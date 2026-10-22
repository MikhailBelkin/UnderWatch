"""The resident's settings: schedule, hunger, character traits, looks."""
import json

from .config import SLEEP_H, WAKE_H
from .context import R, SETTINGS, store


TRAITS = {  # key: (low end, high end, default)
    "extraversion": ("интроверт", "экстраверт", 60), "friendliness": ("колючесть", "дружелюбие", 70),
    "romance": ("прагматизм", "романтичность", 50), "positivity": ("пессимизм", "оптимизм", 65),
    "activity": ("лень", "активность", 55), "humor": ("серьёзность", "чувство юмора", 60),
    "curiosity": ("равнодушие", "любопытство", 60), "tidiness": ("небрежность", "аккуратность", 55),
    "sensitivity": ("невозмутимость", "ранимость", 50),
}

# looks: key -> how the model hears it (the page has the colours)
EYES = {"dark": "тёмные", "brown": "карие", "hazel": "ореховые", "green": "зелёные", "blue": "голубые", "gray": "серые"}
HAIR = {"black": "чёрные", "dark": "тёмно-каштановые", "chestnut": "каштановые", "red": "рыжие", "light": "русые",
        "blond": "светлые", "gray": "седые", "pink": "розовые"}
BUST = (0, 1, 2)  # small, medium, large; drawn only for a female resident

DEFAULT_SETTINGS = {"wake": WAKE_H, "sleep": SLEEP_H, "hunger_rate": 1.0, "traits": {k: v[2] for k, v in TRAITS.items()}, "look": {}}


def clean_look(raw):
    """Only known colours and sizes get through; anything else is left to the gender's default."""
    raw = raw if isinstance(raw, dict) else {}
    look = {}
    if raw.get("eyes") in EYES:
        look["eyes"] = raw["eyes"]
    if raw.get("hair") in HAIR:
        look["hair"] = raw["hair"]
    if raw.get("bust") in BUST:
        look["bust"] = raw["bust"]
    return look


def wake_h():
    return int(SETTINGS["wake"])


def sleep_h():
    return int(SETTINGS["sleep"])


def trait(k):
    return max(0, min(100, float(SETTINGS["traits"].get(k, 50)))) / 100


def apply_settings(body):
    errors = []
    new = json.loads(json.dumps(R().settings))
    try:
        if "wake" in body: new["wake"] = int(body["wake"])
        if "sleep" in body: new["sleep"] = int(body["sleep"])
        if "hunger_rate" in body: new["hunger_rate"] = round(max(0.3, min(3.0, float(body["hunger_rate"]))), 2)
        if isinstance(body.get("brain"), dict) and R().admin:  # the GPU and the subscription are the owner's to choose
            bb = body["brain"]
            new["brain"] = {"backend": "local" if bb.get("backend") == "local" else "claude",
                            "fast": str(bb.get("fast") or "")[:80], "deep": str(bb.get("deep") or "")[:80], "fallback": bool(bb.get("fallback", True))}
        if "look" in body:
            new["look"] = clean_look(body["look"])
        for k, v in (body.get("traits") or {}).items():
            if k in TRAITS:
                new["traits"][k] = int(max(0, min(100, float(v))))
    except (TypeError, ValueError):
        errors.append("неверные значения")
    if not (0 <= new["wake"] < new["sleep"] <= 24):
        errors.append("время подъёма должно быть раньше времени сна")
    if errors:
        return "; ".join(errors)
    SETTINGS.clear()
    SETTINGS.update(new)
    store.set("settings", R().settings)
    return None
