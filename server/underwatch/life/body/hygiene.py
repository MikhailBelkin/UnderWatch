"""The bathroom: shower, toilet, teeth, washing. Their effect on needs is in needs.INSTANT and needs.PER_MIN."""
from ...context import S


def shower(a, body):
    """Undresses for the shower (a gifted accessory comes off too). Afterwards she is in a towel — see after_chain."""
    S["accessory"] = None


def after_chain(actions, body):
    """Out of the shower in a towel: after a shower earlier in this chain or a shower that was going on, unless she dressed afterwards."""
    last_shower = max((i for i, a in enumerate(actions) if a["do"] == "shower"), default=-1)
    dressed_after = any(a["do"] == "change_clothes" for a in actions[last_shower + 1:])
    if body.loop != "shower" and not dressed_after and (S["loop"] == "shower" or last_shower >= 0):
        S["outfit"] = {"type": "towel", "color": None}


EFFECTS = {"shower": shower}
