import json
from Queue import Queue
import random
import multiprocessing
import threading
import time

import redis

import internals.constants as constants
import internals.entities.items as items
from internals.entities.entities import Animat
from internals.locations import Location


redis_host, port = constants.redis.split(":")

LOOP_TICK = constants.GAME_LOOP_TICK / 1000
MESSAGES_TO_IGNORE = ("spa", "epu", )
MESSAGES_TO_INSPECT = ("del", "cha", )


class ThreadedRedisReader(threading.Thread, object):

    def __init__(self, pubsub):
        super(ThreadedRedisReader, self).__init__()
        self.pubsub = pubsub
        self.output_queue = Queue()

        self.start()

    def run(self):
        for event in self.pubsub.listen():
            self.output_queue.put(event)

    def events_waiting(self):
        return not self.output_queue.empty()

    def get_events(self):
        while not self.output_queue.empty():
            yield self.output_queue.get()


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
        self.players = set()
        self.ttl = None

    def _setup(self):
        redis_host, port = constants.redis.split(":")
        self.outbound_redis = redis.Redis(host=redis_host, port=int(port))

        if self._initial_message_data:
            self.on_enter(self._initial_message_data, initial=True)
            self._initial_message_data = None

    def _end(self):
        # Cancel any TTL timer.
        if self.ttl:
            self.ttl.cancel()

        # Destroy entities that still exist.
        for entity in self.entities:
            entity.destroy()

        self.terminate()

    def run(self):

        self._setup()

        inbound_redis = redis.Redis(host=redis_host, port=int(port))
        pubsub = inbound_redis.pubsub()
        pubsub.subscribe("global::enter")
        pubsub.subscribe("global::drop")
        pubsub.subscribe("location::p::%s" % self.location)
        pubsub.subscribe("location::pe::%s" % self.location)

        sub_manager = ThreadedRedisReader(pubsub)

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
            if sub_manager.events_waiting():
                for event in sub_manager.get_events():
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
        self.players.add(guid)

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

        self.players.discard(user)
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

            e.place(x * constants.tilesize, y * constants.tilesize)
            placeable_locations = None  # Free up that memory!
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
        self.outbound_redis.publish(
                "location::e::%s" % self.location,
                "%s>%s%s" % (self.location, command, message))

        if to_entities:
            full_message = "%s%s" % (command, message)
            for entity in self.entities:
                entity.handle_message(full_message)

