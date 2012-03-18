memcached = "127.0.0.1:11211"
redis = "127.0.0.1:6379"

port = 8080

level_grad_resolution = 4
level_width = 75
level_height = 75
tilesize = 50
framerate = 30  # FPS
speed = 0.2  # Pixels per tick

entity_despawn_time = 60 * 10

MESSAGES_WITH_GUIDS = ("loc", "add", "del", "cha", "giv")
PLAYER_RANGES = 3

# The distance that a player can hear chat messages from.
CHAT_DISTANCE = 8
# The distance that an attack startles an entity from.
FLEE_DISTANCE = 15
# The distance that a hostile mob will notice a player/entity from.
CHASE_DISTANCE = 25
# The distance that an attack hurts from.
HURT_DISTANCE = 1

GAME_LOOP_TICK = 50  # 50ms
TICK = 1.0 / framerate
