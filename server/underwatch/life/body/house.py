"""Trouble in the flat: the leak under the sink and the water on the floor."""
from ...context import S


def close_valve(a, body):
    """Turns the water off under the sink; what is on the floor still has to be mopped."""
    S["leak"] = False


def after_chain(actions, body):
    """Mopping a dry floor makes no sense: she just stands."""
    if body.loop == "mop" and S["water"] <= 0:
        body.loop = None


EFFECTS = {"close_valve": close_valve}
