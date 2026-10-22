"""Company: time together with the guest, and the creatures the guest let in."""
import time

from ...context import S
from ...world import TOGETHER_LOOPS
from .. import bonds, emotions


def shoo(a, body):
    """Shoos out a creature (a bird, a spider…) by id, or the first one if none is named."""
    gone = [v for v in S["visitors"] if a.get("id") in (None, v["id"])][:1]
    S["visitors"] = [v for v in S["visitors"] if v not in gone]
    if gone:
        a["id"], a["name"], a["room"] = gone[0]["id"], gone[0]["name"], gone[0]["room"]  # the page walks her to it


def after_chain(actions, body):
    """Time together starts with an action marked "together" (a date, a film, a dance…) and ends
    when she turns to something that doesn't belong to it."""
    started = next((a["together"] for a in actions if a.get("together")), None)
    if started:
        bonds.grow_closeness(4.0, "together")
        custom_text = (S.get("invite") or {}).get("text") if started == "custom" else None
        S["together"] = {"kind": started, "since": time.time(), "text": custom_text}
        S["invite"] = None
        S["emo"]["longing"] = 0
        emotions.appraise("joy", 0.5)
        if started == "date":
            emotions.appraise("shyness", 0.3)
    elif S.get("together") and actions and body.loop not in TOGETHER_LOOPS[S["together"]["kind"]] \
            and not any(a["do"] in ("cook", "music_on", "change_clothes") for a in actions):
        S["together"] = None


EFFECTS = {"shoo": shoo}
