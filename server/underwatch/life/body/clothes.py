"""Clothes: changing at the wardrobe. (A towel after the shower is in hygiene.py.)"""
import random

from ...context import R, S
from ...settings import trait
from ...world import COLORS
from .. import state


def wants_privacy(asked=None):
    """Whether she hides while changing or in the shower (the wardrobe door, the frosted glass).
    Outside the 18+ mode, always. In it, the model may decide (asked is True/False); when it doesn't, her character
    does: romance, sociability and composure make her bolder, closeness with the guest lets that show, shyness right now holds it back."""
    if R().meta.get("rel", "romantic") != "romantic":
        return True
    if asked in (True, False):
        return asked
    openness = 0.5 * trait("romance") + 0.3 * trait("extraversion") + 0.2 * (1 - trait("sensitivity"))
    p_open = openness * min(1.0, S.get("closeness", 0) / 70) * (1 - S["emo"].get("shyness", 0))
    return random.random() >= p_open


def change_clothes(a, body):
    """Puts on another outfit. Everyday clothes get a new colour unless one is asked for; a gifted scarf comes off.
    a["private"] (only in the 18+ mode) says whether she hides behind the wardrobe door — the page draws it."""
    S["accessory"] = None
    typ = a.get("outfit") or "casual"
    col = a.get("color") or (random.choice([c for c in COLORS if c != state.outfit_of().get("color")]) if typ == "casual" else None)
    S["outfit"] = {"type": typ, "color": col}
    a["outfit"], a["color"] = typ, col  # the page dresses her in exactly this
    


EFFECTS = {"change_clothes": change_clothes}
