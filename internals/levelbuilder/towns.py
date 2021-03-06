from copy import deepcopy
from math import floor
import os
import random

from internals.constants import level_width, level_height
from tiles import get_building_tiles, overlay


BUILDINGS = ("plaza", "well", "church", "clock", "library",
             "graveyard", "shop", "house", )
TOWN_CENTERS = ("plaza", "well", )
BUILDING_ENTITIES = dict(zip(BUILDINGS, map(get_building_tiles, BUILDINGS)))
REPEATABLE_BUILDINGS = ("shop", "house", )

ROAD_WIDTH = 4
ROAD_MATERIAL = 81
ROAD_MAJOR_TILES = {(1, 1, 1, 1): 81,
                    (1, 1, 0, 0): 85,
                    (1, 0, 0, 1): 87,
                    (0, 1, 1, 0): 75,
                    (0, 0, 1, 1): 77,
                    (1, 1, 0, 1): 86,
                    (0, 1, 1, 1): 76,
                    (1, 0, 1, 1): 82,
                    (1, 1, 1, 0): 80, }
ROAD_MINOR_TILES = {(0, 1, 1, 1): 78,
                    (1, 0, 1, 1): 79,
                    (1, 1, 0, 1): 83,
                    (1, 1, 1, 0): 84, }


def smooth_roads(grid):
    """
    Replaces road tiles with the appropriate "smoothed" road segments. Adds,
    in most cases, curbs. Makes towns look 100% less like shite.
    """

    is_road = lambda x: x == ROAD_MATERIAL

    ogrid = deepcopy(grid)
    for row in range(1, len(grid) - 1):
        for col in range(1, len(grid[row]) - 1):
            # Skip processing for non-roads.
            if not is_road(grid[row][col]):
                continue

            major_signature = map(int, (is_road(ogrid[row - 1][col]),
                                        is_road(ogrid[row][col + 1]),
                                        is_road(ogrid[row + 1][col]),
                                        is_road(ogrid[row][col - 1]), ))
            major_signature = tuple(major_signature)
            if major_signature not in ROAD_MAJOR_TILES:
                continue
            new_value = ROAD_MAJOR_TILES[major_signature]
            if new_value != ROAD_MATERIAL:
                grid[row][col] = new_value
                continue

            minor_signature = map(int, (is_road(ogrid[row - 1][col - 1]),
                                        is_road(ogrid[row - 1][col + 1]),
                                        is_road(ogrid[row + 1][col - 1]),
                                        is_road(ogrid[row + 1][col + 1]), ))
            if all(minor_signature):
                continue
            grid[row][col] = ROAD_MINOR_TILES[tuple(minor_signature)]

    return grid


def build_town(grid, hitmap, seed=0):
    """Run the town building algorithm on a tile grid."""

    # The future home of portals generated by building placement.
    portals = []

    def overlay_portals(portal, x, y):
        p = deepcopy(portal)
        p["x"] += x
        p["y"] += y
        portals.append(p)

    available_buildings = list(BUILDINGS)

    center = random.choice(TOWN_CENTERS)
    center_entity = BUILDING_ENTITIES[center]

    midpoint_x, midpoint_y = floor(level_width / 2), floor(level_height / 2)

    center_x = int(midpoint_x - floor(center_entity[0] / 2))
    center_y = int(midpoint_y - floor(center_entity[1] / 2))

    # Boundaries are in the form (top, right, bottom, left)
    town_boundaries = [center_y, center_x + center_entity[0],
                       center_y + center_entity[1] + ROAD_WIDTH, center_x]

    grid, hitmap, loc_portals = overlay(grid, hitmap, center_entity,
                                        center_x, center_y)
    for portal in loc_portals:
        overlay_portals(portal, center_x, center_y)

    available_buildings.remove(center)

    building_limit = random.randint(6, 15)
    building_count = 0

    # The internal position is represented with a point that's located
    # somewhere along the internal spiral. Since this isn't the coordinate
    # that the building is actually going to be placed at (since the building's
    # actual location is potentially (x - width) or (y - height) from this
    # point), we use these defs to offset this point by the building's height
    # and width.
    direction_defs = {0: (0, 0),
                      1: (-1, 0),
                      2: (-1, -1),
                      3: (0, -1)}

    def fill_road(grid, x, y, w, h):
        for i in range(h):
            for j in range(w):
                grid[y + i][x + j] = ROAD_MATERIAL

    iteration = 0

    while (all(10 < x < 90 for x in town_boundaries) and
           building_count <= building_limit):

        iteration += 1

        old_boundaries = town_boundaries[:]

        # 0 - down, 1 - left, 2 - up, 3 - right
        for direction in range(4):

            # Step 1: Place an object in the direction that we're now facing.
            if direction == 0:
                x, y = old_boundaries[1] + ROAD_WIDTH, old_boundaries[0]
            elif direction == 1:
                x, y = old_boundaries[1], old_boundaries[2]
            elif direction == 2:
                x, y = old_boundaries[3] - ROAD_WIDTH, old_boundaries[2]
            elif direction == 3:
                x, y = old_boundaries[3], old_boundaries[0] - ROAD_WIDTH

            # Set conditions (per direction) for when the town border has been
            # surpassed.
            border_conds = {0: lambda: y > old_boundaries[2],
                            1: lambda: x < old_boundaries[3],
                            2: lambda: y < old_boundaries[0],
                            3: lambda: x > town_boundaries[1]}

            widest_building = 0
            building_w, building_h = 0, 0
            while not border_conds[direction]():
                building = random.choice(available_buildings)
                if building not in REPEATABLE_BUILDINGS:
                    available_buildings.remove(building)

                building_entity = BUILDING_ENTITIES[building]

                # Determine the building's offset from the spiral's position.
                building_w, building_h, temp, temp2, b_portals = building_entity
                offset_x, offset_y = direction_defs[direction]
                offset_x *= building_w
                offset_y *= building_h

                # Place the building on the grid.
                grid, hitmap, loc_portals = overlay(grid, hitmap,
                                                    building_entity,
                                                    x + offset_x, y + offset_y)
                for portal in loc_portals:
                    overlay_portals(portal, x + offset_x, y + offset_y)

                if direction == 0:
                    y += building_h
                    if building_entity[0] > widest_building:
                        widest_building = building_w
                elif direction == 1:
                    x -= building_w
                    if building_h > widest_building:
                        widest_building = building_h
                elif direction == 2:
                    y -= building_h
                    if building_w > widest_building:
                        widest_building = building_w
                elif direction == 3:
                    x += building_w
                    if building_h > widest_building:
                        widest_building = building_h

                building_count += 1

            if direction == 0:
                fill_road(grid, old_boundaries[1], old_boundaries[0],
                          ROAD_WIDTH, y - old_boundaries[0])
                town_boundaries[2] = min(y, town_boundaries[2])
                town_boundaries[1] = x + widest_building
            elif direction == 1:
                if iteration == 1:
                    # If we're drawing the first spiral around the center
                    # object, we want there to be a road below the center
                    # object as well as below the line of buildings.
                    fill_road(grid=grid,
                              x=x - building_w,
                              y=old_boundaries[2] - ROAD_WIDTH,
                              w=max(old_boundaries[1] - x + building_w,
                                    center_entity[0] + ROAD_WIDTH),
                              h=ROAD_WIDTH)
                fill_road(grid=grid,
                          x=x - building_w,
                          y=y + widest_building,
                          w=old_boundaries[1] - x + building_w,
                          h=ROAD_WIDTH)
                town_boundaries[3] = min(x, town_boundaries[3])
                town_boundaries[2] = y + widest_building + ROAD_WIDTH
                # Draw the extension of the road to the right.
                fill_road(grid=grid,
                          x=old_boundaries[1], y=old_boundaries[2],
                          w=ROAD_WIDTH,
                          h=town_boundaries[2] - old_boundaries[2])
            elif direction == 2:
                fill_road(grid, x, min(y, old_boundaries[0]),
                          ROAD_WIDTH,
                          max(old_boundaries[2] - y,
                              old_boundaries[2] - old_boundaries[0]))
                town_boundaries[3] = x - widest_building
                town_boundaries[0] = max(y, town_boundaries[0])
            elif direction == 3:
                fill_road(grid, old_boundaries[3], y,
                          max(x - old_boundaries[3],
                              town_boundaries[1] - old_boundaries[3]),
                          ROAD_WIDTH)
                town_boundaries[1] = max(x, town_boundaries[1])
                town_boundaries[0] = y - widest_building

            if building_count > building_limit:
                break

    smooth_roads(grid)

    return grid, hitmap, portals


