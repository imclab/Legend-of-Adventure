import json
from math import hypot, sqrt
import random
import time
import uuid

import internals.constants as constants
from internals.hitmapping import get_hitmap


DIRECTIONS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1),
              (1, -1)]
SQRT1_2 = sqrt(0.5)


class ScheduleHelper(object):
    """
    This is a helper mixin that allows you, with the use of an event loop,
    to schedule events in the future. This class will figure out which events
    should fire when the event loop comes around. It should be used instead of
    threads and timers.
    """

    def __init__(self, *args, **kwargs):
        super(ScheduleHelper, self).__init__(*args, **kwargs)

        self.schedule_queue = []

    def schedule(self, seconds, callback):
        """
        Fires `event` off in `seconds` seconds. If `seconds` is 0 (default),
        the event will fire immediately.
        """
        then = time.time() + seconds
        for i in xrange(len(self.schedule_queue)):
            if self.schedule_queue[i][0] >= then:
                self.schedule_queue.insert(i, (then, callback))
                return

        self.schedule_queue.append((then, callback))

    def deschedule(self, callback):
        """Deschedules any occurrances of a particular callback."""
        self.schedule_queue = filter(lambda c: c[1] != callback,
                                     self.schedule_queue)

    def fire_events(self, now=None):
        """Call this function to fire off any events that should have fired."""
        if not now:
            now = time.time()
        for i in xrange(len(self.schedule_queue)):
            then, event = self.schedule_queue[i]
            if then <= now:
                # Fire the event if it was supposed to fire in the past or
                # present.
                event()
            else:
                # If the event is in the future, trim the queue if we've fired
                # anything off.
                if i > 0:
                    self.schedule_queue = self.schedule_queue[i:]
                return

        # If we fire all the events off, clear the queue.
        self.schedule_queue = []


class Entity(object):
    """An entity is any non-player, non-terrain element of the game."""

    def __init__(self, location, x=None, y=None, id=None):
        super(Entity, self).__init__()

        self.dead = False

        self.id = id if id else "%s%s" % (self.get_prefix(),
                                          uuid.uuid4().hex[:8])
        self.height, self.width = 0, 0
        self.position = x, y
        self.location = location
        self.offset = 0, 0

        self.remembered_distances = {}

    def get_prefix(self):
        """Get the prefix for the entity GUID."""
        return "%"

    def forget(self, guid):
        """
        This function is called when a user has left the level, or when the
        server decides that the entity should not recognize the user. This
        method may be overridden, but this method should always be called
        with super().
        """
        if guid in self.remembered_distances:
            del self.remembered_distances[guid]

    def can_despawn(self):
        # TODO: Implement this!
        return True

    def destroy(self, notify=True):
        """
        When this function is called, the entity should be fully cleaned up.
        All resources pointing to this entity should be properly dereferenced.
        """
        if notify:
            self.location.notify_location("del", self.id)

    def place(self, x, y):
        """Set the entity's position at X,Y coordinates."""
        self.position = x, y

    def can_place_at(self, x, y, grid, hitmap):
        """
        Return a boolean value representing whether the entity can be placed at
        an X,Y coordinate on a grid. By default, we return True, but this can
        (and should) be overridden by classes that implement this class.
        """
        return True

    def get_placeable_locations(self, grid, hitmap):
        """
        Return a list of 2-tuples containing the X,Y coordinates of locations
        that the entity can be placed at. This is used to randomly place
        entities in a location.
        """
        return []

    def handle_message(self, message):
        """
        Process and route messages to their appropriate handler functions.
        """
        type, message = message[:3], message[3:]
        if type == "loc":
            guid, x, y, xvel, yvel = message.split(":")
            self._player_movement(guid, x, y)
        elif type == "cha":
            guid, chat_data = message.split(":", 1)

            # Filter out chat from entities, this should be handled directly.
            assert not guid.startswith("@")  # Entity IDs start with an '@'.

            chat_data = chat_data.split("\n", 1)[1]
            if guid not in self.remembered_distances:
                self.on_chat(guid, chat_data)
            else:
                self.on_chat(guid, chat_data,
                             distance=self.remembered_distances[guid])
        else:
            self._handle_message(type, message)

    def _handle_message(self, type, message):
        """
        For use by inherited classes. Called when an unrecognized message is
        passed for inspection.
        """
        pass

    def _player_movement(self, guid, x, y):
        """
        This is an internal function to manage player movement relative to the
        entity. It should only be called when a new, updated position for a
        player is available. Old data should never be posted.

        Player position should be passed in pixels, not tiles.
        """
        x, y = map(int, (x, y))
        distance = hypot(abs(x - self.position[0]), abs(y - self.position[1]))
        distance /= constants.tilesize

        distance = int(distance)

        if guid in self.remembered_distances:
            old_distance = self.remembered_distances[guid]
            if old_distance == distance:
                return
        self.remembered_distances[guid] = distance
        self.on_player_range(guid, distance)

    def on_player_range(self, guid, distance):
        """
        This method is called when the player's distance from the entity
        changes by a unit of constants.PLAYER_RANGES. It should be overridden
        by child classes.
        """
        pass

    def on_chat(self, guid, message, distance=0):
        """
        This method is called when a chat is sent to the current location.
        If distance is available, it is set, otherwise, the value is zero and
        the chat should appear to be coming from a position very near to the
        entity.
        """
        pass

    def write_chat(self, message):
        """Write a line of text to the chats of nearby users."""
        self.location.notify_location(
                "cha",
                "%s:%d:%d\n%s" % (self.id, self.position[0],
                                  self.position[1], message))

    def make_sound(self, sound):
        """Instruct clients to play sound `sound`."""
        self.location.notify_location(
                "snd",
                "%s:%d:%d" % (sound, self.position[0], self.position[1]))

    def _get_properties(self):
        return {"x": self.position[0] / constants.tilesize,
                "y": self.position[1] / constants.tilesize,
                "height": self.height,
                "width": self.width,
                "layer": 0,
                "x_vel": 0,
                "y_vel": 0,
                "image": None,
                "view": {"type": "static"},
                "offset": {"x": self.offset[0],
                           "y": self.offset[1]}}

    def __str__(self):
        return json.dumps(self._get_properties())

    def broadcast_changes(self, *args):
        """
        Broadcast a set of changed properties to the location. This should also
        update other entities of relevant information.
        """
        if self.dead:
            return

        props = self._get_properties()
        def get_prop(key, value=None):
            if value is None:
                value = props
            if "|" in key:
                new_key = key.split("|", 1)
                return get_prop(new_key[1], props[new_key[0]])
            else:
                return value[key]

        builder = lambda x: "%s=%s" % (x, json.dumps(get_prop(x)))
        command = "\n".join(map(builder, args))

        self.location.notify_location("epu", "%s:%s" % (self.id, command))

        # Notify all of the entities of where we're at.
        for entity in self.location.entities:
            if entity is self:
                continue
            entity._player_movement(self.id, self.position[0], self.position[1])


class Animat(Entity, ScheduleHelper):
    """
    An animat is a game entity that is capable of performing animations and
    actions on its own.
    """

    def __init__(self, *args, **kwargs):
        super(Animat, self).__init__(*args, **kwargs)

        self.layer = 0
        self.image = None
        self.view = None

        self.velocity = 0, 0
        self.old_velocity = 0, 0
        self.movement_effect = ""
        self.speed = 1

        self.hitmap = None

        # Properties that are changed on moevement.
        self._movement_properties = ("x_vel", "y_vel", "layer", "x", "y",
                                     "view", )

    def destroy(self, notify=True):
        super(Animat, self).destroy(notify)

        # Since we're being destroyed, delete all of our planned events.
        self.deschedule_all()

    def forget(self, guid):
        """
        We want to make sure we unregister all scheduled events that are
        focused around the user being despawned.
        """
        super(Animat, self).forget(guid)

    def schedule(self, seconds, callback=None):
        if not callback:
            callback = self._on_event

        super(Animat, self).schedule(seconds, callback)

    def deschedule_all(self):
        """Deschedule all of the events in the timer queue."""
        self.schedule_queue = []

    def _on_event(self):
        """
        This method will be called when the event time has fired. It should be
        overridden by child classes.
        """
        pass

    def _updated_position(self, x, y, velocity=None, duration=0):
        if velocity is None:
            velocity = self.velocity
        if duration == 0:
            duration = constants.GAME_LOOP_TICK

        # Adjust for diagonals
        if all(velocity):
            velocity = velocity[0] * SQRT1_2, velocity[1] * SQRT1_2

        new_x = x + velocity[0] * duration * constants.speed * self.speed
        new_y = y + velocity[1] * duration * constants.speed * self.speed
        return new_x, new_y  # Be aware that this doesn't return an int!

    def has_work(self):
        """
        Returns whether the entity has any miscellaneous work to do.
        """
        return any(self.velocity)

    def do_work(self, duration=0, profiler=None):
        """
        This is the method the fires intermittently as the animat moves across
        the level. It should be used to internally update the animat's
        position, recalculate distances to avatars and other entities, and to
        recalculate hitmaps.
        """

        if self.dead: return False

        if profiler: profiler.log("ent>calculating new position")

        now_moving = any(self.velocity)
        velocity = self.velocity

        if now_moving:
            # Calculate the updated position.
            self.position = self._updated_position(*self.position,
                                                   velocity=velocity,
                                                   duration=duration)

            if profiler: profiler.log("ent>hit detection")
            # If the next position isn't a valid place to move, change
            # direction or stop moving.
            if not self._test_position(self.position, velocity):
                #self.write_chat("Oh no, I almost hit a wall.")
                nd_x, nd_y = self._get_best_direction()
                next_direction_back = nd_x * -1, nd_y * -1
                if next_direction_back == velocity:
                    self.move(0, 0)
                else:
                    self.move(nd_x, nd_y)
                # Also don't keep calculating the next position.
                now_moving = False

        if now_moving:
            if profiler: profiler.log("ent>updating other ents")
            # We're moving, didn't stop, and didn't hit a wall.
            for entity in self.location.entities:
                if entity is self:
                    continue
                entity._player_movement(self.id, self.position[0],
                                        self.position[1])

        if profiler: profiler.log("ent>other")

    def get_movable_directions(self):
        """
        Return a list of directions that the entity can move in, given its
        current position.
        """
        def calculate_next_position(velocity):
            new_position = self._updated_position(*self.position,
                                                  velocity=velocity)
            return self._test_position(new_position, velocity)

        return filter(calculate_next_position, DIRECTIONS)

    def _get_best_direction(self, weighted=False):
        """
        If the entity were to be stopped and forced to choose a new direction
        to move in based on surrounding entities and players, which direction
        would it move in?

        If `weighted` is false, surrounding entities will not be considered.
        Rather, this function will simply alias `get_movable_directions`. This
        base class does not implement `weighted` by default, and has no concept
        of direction weight.
        """
        usable_directions = self.get_movable_directions()

        if len(usable_directions) == 1:
            return usable_directions[0]
        elif not usable_directions:
            # It's unlikely that we'll be moving in the future if we can't
            # move now.
            self.write_chat("I'm stuck!")
            return

        return random.choice(usable_directions)

    def _test_position(self, position, velocity=None):
        """
        Test that a particular position for a given velocity is a value that
        doesn't fall on a value that is solid.
        """

        if velocity and any(velocity):
            x, y = self._updated_position(*position, velocity=velocity)
        else:
            x, y = position

        x_t, y_t = map(lambda i: int(i / constants.tilesize), (x, y))

        # Test that the next position is within bounds.
        width = self.location.location.width()
        height = self.location.location.height()
        if (x_t < 2 or x_t > width - 2.5 or
            y_t < 2 or y_t > height - 2.5):
            return False

        # Test that the next position is solid.
        hitmap = self.location.location.generate()[1]
        x_hitmap, y_hitmap = get_hitmap((x, y), hitmap)
        if (x < x_hitmap[0] or x + self.width > x_hitmap[1] or
            y < y_hitmap[0] or y + self.height > y_hitmap[1]):
            return False

        # Perform corner testing if the intended direction is along a diagonal.
        if velocity and all(velocity):
            x, y = self.position
            x2, y2 = x + self.width, y + self.height
            x, y, x2, y2 = map(lambda x: int(x / constants.tilesize),
                               (x, y, x2, y2))

            x2 = min(x2, width - 1)
            y2 = min(y2, height - 1)

            if any([hitmap[y2][x2], hitmap[y][x2], hitmap[y2][x],
                    hitmap[y][x]]):
                return False

        return True

    def move(self, x_vel, y_vel, broadcast=True, event=True):
        """Start the sprite moving in any direction, or stop it from moving."""

        changed = x_vel != self.velocity[0] or y_vel != self.velocity[1]
        if not changed:
            return

        self.old_velocity, self.velocity = self.velocity, (x_vel, y_vel)
        # TODO: This is where the fix for bug #11 will go.
        self.layer = 1 if x_vel or y_vel else 0

        # Perform hitmapping, but don't take the Y offset into account. We want
        # to hit the left edge properly, but the top edge might actually be
        # representing the bottom edge.
        self.hitmap = get_hitmap((self.position[0] - self.offset[0],
                                  self.position[1]),
                                 self.location.location.generate()[1])

        if broadcast:
            self.broadcast_changes(*self._movement_properties)

    def wander(self):
        def callback():
            best_direction = self._get_best_direction()
            if not best_direction:
                return
            self.move(*best_direction)
            self.wandering = True
            self.schedule(random.randint(1, 4), self.stop_wandering)

        # Move the callback into the future so we can finish initializing the
        # entity.
        self.schedule(0.25, callback)

    def stop_wandering(self):
        self.move(0, 0)
        self.wandering = False
        self.schedule(random.randint(1, 3), self.wander)

    def can_place_at(self, x, y, grid, hitmap):
        return not hitmap[y][x]

    def get_placeable_locations(self, grid, hitmap):
        """
        We only want animats to be able to spawn on walkable surfaces, so only
        return those locations.
        """
        # Make our life easy: if everything's walkable, tell the server to just
        # pick a random location.
        if all(all(not cell for cell in row) for row in hitmap):
            return []

        locations = []
        hitmap_len = len(hitmap)
        for rownum in range(int(0.1 * hitmap_len), int(0.9 * hitmap_len)):
            row = hitmap[rownum]
            row_len = len(row)
            for cellnum in range(int(0.1 * row_len), int(0.9 * row_len)):
                if not row[cellnum]:
                    locations.append((cellnum, rownum))
        return locations if locations else None

    def _get_properties(self):
        baseline = super(Animat, self)._get_properties()
        baseline["x_vel"] = self.velocity[0]
        baseline["y_vel"] = self.velocity[1]

        baseline["image"] = self.image
        baseline["layer"] = self.layer
        baseline["view"] = self.view

        return baseline

        #"sprite": {"x": 0, "y": 0,
        #           "swidth": 32, "sheight": 32,
        #           "awidth": 65, "aheight": 65}

