"""Emotions: Ekman's basic ones plus shyness, jealousy and longing; how they rise, fade and show."""
import time

from ..context import S, state_lock
from ..settings import trait


MOODS = {"happy", "neutral", "sad", "surprised", "angry", "sleepy", "love"}

# Ekman's basic emotions. Each fades on its own clock (minutes); opposites damp each other.
EMOTIONS = {"joy": "радость", "sadness": "грусть", "fear": "страх", "anger": "злость", "surprise": "удивление",
            "disgust": "отвращение", "contempt": "презрение",
            # social feelings on top of Ekman's basic set
            "shyness": "смущение", "jealousy": "ревность", "longing": "скучание"}

EMO_TAU = {"joy": 25, "sadness": 40, "fear": 8, "anger": 12, "surprise": 1.5, "disgust": 6, "contempt": 12,
           "shyness": 4, "jealousy": 15, "longing": 100000}  # longing is driven by absence, not by a clock

EMO_OPPOSE = {"joy": ("sadness", "anger", "fear", "longing"), "sadness": ("joy",), "anger": ("joy",), "fear": ("joy",),
              "disgust": ("joy",), "contempt": (), "surprise": (), "shyness": (), "jealousy": ("joy",), "longing": ()}

MOOD_COMPAT = {"happy": ("joy", 0.6), "love": ("joy", 0.8), "sad": ("sadness", 0.6), "angry": ("anger", 0.6),
               "surprised": ("surprise", 0.7), "neutral": ("neutral", 0.5), "sleepy": ("neutral", 0.5)}

EMO_LIST = "joy|sadness|fear|anger|surprise|disgust|contempt|shyness|jealousy|longing|neutral"


def feel(name, intensity):
    """Add an emotion (Ekman) to the current blend."""
    try:
        x = max(0.0, min(1.0, float(intensity)))
    except (TypeError, ValueError):
        x = 0.5
    with state_lock:
        E = S["emo"]
        if name == "neutral":
            for k in E:
                E[k] = round(E[k] * (1 - 0.6 * x), 3)
        elif name in E:
            E[name] = round(min(1.0, max(E[name], E[name] * 0.4 + x * 0.8)), 3)
            for k in EMO_OPPOSE[name]:
                E[k] = round(E[k] * (1 - 0.7 * x), 3)
        S["mood"] = dominant()[0]


def guest_here():
    """The guest just did something: longing turns into joy."""
    with state_lock:
        L = S["emo"].get("longing", 0)
        if L > 0.1:
            feel("joy", min(1.0, S["emo"]["joy"] + L * 0.6))
            S["emo"]["longing"] = round(L * 0.15, 3)
        S["last_guest_ts"] = time.time()


def appraise(name, x):
    """Immediate reaction to what happens in the world, coloured by character."""
    P, Sn = trait("positivity"), trait("sensitivity")
    k = 0.7 + 0.6 * Sn
    if name == "joy":
        k *= 0.75 + 0.5 * P
    elif name in ("sadness", "anger", "fear", "disgust", "contempt"):
        k *= 1.25 - 0.5 * P
    feel(name, min(1.0, x * k))


def dominant():
    E = S["emo"]
    k = max(E, key=E.get)
    return (k, E[k]) if E[k] >= 0.15 else ("neutral", 0.0)


def parse_emotion(r):
    name = str(r.get("emotion") or "").strip().lower()
    if name in EMOTIONS or name == "neutral":
        return name, r.get("intensity", 0.5)
    if r.get("mood") in MOOD_COMPAT:
        return MOOD_COMPAT[r["mood"]]
    return None


def emo_line():
    E = S["emo"]
    felt = sorted(((v, k) for k, v in E.items() if v >= 0.1), reverse=True)
    if not felt:
        return "Эмоции: спокойствие, ничего особенного не чувствуешь."
    return "Эмоции и чувства сейчас (0–1): " + ", ".join(f"{EMOTIONS[k]} {v:.1f}" for v, k in felt) + "."
