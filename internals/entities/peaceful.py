from internals.constants import FLEE_DISTANCE
from sentient import SentientAnimat


class PeacefulAnimat(SentientAnimat):
    """
    A PeacefulAnimat will behave like any animat, however, it will flee when
    it is attacked.
    """

    def _saw_attack(self, attacker):
        """
        Detect attacks that are close to the entity and flee if necessary.
        """

        # If the attack/hit happened less than FLEE_DISTANCE away, flee the
        # attacker.
        if (attacker in self.remembered_distances and
            self.remembered_distances[attacker] < FLEE_DISTANCE):
            self.flee(attacker)

