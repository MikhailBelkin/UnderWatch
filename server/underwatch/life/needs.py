"""Needs: hunger, energy, fun, social, hygiene, bladder; how they drift and what fills them."""
import math
import time

from ..context import S, SETTINGS, state_lock
from ..settings import trait
from ..clock import is_awake_time
from ..world import LOOP_LABEL, MOP_RATE, WATER_MAX, WATER_RISE
from . import emotions


INSTANT = {  # need changes applied when the action happens
    "eat": {"hunger": 55, "fun": 4, "bladder": -12}, "drink": {"hunger": 6, "energy": 4, "bladder": -30}, "dance": {"fun": 10, "energy": -3, "hygiene": -5},
    "workout": {"energy": -4}, "change_clothes": {"fun": 3}, "laugh": {"fun": 3},
    "use_toilet": {"bladder": 100}, "brush_teeth": {"hygiene": 15}, "wash_face": {"hygiene": 6, "energy": 3}, "comb_hair": {"fun": 2},
    "cook": {"hygiene": -4}, "tidy_up": {"hygiene": -6}, "open_fridge": {},
}

PER_MIN = {  # need drift per awake minute, by loop
    None: {}, "sit": {"energy": 0.08}, "watch": {"fun": 0.7}, "game": {"fun": 0.8, "energy": -0.05},
    "listen": {"fun": 0.6}, "read": {"fun": 0.5}, "write": {"fun": 0.35}, "daydream": {"fun": 0.25, "energy": 0.05},
    "phone": {"social": 1.0, "fun": 0.25}, "workout": {"fun": 0.3, "energy": -0.15, "hygiene": -0.4}, "mop": {"fun": -0.3, "energy": -0.12, "hygiene": -0.3},
    "shower": {"hygiene": 9, "fun": 0.3, "energy": 0.2},
    "date": {"social": 1.2, "fun": 0.5}, "cozy": {"fun": 0.35, "energy": 0.12}, "dancing": {"social": 1.0, "fun": 1.0, "energy": -0.1, "hygiene": -0.1},
}

BASE_DRIFT = {"hunger": -0.30, "energy": -0.11, "fun": -0.22, "social": -0.10, "hygiene": -0.06, "bladder": -0.15}

NEED_RU = {"hunger": "сытость", "energy": "бодрость", "fun": "развлечённость (не про настроение, а про скуку)", "social": "общение",
           "hygiene": "свежесть", "bladder": "туалет (100 — не хочется)"}

NEED_WORDS = {  # (threshold, masculine, feminine), checked from the top
    "hunger": [(70, "сыт", "сыта"), (40, "не голоден", "не голодна"), (20, "проголодался", "проголодалась"), (0, "очень голоден", "очень голодна")],
    "energy": [(70, "полон сил", "полна сил"), (40, "в порядке", "в порядке"), (20, "устал", "устала"), (0, "валится с ног", "валится с ног")],
    "fun": [(70, "не скучно", "не скучно"), (40, "нормально", "нормально"), (20, "скучновато", "скучновато"), (0, "скучно до тоски", "скучно до тоски")],
    "social": [(70, "наобщался", "наобщалась"), (40, "нормально", "нормально"), (20, "хочется поболтать", "хочется поболтать"), (0, "одиноко", "одиноко")],
    "hygiene": [(70, "свежий", "свежая"), (40, "нормально", "нормально"), (20, "хочется умыться", "хочется умыться"), (0, "срочно в душ", "срочно в душ")],
    "bladder": [(70, "не хочет", "не хочет"), (40, "терпимо", "терпимо"), (20, "хочет в туалет", "хочет в туалет"), (0, "очень хочет в туалет", "очень хочет в туалет")],
}


def need_word(k, v):
    for th, m, f in NEED_WORDS[k]:
        if v >= th:
            return m if S["male"] else f
    return ""


def base_drift():
    """Drift per awake minute, shaped by the body settings and the character."""
    d = dict(BASE_DRIFT)
    d["hunger"] = BASE_DRIFT["hunger"] * SETTINGS.get("hunger_rate", 1.0)
    d["social"] = -(0.04 + 0.16 * trait("extraversion")) - 0.12 * S["emo"].get("longing", 0)  # extraverts need people more; missing him empties it faster
    d["energy"] = BASE_DRIFT["energy"] * (1.25 - 0.5 * trait("activity"))  # active people tire slower
    return d


def rest_rates(rates):
    r = S.get("rest") or {}
    if S["loop"] == "rest":
        rates["energy"] = rates.get("energy", 0) + (0.18 if r.get("how") in ("lie", "belly") else 0.08 if r.get("how") == "sit" else 0)
    return rates


def enjoyment():
    """How much pleasure things give right now: sadness, longing, anger and fear take the joy out of them."""
    E = S["emo"]
    dull = 0.9 * E["sadness"] + 0.6 * E["longing"] + 0.4 * E["anger"] + 0.4 * E["fear"] + 0.3 * E["jealousy"]
    return max(0.15, 1 - dull) * (1 + 0.3 * E["joy"])


def fun_gain(x):
    """A positive bump of fun, damped by mood and by how full it already is (the last points come hard)."""
    if x <= 0:
        return x
    return x * enjoyment() * min(1.0, (100 - S["needs"]["fun"]) / 50)


def live_rates():
    """Per-minute change of each need while awake."""
    rates = base_drift()
    for k, v in PER_MIN.get(S["loop"], {}).items():
        rates[k] = rates.get(k, 0) + (fun_gain(v) if k == "fun" else v)
    rates["fun"] -= 0.3 * S["emo"]["sadness"]  # gloom makes everything dull
    return rest_rates(rates)


def need_rates():
    """Per-minute change of each need right now, and why."""
    loop = S["loop"]
    if loop == "sleep":
        return {k: (0.35 if k == "energy" else 0.0) for k in BASE_DRIFT}, "спит"
    return {k: round(v, 2) for k, v in live_rates().items()}, LOOP_LABEL.get(loop, "ничем особым не занят" if S["male"] else "ничем особым не занята")


def needs_view():
    rates, why = need_rates()
    return {"words": {k: need_word(k, v) for k, v in S["needs"].items()}, "rates": rates, "why": why}


def clampn(v):
    return max(0.0, min(100.0, float(v)))  # no rounding here: ticks are 5 s and per-tick changes are tiny


def update_needs():
    t = time.time()
    with state_lock:
        dt_min = min(30, max(0, (t - (S["last_tick"] or t)) / 60))
        S["last_tick"] = t
        for k in S["emo"]:
            tau = emotions.EMO_TAU[k] * (0.5 if S["loop"] == "sleep" else 1)
            S["emo"][k] = S["emo"][k] * math.exp(-dt_min / tau)
        if is_awake_time() and S["loop"] != "sleep":
            away = (t - (S.get("last_guest_ts") or t)) / 60
            target = max(0.0, min(1.0, (away - 20) / 180)) * (0.35 + 0.65 * (trait("romance") + trait("extraversion")) / 2)
            if S.get("together"):
                target = 0.0
            L = S["emo"]["longing"]
            S["emo"]["longing"] = min(target, L + 0.012 * dt_min) if L < target else max(target, L - 0.02 * dt_min)
            L = S["emo"]["longing"]
            if L > 0.35:  # neglect sours the mood: sadness and (for romantics) jealousy drift up towards a level set by longing
                E = S["emo"]
                sad_target = min(0.75, (L - 0.35) * 0.9 * (0.7 + 0.6 * trait("sensitivity")))
                if E["sadness"] < sad_target:
                    E["sadness"] = min(sad_target, E["sadness"] + 0.012 * dt_min)
                E["joy"] = max(0.0, E["joy"] - 0.012 * dt_min * (L - 0.35))
                if away > 180 and trait("romance") > 0.45:
                    jel_target = min(0.6, (L - 0.5) * (0.4 + trait("romance")))
                    if E["jealousy"] < jel_target:
                        E["jealousy"] = min(jel_target, E["jealousy"] + 0.008 * dt_min)
        S["mood"] = emotions.dominant()[0]
        if S["leak"]:
            S["water"] = min(WATER_MAX, S["water"] + WATER_RISE * dt_min)
        elif S["loop"] == "mop" and S["water"] > 0:
            S["water"] = max(0.0, S["water"] - MOP_RATE * dt_min)
            if S["water"] == 0:
                S["until"] = time.time()  # floor is dry: time to decide what's next
        n = S["needs"]
        if S["loop"] == "sleep":
            n["energy"] = clampn(n["energy"] + 0.35 * dt_min)
            return
        for k, v in live_rates().items():
            n[k] = clampn(n[k] + v * dt_min)


def instant(do):
    """What an action does to the needs right away (eating fills hunger, the toilet empties the bladder…)."""
    for k, v in INSTANT.get(do, {}).items():
        S["needs"][k] = clampn(S["needs"][k] + (fun_gain(v) if k == "fun" else v))
