"""The kitchen: cooking, eating, coffee and the dirty dishes they leave."""
from ...context import S
from .. import needs


def cook(a, body):
    """Cooks at the stove; a pan goes into the sink."""
    S["dishes"] = min(8, S.get("dishes", 0) + 1)


def eat(a, body):
    """Eats; one more plate for the sink."""
    S["dishes"] = min(8, S.get("dishes", 0) + 1)


def coffee(a, body):
    """Brews a cup at the stove and drinks it: +12 energy for the first cup of the day, half as much for each next one."""
    from ...clock import now
    day = now().strftime("%Y-%m-%d")
    if S.get("coffee_day") != day:
        S["coffee_day"], S["coffee_cups"] = day, 0
    S["needs"]["energy"] = needs.clampn(S["needs"]["energy"] + 12 * 0.5 ** S["coffee_cups"])
    S["needs"]["bladder"] = needs.clampn(S["needs"]["bladder"] - 15)
    S["coffee_cups"] += 1
    S["dishes"] = min(8, S.get("dishes", 0) + 1)


def wash_dishes(a, body):
    S["dishes"] = 0


EFFECTS = {"cook": cook, "eat": eat, "coffee": coffee, "wash_dishes": wash_dishes}
