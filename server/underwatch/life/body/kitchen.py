"""The kitchen: cooking, eating and the dirty dishes they leave."""
from ...context import S


def cook(a, body):
    """Cooks at the stove; a pan goes into the sink."""
    S["dishes"] = min(8, S.get("dishes", 0) + 1)


def eat(a, body):
    """Eats; one more plate for the sink."""
    S["dishes"] = min(8, S.get("dishes", 0) + 1)


def wash_dishes(a, body):
    S["dishes"] = 0


EFFECTS = {"cook": cook, "eat": eat, "wash_dishes": wash_dishes}
