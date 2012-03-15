import internals.constants as constants


class InventoryManager(object):

    def __init__(self, *args):
        super(InventoryManager, self).__init__(*args)

        self.inventory = {}

    def registered(self):
        self.inventory[0] = "wsw.sharp.12"
        self.inventory[1] = "f5"
        self.update_inventory()

    def give_item(self, item_code):
        """Give an item with code `item_code` to this manager."""
        if self.inventory_full():
            print "Inventory full!"
            return False

        for i in range(5):
            if i in self.inventory:
                continue
            self.inventory[i] = item_code
            self.update_inventory(i)
            return True

    def use_item(self, slot):
        slot = int(slot)
        if slot not in self.inventory:
            return

        item = self.inventory[slot]
        if item.startswith("w"):
            # TODO: Tweak this to the direction of the player.
            self._notify_location(self.location,
                                  "hit%s" % ":".join(
                                      (self.id, item,
                                       str(int(self.position[0])),
                                       str(int(self.position[1])))))
        else:
            pass
        self.write_message("chaitem daemon\nUsed %s" % item)

    def drop_item(self, slot, direction=None, update=True):
        """
        Throw an item (usually with the U key).

        If `direction` is set to `None`, the item will be thrown in the
        direction that the player is facing. Otherwise, the direction
        specified will be used. `direction` is not converted to a unit vector.

        If `update` is set to False, the inventory dictionary will not be
        modified and the updated inventory will not be sent to the client.
        """
        slot = int(slot)
        if slot not in self.inventory:
            return

        item_code = self.inventory[slot]

        if update:
            # Delete the item from the user's inventory.
            new_inv = {}
            for i in range(len(self.inventory)):
                if i == slot:
                    continue
                new_inv[len(new_inv)] = self.inventory[i]
            self.inventory = new_inv
            self.update_inventory()

        dx, dy = self.position
        if direction is None:
            direction = self.direction
        dx += (direction[0] * 3 + 0.5) * constants.tilesize
        dy += (direction[1] * 3 - 0.5) * constants.tilesize

        self._notify_global("drop", "%s>%s:%s:%d:%d" % (str(self.location),
                                                        self.id, item_code,
                                                        dx, dy))

    def cycle_items(self, direction):
        """Cycle the items in the inventory one slot in `direction`"""
        direction = -1 if direction == "b" else 1
        count = len(self.inventory)
        pos = lambda x: x % count
        new_inv = {}
        for i in range(count):
            new_inv[i] = self.inventory[pos(i + direction)]
        self.inventory = new_inv
        self.update_inventory()

    def empty_inventory(self):
        self.inventory = {}
        self.update_inventory()

    def inventory_full(self):
        """Returns whether the inventory is full."""
        return len(self.inventory) == 5

    def update_inventory(self, slot=None):
        def get_line(slot):
            if slot not in self.inventory or self.inventory[slot] is None:
                return "%d:" % slot
            else:
                return "%d:%s" % (slot, self.inventory[slot])
        if slot:
            self.write_message("inv%s" % get_line(slot))
        else:
            message = map(get_line, range(5))
            self.write_message("inv%s" % "\n".join(message))


