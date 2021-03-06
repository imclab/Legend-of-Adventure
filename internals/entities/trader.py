from npc import NPC
from internals.levelbuilder.towns import ROAD_MATERIAL


class Trader(NPC):

    def __init__(self, *args):
        super(Trader, self).__init__(*args)
        self.messages = ["What're ya buyin?", "Greetings, stranger!",
                         "Come back anytime.",
                         "Got somethin' that might interest ya. Heh heh heh!"]

    def can_place_at(self, x, y, grid, hitmap):
        return grid[y][x] == ROAD_MATERIAL

    def get_placeable_locations(self, grid, hitmap):
        """
        Return a list of 2-tuples containing the X,Y coordinates of locations
        that the entity can be placed at. This is used to randomly place
        entities in a location.
        """
        street_locations = []
        for y in xrange(len(grid)):
            for x in xrange(len(grid[y])):
                if grid[y][x] == ROAD_MATERIAL:
                    street_locations.append((x, y))
        return street_locations
