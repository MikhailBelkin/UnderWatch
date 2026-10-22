"""The guest's hand in the world: lights and devices, tenderness, invitations, the resident's name."""
import re
import time

from ..context import S, emit_event, g, hub, save_state, spawn, state_lock
from ..settings import trait
from ..clock import is_awake_time
from ..world import LAMP_RU, LOOP_LABEL, PLACES, TOGETHER
from . import bonds, drawings, emotions, needs, state


POKES = ("bed", "night", "liv", "floor", "kit", "bath", "tv", "console", "music", "flood", "pat", "kiss", "hand", "hug", "flowers")

# tender touches: (what she perceives, what the guest did, joy, surprise)
TOUCHES = {
    "pat": ("Кто-то невидимый нежно погладил тебя по голове.", "погладили по голове", 0.5, 0.25),
    "kiss": ("Ты почувствовал{a} лёгкий поцелуй в щёку — кажется, это гость.", "чмокнули в щёчку", 0.6, 0.35),
    "hand": ("Кто-то тёплый взял тебя за руку и немного подержал.", "взяли за руку", 0.45, 0.2),
    "hug": ("Тебя вдруг тепло и крепко обняли — никого не видно, но объятие настоящее.", "обняли", 0.65, 0.3),
    "flowers": ("На подоконнике в спальне вдруг появился букет свежих цветов!", "подарили цветы", 0.6, 0.6),
}


def poke_custom(kind, text):
    """Something the player made up: a world event, a touch or an invitation the menus don't have."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()[:200]
    if len(text) < 2:
        return None
    emotions.guest_here()
    if kind == "world":
        perceived = f"В квартире случилось: {text}"
        guest = "своё вмешательство: " + text
        emotions.appraise("surprise", 0.45)
    else:
        perceived = (f"Гость делает тебе: {text}. Отреагируй по-своему — по тому, как ты к нему сейчас относишься; " )
        guest = "нежность: " + text
        emotions.appraise("surprise", 0.25)
        bonds.grow_closeness(0.8, "touch")
    with state_lock:
        if is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [perceived]
            S["react_at"] = time.time() + 2
        save_state()
        st = state.public_state()
    emit_event("world", perceived, {"by": "guest", "what": "custom_" + kind, "guest": guest})
    hub.publish({"type": "world", "what": "custom_" + kind, "text": perceived, "guest": guest, "state": st})
    if kind == "world":
        spawn(drawings.visualize_world, text)
    return st


def poke(what):
    """The guest changes the world. The resident perceives it as something that just happened."""
    emotions.guest_here()
    with state_lock:
        was = S["loop"]
        on = False
        if what in TOUCHES:
            text, guest, joy, surprise = TOUCHES[what]
            text = text.replace("{a}", g("", "а"))
            if S["loop"] == "sleep" or not is_awake_time():
                text = "Сквозь сон: " + text[0].lower() + text[1:]
            now_ts = time.time()
            recent = [t for t in S.get("touch_log", []) if now_ts - t < 600]
            S["touch_log"] = recent + [now_ts]
            f = (0.65 ** len(recent)) * (1 - 0.5 * S["emo"]["anger"])  # habituation; resentment dulls tenderness
            emotions.appraise("joy", joy * f * (0.5 + trait("romance")) * (0.7 + 0.6 * trait("friendliness")))
            bonds.grow_closeness(1.0 * f, "touch")
            shy = {"kiss": 0.5, "hug": 0.4, "hand": 0.35, "pat": 0.25, "flowers": 0.3}[what]
            emotions.appraise("shyness", shy * (1.1 - 0.6 * trait("extraversion")) * (0.7 ** len(recent)))
            emotions.appraise("surprise", surprise * (0.7 ** len(recent)))
            S["needs"]["social"] = needs.clampn(S["needs"]["social"] + 8 * f)
            if what == "flowers":
                S["flowers_ts"] = now_ts
            on = True
        elif what in LAMP_RU:
            on = S["lights"][what] = not S["lights"][what]
            text = ("Сам собой включился " if on else "Внезапно погас ") + LAMP_RU[what] if what in ("floor", "night") else \
                   ("Сам собой зажёгся " if on else "Внезапно погас ") + LAMP_RU[what]
            guest = ("включили " if on else "выключили ") + LAMP_RU[what]
        elif what == "tv":
            S["tv"] = "off" if S["tv"] != "off" else ("game" if S["console"] else "show")
            on = S["tv"] != "off"
            text, guest = ("Телевизор сам включился." if on else "Телевизор вдруг погас."), ("включили" if on else "выключили") + " телевизор"
            if not on and S["loop"] in ("watch", "game"):
                S["loop"], S["label"] = "sit", LOOP_LABEL["sit"]
        elif what == "console":
            S["console"] = not S["console"]
            on = S["console"]
            if S["tv"] != "off":
                S["tv"] = "game" if on else "show"
            text = ("Приставка сама включилась" + (" — на экране игра." if S["tv"] != "off" else ".")) if on else "Приставка выключилась сама собой."
            guest = ("включили" if on else "выключили") + " приставку"
            if not on and S["loop"] == "game":
                S["loop"], S["label"] = "sit", LOOP_LABEL["sit"]
        elif what == "music":
            S["music"] = not S["music"]
            on = S["music"]
            text, guest = ("Проигрыватель сам заиграл." if on else "Музыка внезапно оборвалась."), ("включили" if on else "выключили") + " музыку"
            if not on and S["loop"] == "listen":
                S["loop"], S["label"] = None, "стоит: " + PLACES[S["location"]]
        elif what == "flood":
            if S["leak"]:
                return None
            S["leak"] = True
            text, guest = "Под мойкой с грохотом прорвало трубу — по полу разливается вода!", "прорвали трубу под мойкой"
        else:
            return None
        if what in TOUCHES:
            pass
        elif what == "flood":
            emotions.appraise("surprise", 0.9); emotions.appraise("fear", 0.5)
        elif what in LAMP_RU:
            emotions.appraise("surprise", 0.35 if on else 0.5)
            if not on: emotions.appraise("fear", 0.15)
        else:
            emotions.appraise("surprise", 0.4)
            if not on and ((what == "music" and was in ("listen",)) or (what in ("tv", "console") and was in ("watch", "game", "sit"))):
                emotions.appraise("anger", 0.35)
        awake = is_awake_time()
        if awake:
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = state.public_state()
    emit_event("world", text, {"by": "guest", "what": what, "guest": guest})
    hub.publish({"type": "world", "what": what, "text": text, "guest": guest, "state": st})
    return st


def invite(kind, custom=None):
    emotions.guest_here()
    with state_lock:
        if kind == "end":
            was = S.get("together")
            S["together"], S["invite"] = None, None
            text = "Гость говорит, что ему пора — ваше совместное время закончилось." if was else None
            if not was:
                return state.public_state()
            guest = "закончили совместное время"
        elif kind == "custom":
            label = re.sub(r"\s+", " ", str(custom or "")).strip()[:100]
            if len(label) < 2:
                return state.public_state()
            S["invite"] = {"kind": "custom", "ts": time.time(), "text": label}
            text = f"Гость предлагает заняться вместе: {label}. Если хочешь — соглашайся действием together{{custom}} (можно добавить и другие действия, чтобы это изобразить); если нет — откажи словами."
            guest = "предложили: " + label
        else:
            S["invite"] = {"kind": kind, "ts": time.time()}
            text = f"Гость приглашает тебя: {TOGETHER[kind]}. Если хочешь — соглашайся действием together{{{kind}}}; если нет — откажи словами, можно мягко."
            guest = "пригласили: " + TOGETHER[kind]
        if is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
            S["react_at"] = time.time() + 2
        save_state()
        st = state.public_state()
    emit_event("world", text, {"by": "guest", "what": "invite", "guest": guest})
    hub.publish({"type": "world", "what": "invite", "text": text, "guest": guest, "state": st})
    return st


def set_identity(male, name):
    with state_lock:
        old = S["name"]
        if male is not None:
            if not S["name"] or S["name"] == ("Лёва" if S["male"] else "Лена"):
                S["name"] = "Лёва" if male else "Лена"
            S["male"] = bool(male)
        if name:
            S["name"] = name
        save_state()
    emit_event("system", f"Жилец теперь: {S['name']} ({'он' if S['male'] else 'она'})" + ("" if old == S["name"] else f", раньше — {old}"))
    hub.publish({"type": "state", "state": state.public_state()})
