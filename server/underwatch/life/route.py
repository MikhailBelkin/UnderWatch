"""The route to Proxima: how far the ship has come, what passes by the portholes (a comet, meteors, a nebula,
a galaxy, a rogue planet, a star, a black hole), the hull hit by meteors, going outside to patch it (EVA),
and the radio noise that reaches the chat with the guest."""
import random
import re
import time

from ..context import R, S, emit_event, g, hub, save_state, spawn, state_lock
from ..clock import is_awake_time
from . import emotions, state

SPEED_C = 0.12          # the ship's speed, a share of the speed of light (the bridge screen says so too)
DIST_LY = 4.24          # light years from the Sun to Proxima Centauri
HEAD_START_DAYS = 210   # the flight began before the guest caught her frequency
EVA_O2_MIN = 45         # minutes of oxygen in the suit
EVA_PATCH_MIN = 5       # minutes outside it takes to patch the hull
DODGE = 0.75            # the chance to steer away from the rock when she is at the helm
DUTY_HOURS = 4          # a watch on the bridge at least this often while she is awake

# what can pass by: name, minutes it stays in view, what she sees, what the guest is told, feelings, radio noise (0–1)
SKY = {
    "comet": dict(pilot="Можно сесть за штурвал (pilot) и подвести корабль поближе к комете — для снимков и чтобы гость увидел.", ru="комета", mins=(6, 10), noise=0.0, feel=(("surprise", 0.55), ("joy", 0.4)),
                  see="Мимо корабля проходит комета: яркое ядро и хвост на полнеба, его видно во все иллюминаторы. Говорят, на комету можно загадать желание.",
                  now="мимо проходит комета, хвост на полнеба"),
    "meteors": dict(pilot="Срочно за штурвал (pilot): вручную можно увести корабль от крупных камней.", ru="метеорный поток", mins=(3, 5), noise=0.3, feel=(("fear", 0.5), ("surprise", 0.7)),
                    see="Корабль влетел в метеорный поток! Мимо иллюминаторов несутся камни, по обшивке что-то стучит. Выходить наружу сейчас опасно.",
                    now="метеорный поток — камни бьют по обшивке, выходить наружу опасно"),
    "nebula": dict(pilot="В туманности автопилот путается в пыли — пилоту стоит посидеть за штурвалом (pilot) и проследить за курсом.", ru="туманность", mins=(20, 35), noise=0.1, feel=(("joy", 0.35), ("surprise", 0.3)),
                   see="Корабль идёт краем туманности: за иллюминаторами розовые, голубые и сиреневые облака, сквозь них просвечивают молодые звёзды.",
                   now="корабль идёт краем туманности, за иллюминаторами цветные облака"),
    "galaxy": dict(pilot="", ru="галактика", mins=(15, 25), noise=0.0, feel=(("joy", 0.3), ("surprise", 0.3)),
                   see="В иллюминаторе необычно ясно видна далёкая спиральная галактика — два рукава из звёзд вокруг яркого ядра.",
                   now="в иллюминаторе ясно видна далёкая спиральная галактика"),
    "planet": dict(pilot="Можно взять управление (pilot) и пройти поближе к планете, чтобы снять её для Земли.", ru="блуждающая планета", mins=(10, 18), noise=0.0, feel=(("surprise", 0.6), ("joy", 0.35)),
                   see="Корабль проходит мимо блуждающей планеты{ring} — без своей звезды, одна в темноте. Она закрывает пол-иллюминатора; можно сделать снимки для Земли.",
                   now="мимо проходит блуждающая планета{ring}"),
    "star": dict(pilot="Пилоту лучше сесть за штурвал (pilot) и отвести корабль подальше от жара.", ru="звезда", mins=(8, 14), noise=0.3, feel=(("surprise", 0.5), ("fear", 0.15)), heat=True,
                 see="Корабль проходит недалеко от звезды: свет бьёт в иллюминаторы, обшивка нагревается, на борту становится жарко (+29 °C), связь шумит от звёздного ветра.",
                 now="корабль проходит рядом со звездой: свет бьёт в иллюминаторы, на борту жарко (+29 °C)"),
    "blackhole": dict(pilot="Гравитация тянет корабль с курса — пилот должен быть в кресле (pilot) и держать курс вручную.", ru="чёрная дыра", mins=(8, 14), noise=0.45, feel=(("fear", 0.4), ("surprise", 0.65)),
                      see="Вдалеке чёрная дыра: свет звёзд вокруг неё изгибается кольцом, вокруг светится оранжевый диск. Приборы шалят, часы в рубке сбиваются, связь с гостем идёт с помехами.",
                      now="вдалеке чёрная дыра — свет вокруг неё изгибается, часы в рубке сбиваются"),
}
WEIGHTS = {"comet": 2, "meteors": 1.5, "nebula": 2, "galaxy": 1.3, "planet": 2, "star": 1, "blackhole": 0.7}

# where a meteor can hit: words for her, and the spot along the hull on the outside view (0 — stern, 1 — nose)
HULL_SPOTS = [("над каютой", 0.36), ("над кают-компанией", 0.6), ("возле рубки", 0.84), ("у кормы", 0.12)]


def voyage():
    """Day of the flight, light years flown and left."""
    start = S.get("voyage_start") or time.time() - HEAD_START_DAYS * 86400
    days = (time.time() - start) / 86400
    flown = days / 365.25 * SPEED_C
    return int(days) + 1, flown, max(0.0, DIST_LY - flown)


def sky_now():
    sk = S.get("sky")
    return sk if sk and sk["end"] > time.time() else None


def noise():
    sk = sky_now()
    return SKY[sk["kind"]]["noise"] if sk else 0.0


def _text(kind, field, sk):
    return SKY[kind][field].replace("{ring}", " с широкими кольцами" if sk.get("ring") else "")


def _asleep():
    return S["loop"] == "sleep" or not is_awake_time()


def _react(text, delay=3):
    """She notices: the next decision starts from this (only when she is awake)."""
    if not _asleep():
        S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
        S["react_at"] = max(time.time() + delay, (S.get("last_react") or 0) + 15)


def start_event(kind, by_guest=False):
    """Something comes into view; it replaces whatever was passing by."""
    if kind not in SKY:
        return None
    lo, hi = SKY[kind]["mins"]
    t = time.time()
    sk = {"kind": kind, "start": t, "end": t + random.uniform(lo, hi) * 60, "seed": random.randrange(1, 10 ** 6), "by": "guest" if by_guest else "route"}
    if kind == "planet":
        sk.update(ring=random.random() < 0.6, pal=random.randrange(3))
    if kind == "meteors" and random.random() < 0.6:
        sk["hit_at"] = t + (sk["end"] - t) * random.uniform(0.3, 0.65)
    see = _text(kind, "see", sk)
    with state_lock:
        S["sky"] = sk
        S["sky_last"] = kind
        for emo, k in SKY[kind]["feel"]:
            emotions.appraise(emo, k * (0.5 if _asleep() else 1))
        _react((see + " " + SKY[kind]["pilot"]).strip())
        save_state()
        st = state.public_state()
    emit_event("world", see, {"what": "sky", "kind": kind, "by": sk["by"]})
    hub.publish({"type": "sky", "sky": sk, "text": f"За бортом: {SKY[kind]['ru']}.", "by": sk["by"], "state": st})
    return st


def _end_event():
    kind = (S.get("sky") or {}).get("kind")
    if kind in SKY:
        emit_event("world", f"{SKY[kind]['ru'].capitalize()} позади: за иллюминаторами снова только звёзды." + (" Можно снова выходить наружу." if kind == "meteors" else ""),
                   {"what": "sky_end", "kind": kind})
    with state_lock:
        S["sky"] = None
        S["sky_next"] = time.time() + random.uniform(40, 100) * 60
        save_state()
        st = state.public_state()
    hub.publish({"type": "sky", "sky": None, "state": st})


def _hit():
    """A meteor hits the hull: an alarm on the bridge, a dent to patch from the outside. At the helm she can dodge it."""
    where, x = random.choice(HULL_SPOTS)
    if S["loop"] == "pilot" and random.random() < DODGE:
        with state_lock:
            S["sky"] = dict(S["sky"], hit_done=True, dodged=True)
            emotions.appraise("joy", 0.5)
            emotions.appraise("surprise", 0.5)
            text = f"Крупный камень летел прямо в корабль, но ты вовремя заметил{g('', 'а')} его и увел{g('', 'а')} «Странник» в сторону — обшивка цела."
            _react(text, delay=1)
            save_state()
            st = state.public_state()
        emit_event("world", text, {"what": "dodge"})
        hub.publish({"type": "sky", "sky": S["sky"], "dodge": True, "text": "Камень летел прямо в «Странник» — пилот увела корабль в сторону.", "state": st})
        return
    with state_lock:
        S["sky"] = dict(S["sky"], hit_done=True)
        if S.get("hull"):
            save_state()
            return
        S["hull"] = {"where": where, "x": x, "ts": time.time()}
        emotions.appraise("fear", 0.6)
        emotions.appraise("surprise", 0.8)
        text = (f"Удар! Метеорит попал в корабль: в рубке завыла тревога, обшивка повреждена {where}. "
                f"Давление держится, но дыру надо залатать — выйти наружу в скафандре (eva), когда кончится метеорный поток.")
        _react(text, delay=1)
        save_state()
        st = state.public_state()
    emit_event("world", text, {"what": "hull_hit", "where": where})
    hub.publish({"type": "sky", "sky": S["sky"], "hit": True, "text": f"Метеорит попал в «Странник»: обшивка повреждена {where}.", "state": st})


def tick():
    """Every few seconds while the resident lives: the voyage clock, what passes by, the meteors' hit, the suit's oxygen."""
    t = time.time()
    if not S.get("voyage_start"):
        with state_lock:
            S["voyage_start"] = t - HEAD_START_DAYS * 86400
    if not S.get("duty_ts"):
        with state_lock:
            S["duty_ts"] = t - (DUTY_HOURS - 1) * 3600
    sk = S.get("sky")
    if sk and sk.get("hit_at") and not sk.get("hit_done") and t >= sk["hit_at"]:
        _hit()
    if sk and t >= sk["end"]:
        _end_event()
        sk = None
    if not sk:
        nxt = S.get("sky_next") or 0
        if not nxt:
            nxt = t + random.uniform(5, 20) * 60
        elif hub.clients and nxt - t > 25 * 60:  # the guest is watching: something comes by soon, so they see it
            nxt = t + random.uniform(8, 20) * 60
        if nxt != S.get("sky_next"):
            with state_lock:
                S["sky_next"] = nxt
        if t >= nxt:
            last = S.get("sky_last")
            kinds = [k for k in SKY if k != last]
            start_event(random.choices(kinds, [WEIGHTS[k] for k in kinds])[0])
    if S["loop"] == "eva" and t - (S.get("eva_since") or t) > (EVA_O2_MIN + 3) * 60:
        from .body import act  # the suit is nearly empty: back inside, whatever she was about to do
        act([{"do": "walk_to", "place": "airlock"}], minutes=2, thought="Кислород на исходе — пора внутрь.", intent="возвращается в шлюз")


# ---- going outside

def eva_allowed(a):
    sk = sky_now()
    if sk and sk["kind"] == "meteors":
        return f"Хотел{g('', 'а')} выйти наружу, но идёт метеорный поток — снаружи сейчас опасно, лучше переждать."


def eva(a, body):
    if S["loop"] != "eva" or not S.get("eva_since"):  # going out, not already outside: a full suit of oxygen
        S["eva_since"] = time.time()
    S["duty_ts"] = time.time()


def duty(a, body):
    """A watch at the helm or a round of the systems: the ship is looked after."""
    S["duty_ts"] = time.time()


def suit_fix(actions, *texts):
    """She means to put the spacesuit on but picks clothes from the locker (or an outfit that isn't there):
    the suit only comes with going outside, so the chain becomes eva from that point."""
    if not isinstance(actions, list):
        return actions
    said = any("скафанд" in str(x or "").lower() for x in texts) or any(
        isinstance(a, dict) and "скафанд" in str(a.get("label") or "").lower() for a in actions)
    dos = [a.get("do") if isinstance(a, dict) else None for a in actions]
    if "eva" in dos:
        return actions

    def suit(a):
        if not isinstance(a, dict):
            return False
        if a.get("do") == "change_clothes":
            o = str(a.get("outfit") or "").lower()
            return said or "suit" in o or "скафанд" in o
        return a.get("do") == "move" and "скафанд" in str(a.get("label") or "").lower()
    hit = next((i for i, a in enumerate(actions) if suit(a)), None)
    if hit is None:
        return actions
    if hit and isinstance(actions[hit - 1], dict) and actions[hit - 1].get("do") == "walk_to" and actions[hit - 1].get("place") in ("lock", "airlock"):
        hit -= 1
    return actions[:hit] + [{"do": "eva"}]


def after_chain(actions, body):
    """Back inside from the open space: if she was out long enough, the hole in the hull is patched."""
    if S["loop"] != "eva" or body.loop == "eva":
        return
    mins = (time.time() - (S.get("eva_since") or time.time())) / 60
    hull = S.get("hull")
    if hull and mins >= EVA_PATCH_MIN:
        S["patches"] = (S.get("patches") or [])[-5:] + [hull["x"]]
        S["hull"] = None
        emotions.appraise("joy", 0.45)
        spawn(emit_event, "world", f"Обшивка {hull['where']} залатана: тревога в рубке смолкла.", {"what": "hull_fixed"})
    elif hull:
        spawn(emit_event, "system", f"Вернул{g('ся', 'ась')} в шлюз, но залатать обшивку не успел{g('', 'а')} — на это нужно хотя бы {EVA_PATCH_MIN} минут снаружи.")


# ---- the radio link

STATIC = ("кх-х…", "ш-ш-ш…", "…тр-р…", "пш-ш…")


def garble(text):
    """What she hears of the guest's words through the noise; the same text when the link is clear."""
    n = noise()
    if not n:
        return text
    words = text.split()
    out = [random.choice(STATIC) if len(w) > 2 and random.random() < n else w for w in words]
    heard = re.sub(r"(?:(?:кх-х…|ш-ш-ш…|…тр-р…|пш-ш…)\s*){2,}", "ш-ш-ш… ", " ".join(out)).strip()
    return heard


# ---- for the prompts

def line():
    day, flown, left = voyage()
    out = [f"Полёт: день {day}, до Проксимы {left:.2f} св. года.".replace(f"{left:.2f}", f"{left:.2f}".replace(".", ","))]
    sk = sky_now()
    if sk:
        m = max(1, int((sk["end"] - time.time()) / 60))
        out.append(f"За иллюминаторами сейчас: {_text(sk['kind'], 'now', sk)} (будет видно ещё минут {m}).")
        if SKY[sk["kind"]]["noise"] >= 0.2:
            out.append("Связь с гостем сейчас с помехами: его слова доходят урывками.")
    hull = S.get("hull")
    if hull:
        out.append(f"ВНИМАНИЕ: обшивка повреждена {hull['where']} — в рубке мигает тревога. Залатать можно только снаружи: выйти в открытый космос (eva) хотя бы на {EVA_PATCH_MIN} минут.")
    if not _asleep() and S["loop"] not in ("pilot", "eva") and time.time() - (S.get("duty_ts") or time.time()) > DUTY_HOURS * 3600:
        h = int((time.time() - S["duty_ts"]) / 3600)
        out.append(f"Ты уже {h} ч не заступал{g('', 'а')} на вахту: пора в рубку — сверить курс и сделать коррекцию за штурвалом (pilot) или проверить системы (check_systems).")
    if S["loop"] == "pilot":
        out.append("Ты на вахте за штурвалом: ведёшь корабль, следишь за курсом и приборами.")
    if S["loop"] == "eva":
        left_o2 = max(0, int(EVA_O2_MIN - (time.time() - (S.get("eva_since") or time.time())) / 60))
        out.append(f"Ты сейчас снаружи, в открытом космосе: в скафандре, на страховочном тросе у обшивки. Кислорода ещё минут на {left_o2}. "
                   "С гостем говоришь по радио скафандра. Ты уже снаружи — eva повторять не нужно; просто разговаривай, а если хочешь что-то сделать — actions пустой, ты остаёшься на тросе. Чтобы вернуться — любое действие внутри корабля (ты сначала пройдёшь через шлюз).")
    return " ".join(out)
