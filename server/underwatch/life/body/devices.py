"""The flat's devices: the TV, the console, the record player and the lights."""
from ...context import S
from ...world import ROOMS, room_of


def watch_tv(a, body):
    """Sits down on the sofa and turns the TV on (the walk and the sitting come from the action table)."""
    S["tv"] = "show"


def play_game(a, body):
    """Turns the console on; the TV shows the game. A gifted steering wheel or gamepad is taken by the page itself."""
    S.update(tv="game", console=True)


def tv_off(a, body):
    S["tv"] = "off"
    if body.loop in ("watch", "game"):  # nothing to look at any more: just sitting
        body.loop = "sit"


def console_off(a, body):
    S["console"] = False
    if S["tv"] == "game":
        S["tv"] = "show"
    if body.loop == "game":
        body.loop = "sit"


def music_on(a, body):
    S["music"] = True


def music_off(a, body):
    S["music"] = False


def light(a, body, on):
    """Lights of one room (or all of them); with no room given, the room she is in."""
    room = a.get("room") or room_of(body.loc)
    a["room"] = room  # the page needs to know which lamps
    for k in ROOMS[room]:
        S["lights"][k] = on


EFFECTS = {"watch_tv": watch_tv, "play_game": play_game, "tv_off": tv_off, "console_off": console_off,
           "music_on": music_on, "music_off": music_off,
           "light_on": lambda a, body: light(a, body, True), "light_off": lambda a, body: light(a, body, False)}
