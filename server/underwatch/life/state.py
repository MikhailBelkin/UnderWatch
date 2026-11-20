"""The resident's state: defaults, what the page sees, clothes, the identity the player wrote."""

import time

from ..context import S, busy_what, state_lock, store
from ..clock import is_awake_time, next_wake, now, today_sleep
from ..world import COLORS
from ..brain import mind_paused
from . import needs, wardrobe


SEED_SELF = """- Полёт к Проксиме только начался: обживаю корабль, привыкаю к тишине и звёздам за иллюминатором.
- Люблю виниловые пластинки, простые сериалы и готовить что-нибудь на скорую руку на камбузе.
- Хочу каждый день делать зарядку и читать хотя бы по полчаса.
- На Земле остались родные и друзья: пишу им видеописьма, ответы идут неделями."""

DEFAULT_STATE = {
    "name": "Лёва", "male": True, "location": "sofa", "loop": "sit", "label": "сидит на диване",
    "until": 0, "tv": "off", "console": False, "music": False, "outfit": "blue", "mood": "joy",
    "emo": {"joy": 0.35, "sadness": 0, "fear": 0, "anger": 0, "surprise": 0, "disgust": 0, "contempt": 0,
            "shyness": 0, "jealousy": 0, "longing": 0},
    "last_guest_ts": 0, "last_initiative": 0, "dormant": False, "together": None, "invite": None,
    "lights": {"cabin": True, "night": False, "lounge": True, "galley": True, "bridge": True, "bath": False, "lock": False}, "water": 0.0, "leak": False,
    "react_at": 0, "react_reasons": [], "last_react": 0, "touch_log": [], "flowers_ts": 0,
    "items": [], "wishes": [], "visitors": [], "next_id": 1, "dishes": 0, "accessory": None, "pose_hold": None, "rest": None,
    "guest_facts": [], "closeness": 0.0, "closeness_day": "", "closeness_today": 0.0, "goal": None, "goals_done": [],
    "needs": {"hunger": 70, "energy": 85, "fun": 55, "social": 50, "hygiene": 70, "bladder": 80},
    "thought": "", "intent": "", "plan": [], "plan_day": "", "act_seq": 0, "last_act": None,
    "last_tick": 0, "last_decide": 0, "reflect_ts": 0, "reflect_day": "",
    "voyage_start": 0, "sky": None, "sky_next": 0, "sky_last": "", "hull": None, "patches": [], "eva_since": 0, "duty_ts": 0,
}


def public_state():
    with state_lock:
        s = {k: S[k] for k in ("name", "male", "location", "loop", "label", "until", "tv", "console", "music", "lights", "water", "leak", "flowers_ts", "items", "wishes", "visitors", "together", "invite", "dishes", "accessory", "pose_hold", "rest", "guest_facts", "closeness", "goal", "goals_done",
                               "outfit", "mood", "emo", "needs", "thought", "intent", "plan", "act_seq", "last_act",
                               "voyage_start", "sky", "hull", "patches", "eva_since")}
    s["now"] = time.time()  # the page keeps its sky in step with the server's clock
    s["mind_paused"] = mind_paused()  # one switch for the whole machine
    t = now()
    s["awake_time"] = is_awake_time(t)
    s["wake_at"] = next_wake(t).timestamp()
    s["sleep_at"] = today_sleep(t).timestamp()
    s["busy"] = busy_what["v"]
    with state_lock:
        s["needs_view"] = needs.needs_view()
    s["needs"] = {k: round(v, 1) for k, v in s["needs"].items()}
    s["emo"] = {k: round(v, 3) for k, v in s["emo"].items()}
    return s


def outfit_of():
    o = S.get("outfit")
    return {"type": "casual", "color": o} if isinstance(o, str) else (o or {"type": "casual", "color": "blue"})


def outfit_text():
    if S.get("loop") == "shower":
        return "ничего — ты в душе, одежда аккуратно сложена рядом; выйдешь в полотенце"
    if S.get("loop") == "eva":
        return "скафандр (ты снаружи, в открытом космосе)"
    o = outfit_of()
    name = "плавки" if o["type"] == "swimsuit" and S["male"] else wardrobe.label(o["type"])
    return name + (f", цвет {COLORS[o['color']]}" if o.get("color") in COLORS and o["type"] != "towel" else "")


def identity():
    """Who the resident is — written by the player, never rewritten by the resident."""
    return (store.get("identity") or "").strip()


def notes():
    return {"self": store.get("self_notes") or SEED_SELF, "guest": store.get("guest_notes") or "", "identity": identity(), "day": store.get("day_memory") or ""}
