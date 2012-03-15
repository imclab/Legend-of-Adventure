from math import sqrt
from Queue import Queue, Empty
import random
import multiprocessing
import threading
import time

import redis

import internals.constants as constants
from internals.constants import tilesize
import internals.entities.items as items
from internals.entities.entities import Animat
from internals.locations import Location


redis_host, port = constants.redis.split(":")

LOOP_TICK = constants.GAME_LOOP_TICK / 1000
MESSAGES_TO_IGNORE = ("spa", "epu", )
MESSAGES_TO_INSPECT = ("del", "cha", )


class ThreadedRedisReader(threading.Thread, object):

    def __init__(self, pubsub, outbound):
        super(ThreadedRedisReader, self).__init__()
        self.pubsub = pubsub
        self.outbound = outbound
        self.output_queue = Queue()
        self.input_queue = Queue()

        self.start()

    def run(self):
        for event in self.pubsub.listen():
            self.output_queue.put(event)

    def events_waiting(self):
        return not self.output_queue.empty()

    def get_events(self):
        while not self.output_queue.empty():
            yield self.output_queue.get()

    def publish(self, channel, message):
        """Queue a message to be send to the front end."""
        self.input_queue.put((channel, message))

    def flush(self):
        """Push all queued messages to the front end."""

        # TODO: Implement multi-message packets here.
        try:
            while not self.input_queue.empty():
                channel, message = self.input_queue.get(False)
                self.outbound.publish(channel, message)
        except Empty:
            # If we hit the bottom of the queue, just move along.
            pass


class SimulatedPlayer(object):
    """
    A simulated player object is used as a caching mechanism. Rather than
    pushing player location over and over through redis, only the player's
    changes in direction and velocity are broadcast (as they would be to other
    players). This information is then used, with the help of the event loop,
    to predict the player's location and status at any given time.
    """

    def __init__(self, guid):
        self.id = guid
        self.position = 0, 0
        self.velocity = 0, 0
        self.updated = False

    def post_velocity(self, x, y, x_vel, y_vel):
        """Post an updated position and velocity."""
        self.position = map(int, (x, y))
        self.velocity = map(int, (x_vel, y_vel))

        self.updated = True

    def on_tick(self, period):
        """Simulate an update based on the duration of the game tick."""
        x_vel, y_vel = self.velocity

        did_update = False
        if x_vel:
            self.position[0] += x_vel * period * constants.speed
            did_update = True
        if y_vel:
            self.position[1] += y_vel * period * constants.speed
            did_update = True

        if did_update or self.updated:
            self.updated = False
            x, y = self.position
            return lambda e: sqrt((e.position[0] - x) ** 2 +
                                  (e.position[1] - y) ** 2) / tilesize

        return None

class EntityServlet(multiprocessing.Process):
    """
    A location handler manages all entities and entity interactions for a
    single location.
    """

    def __init__(self, location, message_data=None):
        super(EntityServlet, self).__init__()

        self.location = Location(location)
        self._initial_message_data = message_data

        self.entities = []
        self.players = {}
        self.ttl = None

    def _end(self):
        # Cancel any TTL timer.
        if self.ttl:
            self.ttl.cancel()

        # Destroy entities that still exist.
        for entity in self.entities:
            entity.destroy()

        self.terminate()

    def run(self):
        redis_host, port = constants.redis.split(":")
        # We probably don't need a second connection since the pubsub object
        # establishes its own.
        ##outbound_redis = redis.Redis(host=redis_host, port=int(port))

        inbound_redis = redis.Redis(host=redis_host, port=int(port))
        pubsub = inbound_redis.pubsub()
        pubsub.subscribe("global::enter")
        pubsub.subscribe("global::drop")
        pubsub.subscribe("location::p::%s" % self.location)
        pubsub.subscribe("location::pe::%s" % self.location)

        self.sub_manager = ThreadedRedisReader(pubsub, inbound_redis)

        # If we got message data that started up the servlet, handle it now.
        if self._initial_message_data:
            self.on_enter(self._initial_message_data, initial=True)
            self._initial_message_data = None

        last_loop_iteration = 0

        # Enter the location's game loop.
        while 1:
            now = time.time()
            period = now - last_loop_iteration

            # If the duration since the last game tick isn't long enough, wait
            # for a few milliseconds until the time has passed.
            if period < LOOP_TICK:
                time.sleep(LOOP_TICK - period)

            # Handle any waiting events.
            if self.sub_manager.events_waiting():
                for event in self.sub_manager.get_events():
                    if event["type"] != "message":
                        continue
                    self._handle_event(event)

            # Handle any entity-related work.
            for entity in self.entities:
                # Fire off any waiting events for the entity.
                entity.fire_events(now=now)
                # If the entity has other work to do, take care of it.
                if entity.has_work():
                    entity.do_work(period)

            # Iterate each player and see if there's any work to do.
            for guid, player in self.players.items():
                output = player.on_tick(period)
                if output:
                    for entity in self.entities:
                        # Calculate the player's new distance.
                        distance = int(output(entity))
                        # Ignore the update if there's no change in distance.
                        if (guid in entity.remembered_distances and
                            entity.remembered_distances == distance):
                            continue
                        # Save the new distance.
                        entity.remembered_distances[guid] = distance
                        entity.on_player_range(guid, distance)

            # Flush any waiting messages to the front end.
            self.sub_manager.flush()

            last_loop_iteration = now

    def _handle_event(self, event):
        """
        This is a helper function that processes inbound events for this
        region.
        """

        message = event["data"]
        location, full_message_data = message.split(">", 1)
        if (event["channel"] == "global::enter" and
            location == str(self.location)):
            self.on_enter(full_message_data)
            return
        if (event["channel"] == "global::drop" and
            location == str(self.location)):
            self.spawn_drop(full_message_data)
            return

        message_type = full_message_data[:3]
        message_data = full_message_data[3:]

        if (message_type in MESSAGES_TO_IGNORE or
            (message_type in MESSAGES_TO_INSPECT and
             message_data.startswith("@"))):
            return
        if message_type == "del":
            # We don't need to split message_data because it's only one
            # value.
            self.on_leave(message_data)
        elif message_type == "loc":
            # We have our own mechanism for updated the location of players.
            guid, x, y, x_vel, y_vel = message_data.split(":")
            self.players[guid].post_velocity(x, y, x_vel, y_vel)

        # TODO: Event handling code goes here.
        for entity in self.entities:
            entity.handle_message(full_message_data)

    def on_enter(self, message_data, initial=False):
        """
        When a player enters a level, test whether we need to spawn some
        entities. If a timer is set to destroy entities, disable and delete it.
        """
        if self.ttl:
            print "Cleanup of %s cancelled." % self.location
            self.ttl.cancel()
            initial = False

        if initial and self.location.has_entities():
            self.spawn_initial_entities(self.location)
        else:
            # TODO: Move this responsibility to the web server and just keep a
            # copy of the entity data in Redis.
            for entity in self.entities:
                self.spawn_entity(entity)

        guid = message_data.split(":")[0]
        print "Registering user %s" % guid
        self.players[guid] = SimulatedPlayer(guid)

        # TODO: Move this responsibility to the web server and just keep a copy
        # of the entity data in Redis.

    def on_leave(self, user):
        """
        If there are other players in the level, no worries. Detach any events
        tied to the player (mob following, for instance), and you're done. If
        there's nobody else around, start a timer that will destroy the
        entities after a period of time.
        """
        print "Unregistering player %s" % user

        for entity in self.entities:
            entity.forget(user)

        del self.players[user]
        if not self.players:
            print "Last player left %s, preparing for cleanup." % self.location

            def cleanup():
                print "Cleaning up mobs at %s" % self.location
                return self._end()

            # This timer is allowed because it shouldn't be able to be thread
            # unsafe.
            t = threading.Timer(constants.entity_despawn_time, cleanup)
            self.ttl = t
            t.start()

    def destroy_entity(self, entity):
        """Destroy an entity and remove it from the fork."""
        self.entities.remove(entity)
        entity.destroy()

    def spawn_initial_entities(self, location):
        """
        Using data from a location, spawn the initial entities that will roam a
        particular level.
        """
        print "Spawning mobs at %s" % self.location
        spawn_entities = self.location.get_entities_to_spawn()

        for entity in spawn_entities:
            # Initialize the new entity.
            e = entity(self)

            level = self.location.generate()
            placeable_locations = e.get_placeable_locations(*level[:2])

            # Look at the avaialable locations for the entity.
            if placeable_locations is None:
                e.destroy()
                # There are not available locations.
                continue
            elif not placeable_locations:
                # The entity can be placed anywhere.
                width, height = self.location.width(), self.location.height()
                x = random.randint(int(0.1 * width), int(0.9 * width))
                y = random.randint(int(0.1 * height), int(0.9 * height))
            else:
                x, y = random.choice(placeable_locations)

            print "  > %s at (%d, %d)" % (str(entity), x, y)

            e.place(x * tilesize, y * tilesize)
            self.entities.append(e)
            self.spawn_entity(e)

    def spawn_entity(self, entity):
        """Send the command necessary to spawn an entity to the client."""
        self.notify_location("spa", "%s\n%s" % (entity.id, str(entity)))

    def spawn_drop(self, command):
        guid, item, x, y = command.split(":")
        x, y = map(int, (x, y))
        entity = items.ItemEntity(item, x, y, self)
        self.entities.append(entity)
        self.spawn_entity(entity)

    def notify_location(self, command, message, to_entities=False):
        """A shortcut for broadcasting a message to the location."""
        self.sub_manager.publish(
                "location::e::%s" % self.location,
                "%s>%s%s" % (self.location, command, message))

        if to_entities:
            full_message = "%s%s" % (command, message)
            for entity in self.entities:
                entity.handle_message(full_message)

