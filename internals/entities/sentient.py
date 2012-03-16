from math import asin, hypot, pi
from random import choice, randint
import time

from internals.constants import (CHASE_DISTANCE, FLEE_DISTANCE, HURT_DISTANCE,
                                 tilesize)
from entities import Animat
from items import WEAPONS, WEAPON_PREFIXES
from internals.harmable import Harmable


FLEE = 1
CHASE = 2

REEVALUATE_TIME = 0.675

CONVERTED_DIRECTIONS = {0: (1, 0), 45: (1, -1), 90: (0, -1), 135: (-1, -1),
                        180: (-1, 0), 225: (-1, 1), 270: (0, 1), 315: (1, 1)}


class SentientAnimat(Harmable, Animat):
    """
    SentientAnimats are capable of expressing behaviors of living things. The
    fundamental behaviors are flee and chase, as well as attack.
    """

    def __init__(self, *args, **kwargs):
        super(SentientAnimat, self).__init__(*args, **kwargs)

        self.fleeing = set()
        self.chasing = None
        self.flee_point = None

        self.holding_item = None

        self.prefer_behavior = FLEE

        self.does_attack = False
        self.last_attack = 0

    def forget(self, guid):
        super(SentientAnimat, self).forget(guid)

        self.stop_fleeing(guid)

        if self.chasing == guid:
            self.chasing = None

    def flee(self, guid):
        """Mark a GUID as an entity to avoid."""
        if guid in self.fleeing:
            return

        self.fleeing.add(guid)
        self._behavior_changed()

    def stop_fleeing(self, guid):
        """Stop fleeign from a GUID."""
        if guid not in self.fleeing:
            return

        self.fleeing.discard(guid)

    def chase(self, guid):
        """Mark a GUID as an entity to chase."""
        if guid == self.chasing:
            return

        self.chasing = guid
        self._behavior_changed()

    def _behavior_changed(self):
        if not any(self.velocity):
            best_direction = self._get_best_direction()
            if best_direction is None:
                self.move(0, 0)
                self.wander()
                return
            else:
                self.move(*best_direction)

        self.schedule(REEVALUATE_TIME + randint(5, 7) / 11,
                      self._reevaluate_behavior)

    def attack(self, guid):
        now = time.time()
        if now - self.last_attack < 1.5:
            return
        self.last_attack = now

        self.location.notify_location(
            "atk", "%s:%s:%s" % (self.id, self.holding_item or "", guid),
            to_entities=True)

    def wander(self):
        if self.fleeing or self.chasing:
            return

        super(SentientAnimat, self).wander()

    def stop_wandering(self):
        if self.fleeing or self.chasing:
            self._reevaluate_behavior()
            return

        super(SentientAnimat, self).stop_wandering()

    def do_work(self, duration=0, profiler=None):
        """
        Recalculate all of the distances that we've seen. Don't wait for the
        other person to move.
        """
        # Do the work that the entity has to do first.
        super(SentientAnimat, self).do_work(duration, profiler)

        # If we're moving, recalculate the distance to other entities.
        if profiler: profiler.log("ent>sentient>do_work")
        if any(self.velocity):
            x, y = self.position
            for entity in (self.location.entities +
                           self.location.players.values()):
                e_x, e_y = entity.position
                self.remembered_distances[entity.id] = (
                        hypot(abs(x - e_x), abs(y - e_y)) / tilesize)

    def _reevaluate_behavior(self):
        """
        Decide whether we should still be fleeing, and if so, what direction we
        should flee in.
        """

        is_fleeing = self.fleeing
        if self.fleeing:
            if all(self.remembered_distances[x] > FLEE_DISTANCE for
                   x in self.fleeing):
                if_fleeing = False

        if not self.chasing and not is_fleeing:
            self.move(0, 0)
            self.schedule(2, self.wander)
            if not self.fleeing:
                return False
        else:
            dont_move = False
            # Toss out an attack if we can.
            if self.chasing:
                chasing_distance = self.remembered_distances[self.chasing]
                if self.does_attack and chasing_distance <= HURT_DISTANCE:
                    self.attack(self.chasing)
                if chasing_distance < 2:
                    self.move(0, 0)
                    dont_move = True

            if not dont_move:
                best_direction = self._get_best_direction(weighted=True)
                if best_direction is None:
                    self.move(0, 0)
                    self.schedule(3, self.wander)
                    return False
                elif best_direction != self.velocity:
                    self.move(*best_direction)

        self.schedule(REEVALUATE_TIME + randint(5, 7) / 11,
                      self._reevaluate_behavior)
        return True

    def _get_best_direction(self, weighted=False):
        """
        An implementation of `Entity._get_best_direction` that implements
        `weighted`.
        """

        # If we cannot weight our decision, leave it up to the (optimized) base
        # class version of the function.
        behavior = self._flee_or_chase()
        if behavior is None:
            return super(SentientAnimat, self)._get_best_direction()

        usable_directions = self.get_movable_directions()

        if not usable_directions:
            # If we can't move, don't move.
            return
        elif len(usable_directions) == 1:
            # If we can only move in one direction, move in that direction.
            return usable_directions[0]

        x, y = self.position
        if weighted:

            def get_angle(e_x, e_y):
                """
                Convert a set of coordinates (with respect to the current
                entity's position) to an angle representing the direction
                that the coordinates are located in. The angle will always be
                rounded to one of the eight cardinal directions. It will be in
                degrees and not radians to avoid floating point numbers.
                """
                pre_trig = (y - e_y) / hypot(abs(x - e_x), abs(y - e_y))
                theta = asin(pre_trig)

                # Convert to degrees so we're not dealing with floating point
                # numbers.
                theta /= 2 * pi
                theta *= 360

                # Round to the nearest cardinal direction.
                theta += 22  # Rounded from 22.5; we don't need to round "back"
                theta -= theta % 45
                return theta % 360

            def alternate_angles(angle):
                """Return the alternate angles by "best weight"."""
                for count in range(1, 5):
                    yield (angle + 45 * count) % 360
                    yield (angle - 45 * count) % 360

            all_entities = (self.location.entities +
                            self.location.players.values())
            def get_position(guid):
                """
                Return the position of a player/entitiy. This function should
                only be used when a single entity needs to be looked up, since
                it runs in O(N) time.
                """
                for e in all_entities:
                    if e.id == guid:
                        return e.position

            if behavior == FLEE:
                num_fe = len(self.fleeing)
                all_entities = (self.location.entities +
                                self.location.players.values())
                if num_fe > 1:
                    # Get the average of the chasers' positions. We'll flee
                    # from that point.
                    chasers = [e for e in all_entities if e.id in self.fleeing]
                    # This next line may look slow, but there are only a few
                    # chasers at any given time, so it's ok.
                    flee_position = (
                            sum(e.position[0] for e in chasers) / num_fe,
                            sum(e.position[1] for e in chasers) / num_fe)
                else:
                    # Get the chaser's position.
                    flee_position = get_position(self.fleeing.copy().pop())

                # We need to reverse the angle (+180, %360) because we're
                # fleeing and not chasing.
                angle = (get_angle(*flee_position) + 180) % 360

            else:  # CHASE
                # It's so nice and simple because we just need the angle for a
                # single point. And we're going towards it, too!
                angle = get_angle(*get_position(self.chasing))

            # If we can use that angle, go with it. If we can't, look through
            # the list of alternate angles until there's an open angle.
            if CONVERTED_DIRECTIONS[angle] in usable_directions:
                return CONVERTED_DIRECTIONS[angle]
            else:
                for new_angle in alternate_angles(angle):
                    if CONVERTED_DIRECTIONS[new_angle] in usable_directions:
                        return CONVERTED_DIRECTIONS[new_angle]
                # We shouldn't ever get here, but if we do, we should just fall
                # back on random choice (below).

        return choice(usable_directions)

    def _flee_or_chase(self):
        """
        Return `FLEE` if the entity should flee or `CHASE` if the entity should
        be chasing. If entity is neither fleeing nor chasing, return `None`.
        """
        if self.fleeing and self.chasing:
            return FLEE if self.prefer_behavior == FLEE else CHASE
        elif self.fleeing:
            return FLEE
        elif self.chasing:
            return CHASE
        else:
            return None

    def _handle_message(self, type, message):
        """Here, we're going to intercept attack commands and process them."""

        super(SentientAnimat, self)._handle_message(type, message)

        if type not in ("atk", "hit"):
            return

        data = message.split(":")
        # Fire off the _saw_attack function.
        self._saw_attack(attacker=data[0])

        if type == "atk":  # Pre-determined attack
            guid, item, atk_guid = data
            if guid == self.id or atk_guid != self.id:
                return
        elif type == "hit":  # Directed hit
            guid, item, a_x, a_y = data
            if guid == self.id:
                return

            # Calculate how far away the hit is.
            a_x, a_y = float(a_x), float(a_y)
            atk_distance = hypot(abs(self.position[0] - a_x),
                                 abs(self.position[1] - a_y))
            # If the attack is too far away, just ignore it.
            if atk_distance > HURT_DISTANCE:
                return

        self._attacked(guid, item)

    def _attacked(self, attacked_by, attacked_with):
        """
        This is a stub that is called when the entity is specifically attacked.
        It will not be called when the entity suffers environmental or self-
        inflicted damage.
        """
        self.harmed_by(attacked_with, guid=attacked_by)

    def _saw_attack(self, attacker):
        """
        This will be called when the entity witnesses an attack. The attack may
        or may not be on the entity itself. The attack may not have been
        directed at any other entity (i.e.: a user swung his sword).

        This method is meant to be overridden.
        """
        pass

