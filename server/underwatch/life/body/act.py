"""Doing a chain of actions: each action has its own function (see the modules next to this one);
this file walks the chain, keeps track of where the body ends up, and tells the page what to animate."""
import time

from ...context import S, emit_event, g, hub, save_state, state_lock
from ...world import ACTIONS, CHAIN_HOLD, HOW_RU, LOOP_LABEL, PLACES, SURF_RU
from .. import emotions, gifts, goals, needs, state, wardrobe
from . import clothes, company, devices, house, hygiene, kitchen, moves, rest


class Body:
    """Where the chain leaves the resident: the place she is at and the lasting activity she settles into.

    An action moves the body to its place (cook leads to the stove) and either settles it into a loop
    (watch_tv → "watch"), leaves the loop as it was (gestures), or makes it stand (walking, cooking)."""

    def __init__(self):
        self.loop, self.loc = S["loop"], S["location"]
        self.was_sleeping = self.loop == "sleep"

    def go(self, place):
        if place and place != self.loc:
            self.loc, self.loop = place, None


# what each action does to the world, by theme; an action with no entry only moves the body and changes needs
EFFECTS = {**devices.EFFECTS, **clothes.EFFECTS, **hygiene.EFFECTS, **kitchen.EFFECTS, **rest.EFFECTS,
           **house.EFFECTS, **moves.EFFECTS, **company.EFFECTS,
           "practice": lambda a, body: goals.practice(a)}
# what happens once the whole chain is done, in this order
AFTER = [hygiene.after_chain, rest.after_chain, house.after_chain, company.after_chain]


def do_one(a, body):
    """One action: move the body, settle it, apply the action's own effect, the gift it uses, and its effect on needs."""
    d = a["do"]
    place, new_loop, _ = ACTIONS[d]
    if d == "walk_to":
        place = a["place"]
    elif d == "use_item" and a.get("at"):
        place = a["at"]
    body.go(place)
    if new_loop:            # settles into a lasting activity
        body.loop = new_loop
    elif new_loop is None:  # whole-body action: ends up standing
        body.loop = None
    effect = EFFECTS.get(d)
    if effect:
        effect(a, body)
    if a.get("id") is not None and d in gifts.GIFT_ACTIONS:
        gifts.gift_effects(a)
    needs.instant(d)


def label(body):
    """The words for what she is doing once the chain is over."""
    loop, together = body.loop, S.get("together") or {}
    if loop == "rest" and S.get("rest"):
        r = S["rest"]
        return f"{HOW_RU[r['how']][0]} {SURF_RU[r['on']]}"
    if loop == "pose" and S.get("pose_hold"):
        return "замер" + g("", "ла") + " в позе: " + S["pose_hold"]["label"]
    if loop in ("date", "sit", "rest", "pose") and together.get("kind") == "custom":
        return "вместе с гостем: " + (together.get("text") or "")
    return LOOP_LABEL[loop] if loop else "стоит: " + PLACES[body.loc]


def busy_until(actions, body, minutes):
    """When the mind should decide again: after the lasting activity, or as soon as the body is done with a quick chain."""
    span = lambda a: a.get("secs", 0) if a["do"] == "move" else CHAIN_HOLD.get(a["do"], 0)
    hold = sum(span(a) for a in actions[:-1])  # time spent mid-chain (toilet, shower, cooking, free moves...)
    if body.loop == "mop":
        return time.time() + hold + 30 * 60  # mopping lasts until the floor is dry (see needs.update_needs)
    if body.loop == "shower":
        return time.time() + hold + 165  # a shower takes ~2.5 min, then she dries off and decides what's next
    if body.loop in LOOP_LABEL and minutes:
        return time.time() + hold + max(1, float(minutes)) * 60
    if actions:
        return time.time() + sum(span(a) for a in actions) + 30 + 6 * len(actions)
    return S["until"]


def action_text(a):
    """One action as a line in the life feed."""
    d = a["do"]
    if a.get("together") == "custom":
        text = "вместе с гостем: " + ((S.get("together") or {}).get("text") or "")
    elif d == "use_item" and a.get("name"):
        mate = next((x["name"] for x in S["items"] if x["id"] == a.get("with")), "") if a.get("with") else ""
        text = f"{a.get('label') or 'пользуется'}: {a['name']}" + (f" + {mate}" if mate else "")
    elif d == "shoo" and a.get("name"):
        text = f"выгоняет: {a['name']}"
    else:
        text = ACTIONS[d][2]
    if a.get("place"):
        text += " → " + PLACES[a["place"]]
    if d == "change_clothes" and a.get("outfit"):
        text += f" ({wardrobe.label(a['outfit'])})"
    if d == "move":
        text += f": {a.get('label')}"
    return text


def act(actions, minutes=None, thought=None, intent=None, mood=None, aloud=None, source="mind", emotion=None):
    """Apply a chain of actions to the world and tell every open page to animate it."""
    with state_lock:
        body = Body()
        for a in actions:
            do_one(a, body)
        for after in AFTER:
            after(actions, body)
        S["loop"], S["location"] = body.loop, body.loc
        S["label"] = label(body)
        S["until"] = busy_until(actions, body, minutes)
        if thought is not None:
            S["thought"] = thought
        if intent is not None:
            S["intent"] = intent
        if emotion:
            emotions.feel(*emotion)
        elif mood in emotions.MOOD_COMPAT:
            emotions.feel(*emotions.MOOD_COMPAT[mood])
        S["act_seq"] += 1
        S["last_act"] = {"seq": S["act_seq"], "actions": actions, "ts": time.time(), "aloud": aloud or "", "thought": thought or "", "source": source}
        save_state()
        msg = {"type": "act", "seq": S["act_seq"], "actions": actions, "thought": thought or "", "aloud": aloud or "", "source": source, "state": state.public_state()}
    hub.publish(msg)
    if actions:
        emit_event("action", ", ".join(action_text(a) for a in actions), {"actions": actions, "minutes": minutes})
