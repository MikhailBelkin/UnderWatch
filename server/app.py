#!/usr/bin/env python3
"""За стеклом — the resident's mind.

Runs around the clock, but the resident is awake (and the model is called)
only from WAKE_H to SLEEP_H, Europe/Ljubljana. Outside that window he sleeps
and no tokens are spent.

  * every decision about what to do next comes from the model (Haiku via Claude Code);
  * the morning plan and the evening reflection/diary come from a deeper model (Sonnet);
  * the evening reflection is also the memory compaction: notes about himself and
    about the guest are rewritten from the day's events.

Stdlib only. Serves the page and a small JSON/SSE API on HOST:PORT.
"""
import glob
import hashlib
import urllib.parse
import json
import math
import os
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "mind.sqlite"

TZ = ZoneInfo(os.environ.get("RESIDENT_TZ", "Europe/Ljubljana"))
WAKE_H = int(os.environ.get("WAKE_HOUR", "8"))
SLEEP_H = int(os.environ.get("SLEEP_HOUR", "16"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
MODEL_FAST = os.environ.get("MODEL_FAST", "haiku")
MODEL_DEEP = os.environ.get("MODEL_DEEP", "sonnet")
TICK = 5  # seconds between mind-loop checks
PASSWORD = os.environ.get("PASSWORD", "")  # empty = no login
AUTH_TOKEN = hashlib.sha256(("za-steklom:" + PASSWORD).encode()).hexdigest() if PASSWORD else ""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- vocabulary
PLACES = {
    "bed": "кровать", "window": "окно", "wardrobe": "шкаф", "sofa": "диван", "tv": "телевизор",
    "music": "проигрыватель", "fridge": "холодильник", "stove": "плита", "center": "середина комнаты",
    "toilet": "унитаз", "sink": "раковина", "shower": "душ",
}
COLORS = {"red": "красное", "blue": "синее", "green": "зелёное", "yellow": "жёлтое", "purple": "фиолетовое",
          "orange": "оранжевое", "pink": "розовое", "black": "чёрное", "white": "белое"}
# do -> (place it happens at, loop it leaves the body in, label)
ACTIONS = {
    "walk_to": (None, None, "идёт"), "wave": (None, "", "машет"), "nod": (None, "", "кивает"),
    "shake_head": (None, "", "мотает головой"), "shrug": (None, "", "пожимает плечами"), "jump": (None, None, "прыгает"),
    "dance": (None, None, "танцует"), "think": (None, "", "думает"), "laugh": (None, "", "смеётся"),
    "bow": (None, "", "кланяется"), "stretch": (None, None, "потягивается"), "sit": ("sofa", "sit", "сидит на диване"),
    "stand": (None, None, "встаёт"), "watch_tv": ("sofa", "watch", "смотрит телевизор"),
    "open_gift": ("center", None, "открывает подарок"), "eat_treat": ("sofa", "sit", "ест вкусняшку"),
    "use_item": (None, "", "радуется подарку"),
    "tv_off": (None, "", "выключает телевизор"), "play_game": ("sofa", "game", "играет в приставку"),
    "music_on": ("music", "listen", "слушает пластинку"), "music_off": ("music", None, "выключает музыку"),
    "cook": ("stove", None, "готовит"), "eat": (None, "", "ест"), "drink": ("fridge", None, "пьёт"),
    "open_fridge": ("fridge", None, "заглядывает в холодильник"), "sleep": ("bed", "sleep", "спит"),
    "change_clothes": ("wardrobe", None, "переодевается"), "light_on": (None, "", "включает свет"),
    "light_off": (None, "", "выключает свет"), "look_window": ("window", "daydream", "смотрит в окно"),
    "read_book": ("sofa", "read", "читает книгу"), "phone_call": ("window", "phone", "болтает по телефону"),
    "workout": ("center", "workout", "делает зарядку"), "tidy_up": ("center", None, "прибирается"),
    "write_diary": ("sofa", "write", "пишет в блокнот"), "console_off": (None, "", "выключает приставку"),
    "close_valve": ("stove", None, "перекрывает воду под мойкой"), "mop_floor": ("center", "mop", "вытирает пол"),
    "use_toilet": ("toilet", "toilet", "в туалете"), "shower": ("shower", "shower", "принимает душ"),
    "brush_teeth": ("sink", None, "чистит зубы"), "wash_face": ("sink", None, "умывается"),
    "comb_hair": ("sink", None, "причёсывается у зеркала"),
}
ACTIONS_DOC = """walk_to{place} — пойти к месту; wave, nod, shake_head, shrug, jump, dance, think, laugh, bow, stretch — жесты (несколько секунд);
sit — сесть на диван; stand — встать; watch_tv — сесть и смотреть телевизор; tv_off — выключить телевизор;
play_game — играть в приставку; music_on — поставить пластинку и слушать; music_off — выключить музыку;
cook — приготовить еду на плите; eat — поесть (после cook или из холодильника); drink — попить из холодильника; open_fridge — заглянуть в холодильник;
change_clothes{color} — переодеться; light_on{room} / light_off{room} — свет (room: bedroom, living, kitchen, bathroom, all; без room — там, где ты); look_window — смотреть в окно, мечтать;
open_gift{id} — открыть подарок в обёртке; eat_treat{id} — съесть вкусняшку из подарков; use_item{id} — воспользоваться подаренной вещью (книгу — читать, пластинку — слушать, игрушку — обнять, одежду — примерить);
use_toilet — сходить в туалет; shower — принять душ; brush_teeth — почистить зубы; wash_face — умыться; comb_hair — причесаться у зеркала;
console_off — выключить приставку; close_valve — перекрыть воду под мойкой (если течёт); mop_floor — вытирать воду с пола шваброй (имеет смысл, только когда вода уже не течёт);
read_book — читать книгу на диване; phone_call — позвонить кому-то из друзей или родных; workout — зарядка;
tidy_up — прибраться; write_diary — записать мысли в блокнот; sleep — лечь спать. Днём спать можно, только если бодрость ниже 30 (тогда это короткий сон) или до отбоя меньше 15 минут; если просто хочется передохнуть — sit или look_window."""
LOOP_LABEL = {"sit": "сидит на диване", "watch": "смотрит телевизор", "game": "играет в приставку", "listen": "слушает пластинку",
              "sleep": "спит", "daydream": "смотрит в окно", "read": "читает книгу", "phone": "болтает по телефону",
              "workout": "делает зарядку", "write": "пишет в блокнот", "mop": "вытирает пол", "toilet": "сидит в туалете", "shower": "принимает душ"}
MOODS = {"happy", "neutral", "sad", "surprised", "angry", "sleepy", "love"}
# Ekman's basic emotions. Each fades on its own clock (minutes); opposites damp each other.
EMOTIONS = {"joy": "радость", "sadness": "грусть", "fear": "страх", "anger": "злость", "surprise": "удивление",
            "disgust": "отвращение", "contempt": "презрение"}
EMO_TAU = {"joy": 25, "sadness": 40, "fear": 8, "anger": 12, "surprise": 1.5, "disgust": 6, "contempt": 12}
EMO_OPPOSE = {"joy": ("sadness", "anger", "fear"), "sadness": ("joy",), "anger": ("joy",), "fear": ("joy",),
              "disgust": ("joy",), "contempt": (), "surprise": ()}
MOOD_COMPAT = {"happy": ("joy", 0.6), "love": ("joy", 0.8), "sad": ("sadness", 0.6), "angry": ("anger", 0.6),
               "surprised": ("surprise", 0.7), "neutral": ("neutral", 0.5), "sleepy": ("neutral", 0.5)}
EMO_LIST = "joy|sadness|fear|anger|surprise|disgust|contempt|neutral"
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
}
ROOMS = {"bedroom": ("bed", "night"), "living": ("liv", "floor"), "kitchen": ("kit",), "bathroom": ("bath",),
         "all": ("bed", "night", "liv", "floor", "kit", "bath")}
LAMP_RU = {"bed": "свет в спальне", "night": "ночник", "liv": "свет в гостиной", "floor": "торшер", "kit": "свет на кухне", "bath": "свет в ванной"}
WATER_MAX, WATER_RISE, MOP_RATE = 5.0, 10.0, 1.0  # cm; cm/min while leaking; cm/min while mopping
BASE_DRIFT = {"hunger": -0.30, "energy": -0.11, "fun": -0.22, "social": -0.10, "hygiene": -0.06, "bladder": -0.15}
NEED_RU = {"hunger": "сытость", "energy": "бодрость", "fun": "развлечённость", "social": "общение",
           "hygiene": "свежесть", "bladder": "туалет (100 — не хочется)"}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

SEED_SELF = """- Мне 27. Работаю удалённо иллюстратором, сейчас между заказами, так что времени много.
- Люблю виниловые пластинки, простые сериалы и готовить что-нибудь на скорую руку.
- Давно хочу пройти ту игру на приставке до конца и читать хотя бы по полчаса в день.
- Есть друзья и мама, с ними иногда созваниваюсь."""


# ---------- gifts
GIFT_CATALOG = {
    "cake": ("пирожное", "sweet"), "croissant": ("круассан", "sweet"), "chocolate": ("шоколадка", "sweet"),
    "icecream": ("мороженое", "sweet"), "cocoa": ("какао", "drink"), "teddy": ("плюшевый мишка", "toy"),
    "book": ("книга", "book"), "record": ("пластинка", "record"), "candle": ("ароматическая свеча", "decor"),
    "scarf": ("тёплый шарф", "clothes"), "plaid": ("мягкий плед", "decor"),
}
GIFT_KINDS = ("sweet", "drink", "book", "record", "toy", "clothes", "flowers", "decor", "other")
KIND_WORDS = [
    ("sweet", r"торт|пирож|круас|шокол|конфет|морожен|печень|пончик|макарун|десерт|кекс|маффин|вафл|эклер|чизкейк|сладк|вкусняш|булоч"),
    ("drink", r"кофе|какао|чай|сок|лимонад|смузи|вин[оа]|коктейл"),
    ("book", r"книг|роман|комикс|журнал|сборник"),
    ("record", r"пластинк|винил|альбом|диск"),
    ("toy", r"мишк|игрушк|плюш|зайч|котик|единорог"),
    ("clothes", r"шарф|свитер|футболк|носк|плать|шапк|кофт|худи|пижам|варежк"),
    ("flowers", r"цвет|букет|роз[ыау]|тюльпан|пион|ромашк"),
    ("decor", r"свеч|плед|подушк|ламп|картин|постер|кружк|ваз|растен|гирлянд|рамк"),
]
KIND_RU = {"sweet": "вкусняшка", "drink": "напиток", "book": "книга", "record": "пластинка", "toy": "игрушка",
           "clothes": "одежда", "flowers": "цветы", "decor": "вещь для дома", "other": "вещь"}


def guess_kind(name):
    low = name.lower()
    for kind, rx in KIND_WORDS:
        if re.search(rx, low):
            return kind
    return "other"


def now():
    return datetime.now(TZ)


def is_awake_time(t=None):
    t = t or now()
    return wake_h() <= t.hour < sleep_h()


def next_wake(t=None):
    t = t or now()
    w = t.replace(hour=wake_h(), minute=0, second=0, microsecond=0)
    return w if t < w else w + timedelta(days=1)


def today_sleep(t=None):
    t = t or now()
    if sleep_h() >= 24:
        return (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return t.replace(hour=sleep_h(), minute=0, second=0, microsecond=0)


def day_key(t=None):
    """The resident's 'day': the night after SLEEP_H still belongs to the day that just ended."""
    t = t or now()
    return (t - timedelta(days=1) if t.hour < wake_h() else t).strftime("%Y-%m-%d")


def human_date(t):
    return f"{WEEKDAYS[t.weekday()]}, {t.day} {MONTHS[t.month - 1]}, {t:%H:%M}"


def hhmm(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")


# ---------------------------------------------------------------- storage
class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT, data TEXT);
            CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
            CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, ts REAL, day TEXT, purpose TEXT, model TEXT,
                input_tokens INTEGER, output_tokens INTEGER, cost REAL, seconds REAL, ok INTEGER);
        """)

    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))
            self.db.commit()

    def add_event(self, kind, text, data=None):
        ts = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO events (ts, kind, text, data) VALUES (?,?,?,?)",
                                  (ts, kind, text, json.dumps(data or {}, ensure_ascii=False)))
            self.db.commit()
        return {"id": cur.lastrowid, "ts": ts, "kind": kind, "text": text, "data": data or {}}

    def events(self, kinds=None, limit=50, since=None):
        q, args = "SELECT id, ts, kind, text, data FROM events WHERE 1=1", []
        if kinds:
            q += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            args += list(kinds)
        if since is not None:
            q += " AND ts > ?"
            args.append(since)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [{"id": r[0], "ts": r[1], "kind": r[2], "text": r[3], "data": json.loads(r[4] or "{}")} for r in reversed(rows)]

    def log_usage(self, purpose, model, tin, tout, cost, secs, ok):
        with self.lock:
            self.db.execute("INSERT INTO usage (ts, day, purpose, model, input_tokens, output_tokens, cost, seconds, ok) VALUES (?,?,?,?,?,?,?,?,?)",
                            (time.time(), now().strftime("%Y-%m-%d"), purpose, model, tin, tout, cost, secs, 1 if ok else 0))
            self.db.commit()

    def usage_today(self):
        with self.lock:
            r = self.db.execute("SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost),0) FROM usage WHERE day=?",
                                (now().strftime("%Y-%m-%d"),)).fetchone()
            by = self.db.execute("SELECT purpose, COUNT(*) FROM usage WHERE day=? GROUP BY purpose", (now().strftime("%Y-%m-%d"),)).fetchall()
        return {"calls": r[0], "input": r[1], "output": r[2], "cost": round(r[3], 4), "by": dict(by)}


store = Store(DB_PATH)

# ---------------------------------------------------------------- settings: schedule, body, character
TRAITS = {  # key: (low end, high end, default)
    "extraversion": ("интроверт", "экстраверт", 60), "friendliness": ("колючесть", "дружелюбие", 70),
    "romance": ("прагматизм", "романтичность", 50), "positivity": ("пессимизм", "оптимизм", 65),
    "activity": ("лень", "активность", 55), "humor": ("серьёзность", "чувство юмора", 60),
    "curiosity": ("равнодушие", "любопытство", 60), "tidiness": ("небрежность", "аккуратность", 55),
    "sensitivity": ("невозмутимость", "ранимость", 50),
}
DEFAULT_SETTINGS = {"wake": WAKE_H, "sleep": SLEEP_H, "hunger_rate": 1.0, "traits": {k: v[2] for k, v in TRAITS.items()}}
SETTINGS = json.loads(json.dumps(DEFAULT_SETTINGS))
_saved = store.get("settings") or {}
SETTINGS.update({k: v for k, v in _saved.items() if k != "traits"})
SETTINGS["traits"].update(_saved.get("traits") or {})


def wake_h():
    return int(SETTINGS["wake"])


def sleep_h():
    return int(SETTINGS["sleep"])


def trait(k):
    return max(0, min(100, float(SETTINGS["traits"].get(k, 50)))) / 100


def apply_settings(body):
    errors = []
    new = json.loads(json.dumps(SETTINGS))
    try:
        if "wake" in body: new["wake"] = int(body["wake"])
        if "sleep" in body: new["sleep"] = int(body["sleep"])
        if "hunger_rate" in body: new["hunger_rate"] = round(max(0.3, min(3.0, float(body["hunger_rate"]))), 2)
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
    store.set("settings", SETTINGS)
    return None


# ---------------------------------------------------------------- live updates (SSE)
class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = set()

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)

    def publish(self, msg):
        data = json.dumps(msg, ensure_ascii=False)
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    self.clients.discard(q)


hub = Hub()


def emit_event(kind, text, data=None):
    ev = store.add_event(kind, text, data)
    hub.publish({"type": "event", "ev": ev})
    return ev


# ---------------------------------------------------------------- the model, via Claude Code
class LLMError(Exception):
    pass


def claude_bin():
    for c in (os.environ.get("CLAUDE_BIN"), os.environ.get("CLAUDE_CODE_EXECPATH"), shutil.which("claude")):
        if c and os.path.exists(c):
            return c
    found = glob.glob(os.path.expanduser("~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude"))
    if not found:
        raise LLMError("не найден Claude Code (claude)")
    ver = lambda p: [int(x) for x in re.findall(r"claude-code-(\d+)\.(\d+)\.(\d+)", p)[0]]
    return sorted(found, key=ver)[-1]


def parse_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise LLMError("ответ не JSON: " + text[:200])


busy_lock = threading.Lock()   # one model call at a time
busy_what = {"v": None}


def set_busy(what):
    busy_what["v"] = what
    hub.publish({"type": "busy", "what": what})


def llm(purpose, model, system, prompt, timeout=240):
    cmd = [claude_bin(), "-p", "--model", model, "--tools", "", "--system-prompt", system,
           "--output-format", "json", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
    env = dict(os.environ)
    if model == MODEL_FAST:
        env["MAX_THINKING_TOKENS"] = "0"  # everyday decisions don't need extended thinking: ~3 s and ~150 tokens instead of ~30 s and ~4k
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(DATA), env=env)
    except subprocess.TimeoutExpired:
        store.log_usage(purpose, model, 0, 0, 0, time.time() - t0, False)
        raise LLMError("таймаут")
    secs = time.time() - t0
    try:
        d = json.loads(p.stdout)
    except ValueError:
        store.log_usage(purpose, model, 0, 0, 0, secs, False)
        raise LLMError((p.stderr or p.stdout or "пустой ответ")[-300:])
    mu = d.get("modelUsage") or {}
    tin = sum(v.get("inputTokens", 0) + v.get("cacheReadInputTokens", 0) + v.get("cacheCreationInputTokens", 0) for v in mu.values())
    tout = sum(v.get("outputTokens", 0) for v in mu.values())
    cost = sum(v.get("costUSD", 0) for v in mu.values())
    store.log_usage(purpose, model, tin, tout, cost, secs, not d.get("is_error"))
    hub.publish({"type": "usage", "usage": store.usage_today()})
    if d.get("is_error"):
        raise LLMError(str(d.get("result"))[:300])
    log(f"llm {purpose} {model}: {tin} in / {tout} out, {secs:.1f}s")
    return parse_json(d.get("result", ""))


# ---------------------------------------------------------------- the resident's state
DEFAULT_STATE = {
    "name": "Лёва", "male": True, "location": "sofa", "loop": "sit", "label": "сидит на диване",
    "until": 0, "tv": "off", "console": False, "music": False, "outfit": "blue", "mood": "joy",
    "emo": {"joy": 0.35, "sadness": 0, "fear": 0, "anger": 0, "surprise": 0, "disgust": 0, "contempt": 0},
    "lights": {"bed": True, "night": False, "liv": True, "floor": False, "kit": True, "bath": False}, "water": 0.0, "leak": False,
    "react_at": 0, "react_reasons": [], "last_react": 0, "touch_log": [], "flowers_ts": 0,
    "items": [], "wishes": [], "next_id": 1,
    "needs": {"hunger": 70, "energy": 85, "fun": 55, "social": 50, "hygiene": 70, "bladder": 80},
    "thought": "", "intent": "", "plan": [], "plan_day": "", "act_seq": 0, "last_act": None,
    "last_tick": 0, "last_decide": 0, "reflect_ts": 0, "reflect_day": "",
}
state_lock = threading.RLock()
S = dict(DEFAULT_STATE, **(store.get("state") or {}))
S["needs"] = dict(DEFAULT_STATE["needs"], **S.get("needs", {}))
if "light" in S:  # older state had one switch for the whole flat
    S["lights"] = {k: bool(S["light"]) for k in DEFAULT_STATE["lights"]}
    del S["light"]
S["lights"] = dict(DEFAULT_STATE["lights"], **S.get("lights", {}))
S["emo"] = dict(DEFAULT_STATE["emo"], **S.get("emo", {}))


def save_state():
    with state_lock:
        store.set("state", S)


def public_state():
    with state_lock:
        s = {k: S[k] for k in ("name", "male", "location", "loop", "label", "until", "tv", "console", "music", "lights", "water", "leak", "flowers_ts", "items", "wishes",
                               "outfit", "mood", "emo", "needs", "thought", "intent", "plan", "act_seq", "last_act")}
    t = now()
    s["awake_time"] = is_awake_time(t)
    s["wake_at"] = next_wake(t).timestamp()
    s["sleep_at"] = today_sleep(t).timestamp()
    s["busy"] = busy_what["v"]
    with state_lock:
        s["needs_view"] = needs_view()
    return s


def g(m, f):
    return m if S["male"] else f


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
    return "Эмоции сейчас (базовые по Экману, 0–1): " + ", ".join(f"{EMOTIONS[k]} {v:.1f}" for v, k in felt) + "."


NEED_WORDS = {  # (threshold, masculine, feminine), checked from the top
    "hunger": [(70, "сыт", "сыта"), (40, "не голоден", "не голодна"), (20, "проголодался", "проголодалась"), (0, "очень голоден", "очень голодна")],
    "energy": [(70, "полон сил", "полна сил"), (40, "в порядке", "в порядке"), (20, "устал", "устала"), (0, "валится с ног", "валится с ног")],
    "fun": [(70, "весело", "весело"), (40, "нормально", "нормально"), (20, "скучно", "скучно"), (0, "тоска", "тоска")],
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
    d["social"] = -(0.04 + 0.16 * trait("extraversion"))          # extraverts need people more
    d["energy"] = BASE_DRIFT["energy"] * (1.25 - 0.5 * trait("activity"))  # active people tire slower
    return d


def need_rates():
    """Per-minute change of each need right now, and why."""
    loop = S["loop"]
    if loop == "sleep":
        return {k: (0.35 if k == "energy" else 0.0) for k in BASE_DRIFT}, "спит"
    rates = base_drift()
    for k, v in PER_MIN.get(loop, {}).items():
        rates[k] = rates.get(k, 0) + v
    return {k: round(v, 2) for k, v in rates.items()}, LOOP_LABEL.get(loop, "ничем особым не занят" if S["male"] else "ничем особым не занята")


def needs_view():
    rates, why = need_rates()
    return {"words": {k: need_word(k, v) for k, v in S["needs"].items()}, "rates": rates, "why": why}


def clampn(v):
    return max(0, min(100, round(v, 1)))


def update_needs():
    t = time.time()
    with state_lock:
        dt_min = min(30, max(0, (t - (S["last_tick"] or t)) / 60))
        S["last_tick"] = t
        for k in S["emo"]:
            tau = EMO_TAU[k] * (0.5 if S["loop"] == "sleep" else 1)
            S["emo"][k] = round(S["emo"][k] * math.exp(-dt_min / tau), 3)
        S["mood"] = dominant()[0]
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
        for k, v in base_drift().items():
            n[k] = clampn(n[k] + v * dt_min)
        for k, v in PER_MIN.get(S["loop"], {}).items():
            n[k] = clampn(n[k] + v * dt_min)


def clean_actions(raw):
    out = []
    for a in (raw if isinstance(raw, list) else [])[:6]:
        if not isinstance(a, dict):
            continue
        d = str(a.get("do", "")).strip()
        m = re.fullmatch(r"(\w+)\s*[{(]\s*([^})]*?)\s*[})]", d)  # the model sometimes writes the doc notation: open_gift{4}, light_on{living}
        if m:
            d, arg = m.group(1), m.group(2).strip("'\" ")
            a = dict(a)
            if arg.isdigit():
                a.setdefault("id", int(arg))
            elif arg in PLACES:
                a.setdefault("place", arg)
            elif arg in ROOMS:
                a.setdefault("room", arg)
            elif arg in COLORS:
                a.setdefault("color", arg)
        if d not in ACTIONS:
            continue
        x = {"do": d}
        if d == "walk_to":
            if a.get("place") not in PLACES:
                continue
            x["place"] = a["place"]
        if d in ("open_gift", "eat_treat", "use_item") and a.get("id") is not None:
            try:
                x["id"] = int(a["id"])
            except (TypeError, ValueError):
                pass
        if d in ("light_on", "light_off") and a.get("room") in ROOMS:
            x["room"] = a["room"]
        if d == "change_clothes" and a.get("color") in COLORS:
            x["color"] = a["color"]
        out.append(x)
    return out


# where a bare walk_to obviously leads: "went to the TV" means "watches TV"
NATURAL = {"tv": "watch_tv", "sofa": "sit", "music": "music_on", "stove": "cook", "fridge": "drink",
           "window": "look_window", "wardrobe": "change_clothes", "bed": "sleep", "toilet": "use_toilet", "sink": "wash_face", "shower": "shower"}


def complete_chain(actions):
    out = []
    for i, a in enumerate(actions):
        nxt = actions[i + 1] if i + 1 < len(actions) else None
        # a walk right before an action that walks there by itself is redundant
        if a["do"] == "walk_to" and nxt and ACTIONS[nxt["do"]][0]:
            continue
        out.append(a)
    if out and out[-1]["do"] == "walk_to" and out[-1]["place"] in NATURAL:
        out[-1] = {"do": NATURAL[out[-1]["place"]]}
    return out


def find_item(item_id, states, edible=None):
    for it in S["items"]:
        if it["state"] not in states:
            continue
        if edible is not None and (it["kind"] in ("sweet", "drink")) != edible:
            continue
        if item_id is None or it["id"] == item_id:
            return it
    return None


def resolve_gifts(actions):
    """Turn open_gift / eat_treat / use_item into concrete actions on real items; drop the impossible ones."""
    out, opened, used = [], set(), set()

    def pick(item_id, edible):
        # an item is usable if it's already open, or was unwrapped earlier in this same chain
        for want in (item_id, None):
            for it in S["items"]:
                if it["id"] in used or (want is not None and it["id"] != want):
                    continue
                if (it["kind"] in ("sweet", "drink")) != edible:
                    continue
                if it["state"] == "open" or (it["state"] == "wrapped" and it["id"] in opened):
                    return it
        return None

    for a in actions:
        d = a["do"]
        if d not in ("open_gift", "eat_treat", "use_item"):
            out.append(a)
            continue
        if d == "open_gift":
            it = next((x for x in S["items"] if x["state"] == "wrapped" and x["id"] not in opened and x["id"] == a.get("id")), None) or \
                 next((x for x in S["items"] if x["state"] == "wrapped" and x["id"] not in opened), None)
            if it:
                opened.add(it["id"])
        else:
            it = pick(a.get("id"), d == "eat_treat")
            if it:
                used.add(it["id"])
        if not it:
            continue
        info = {"id": it["id"], "name": it["name"], "kind": it["kind"]}
        if d == "use_item" and it["kind"] == "book":
            out.append(dict(info, do="read_book"))
        elif d == "use_item" and it["kind"] == "record":
            out.append(dict(info, do="music_on"))
        elif d == "use_item" and it["kind"] == "flowers":
            out.append(dict(info, do="look_window"))
        else:
            out.append(dict(info, do=d))
    return out


def gift_effects(a):
    """What happens to an item and to her when she opens, eats or uses it."""
    it = find_item(a.get("id"), ("wrapped", "open"))
    if not it:
        return
    d = a["do"]
    if d == "open_gift" and it["state"] == "wrapped":
        it["state"], it["opened_ts"] = "open", time.time()
        appraise("joy", 0.85 if it.get("wish") else 0.55)
        appraise("surprise", 0.4)
        emit_event("gift", f"Открыл{g('', 'а')} подарок: {it['name']}" + (" — то самое, что просил" + g("", "а") + "!" if it.get("wish") else "."), {"item": it})
    elif d == "eat_treat" and it["state"] == "open":
        it["state"] = "eaten"
        S["needs"]["hunger"] = clampn(S["needs"]["hunger"] + (25 if it["kind"] == "sweet" else 12))
        S["needs"]["bladder"] = clampn(S["needs"]["bladder"] - (8 if it["kind"] == "sweet" else 25))
        S["needs"]["fun"] = clampn(S["needs"]["fun"] + 5)
        feel("joy", 0.35)
        emit_event("gift", f"Съел{g('', 'а')} {it['name']}.", {"item": it})
    elif d in ("use_item", "read_book", "music_on", "look_window") and it["state"] == "open":
        it["used"] = it.get("used", 0) + 1
        S["needs"]["fun"] = clampn(S["needs"]["fun"] + 12)
        feel("joy", 0.3)


def add_wish(raw):
    name = re.sub(r"\s+", " ", str(raw or "")).strip(" .!«»\"'")[:80]
    if len(name) < 2:
        return
    with state_lock:
        key = name.lower()
        if any(w["name"].lower() == key for w in S["wishes"]):
            return
        w = {"id": S["next_id"], "name": name, "kind": guess_kind(name), "ts": time.time()}
        S["next_id"] += 1
        S["wishes"] = (S["wishes"] + [w])[-15:]
        save_state()
    emit_event("wish", f"Хочет в подарок: {name}", {"wish": w})
    hub.publish({"type": "state", "state": public_state()})


def body_allows(actions):
    """The body has a say: you can't fall asleep in the daytime when you're full of energy."""
    t = now()
    left = (today_sleep(t) - t).total_seconds() / 60
    if any(a["do"] == "sleep" for a in actions) and is_awake_time(t) and S["needs"]["energy"] >= 30 and left > 15:
        e = int(S["needs"]["energy"])
        emit_event("system", f"Хотел{g('', 'а')} лечь спать, но сна ни в одном глазу (бодрость {e}) — вместо этого прилег{g('', 'ла')} отдохнуть на диване.")
        actions = [a for a in actions if a["do"] not in ("sleep", "walk_to")] + [{"do": "sit"}]
    return actions


def act(actions, minutes=None, thought=None, intent=None, mood=None, aloud=None, source="mind", emotion=None):
    """Apply a list of actions to the world and tell every open page to animate them."""
    with state_lock:
        was_sleeping = S["loop"] == "sleep"
        loop, loc = S["loop"], S["location"]
        for a in actions:
            d = a["do"]
            place, new_loop, _ = ACTIONS[d]
            if d == "walk_to":
                place = a["place"]
            if place and place != loc:
                loc, loop = place, None
            if new_loop:            # settles into a lasting activity
                loop = new_loop
            elif new_loop is None:  # whole-body action: ends up standing
                loop = None
            if d == "watch_tv": S["tv"] = "show"
            if d == "play_game": S.update(tv="game", console=True)
            if d == "tv_off":
                S["tv"] = "off"
                if loop in ("watch", "game"): loop = "sit"
            if d == "console_off":
                S["console"] = False
                if S["tv"] == "game": S["tv"] = "show"
                if loop == "game": loop = "sit"
            if d == "music_on": S["music"] = True
            if d == "music_off": S["music"] = False
            if d in ("light_on", "light_off"):
                room = a.get("room") or room_of(loc)
                a["room"] = room
                for k in ROOMS[room]:
                    S["lights"][k] = d == "light_on"
            if d == "close_valve": S["leak"] = False
            if a.get("id") is not None and d in ("open_gift", "eat_treat", "use_item", "read_book", "music_on", "look_window"):
                gift_effects(a)
            if d == "sleep":
                S.update(tv="off", music=False, console=False)
                S["lights"] = {k: False for k in S["lights"]}
            if d == "change_clothes":
                S["outfit"] = a.get("color") or random.choice([c for c in COLORS if c != S["outfit"]])
                a["color"] = S["outfit"]
            for k, v in INSTANT.get(d, {}).items():
                S["needs"][k] = clampn(S["needs"][k] + v)
        if was_sleeping and loop != "sleep":
            S["lights"]["bed"] = True
        if loop == "mop" and S["water"] <= 0:
            loop = None
        S["loop"], S["location"] = loop, loc
        S["label"] = LOOP_LABEL[loop] if loop else "стоит: " + PLACES[loc]
        if loop == "mop":
            S["until"] = time.time() + 30 * 60  # mopping lasts until the floor is dry (see update_needs)
        elif loop in LOOP_LABEL and minutes:
            S["until"] = time.time() + max(1, float(minutes)) * 60
        elif actions:
            # quick chain (walk, cook, drink, gestures): decide again as soon as the body is done
            S["until"] = time.time() + 30 + 6 * len(actions)
        if thought is not None: S["thought"] = thought
        if intent is not None: S["intent"] = intent
        if emotion:
            feel(*emotion)
        elif mood in MOOD_COMPAT:
            feel(*MOOD_COMPAT[mood])
        S["act_seq"] += 1
        S["last_act"] = {"seq": S["act_seq"], "actions": actions, "ts": time.time(), "aloud": aloud or "", "thought": thought or "", "source": source}
        save_state()
        msg = {"type": "act", "seq": S["act_seq"], "actions": actions, "thought": thought or "", "aloud": aloud or "", "source": source, "state": public_state()}
    hub.publish(msg)
    if actions:
        emit_event("action", ", ".join(ACTIONS[a["do"]][2] + (" → " + PLACES[a["place"]] if a.get("place") else "") for a in actions),
                   {"actions": actions, "minutes": minutes})


# ---------------------------------------------------------------- prompts
TRAIT_WORDS = {  # five bands per trait: (masculine, feminine)
    "extraversion": [("ярко выраженный интроверт: общение быстро утомляет, тебе нужна тишина и своё пространство", "ярко выраженная интровертка: общение быстро утомляет, тебе нужна тишина и своё пространство"),
                     ("скорее интроверт: общаешься охотно, но недолго", "скорее интровертка: общаешься охотно, но недолго"),
                     ("амбиверт: можешь и поболтать, и побыть один", "амбивертка: можешь и поболтать, и побыть одна"),
                     ("экстраверт: любишь общаться и легко заводишь разговор", "экстравертка: любишь общаться и легко заводишь разговор"),
                     ("яркий экстраверт: обожаешь болтать, скучаешь в одиночестве, сам заговариваешь с гостем", "яркая экстравертка: обожаешь болтать, скучаешь в одиночестве, сама заговариваешь с гостем")],
    "friendliness": [("колючий и ворчливый, держишь дистанцию", "колючая и ворчливая, держишь дистанцию"), ("сдержанный, не сразу открываешься", "сдержанная, не сразу открываешься"),
                     ("вежливый и ровный", "вежливая и ровная"), ("дружелюбный и тёплый", "дружелюбная и тёплая"), ("очень дружелюбный, открытый и ласковый", "очень дружелюбная, открытая и ласковая")],
    "romance": [("прагматик, романтика тебя смешит", "прагматичная, романтика тебя смешит"), ("сдержан в чувствах", "сдержанна в чувствах"),
                ("умеренно романтичен", "умеренно романтична"), ("романтичный, ценишь нежность", "романтичная, ценишь нежность"),
                ("очень романтичный и мечтательный, обожаешь нежности и знаки внимания", "очень романтичная и мечтательная, обожаешь нежности и знаки внимания")],
    "positivity": [("пессимист, во всём замечаешь плохое", "пессимистка, во всём замечаешь плохое"), ("скептик", "скептичная"), ("реалист", "реалистка"),
                   ("оптимист", "оптимистка"), ("солнечный оптимист, радуешься мелочам", "солнечная оптимистка, радуешься мелочам")],
    "activity": [("ленивый, больше всего любишь лежать", "ленивая, больше всего любишь лежать"), ("неспешный", "неспешная"), ("умеренно активный", "умеренно активная"),
                 ("активный, любишь двигаться и что-то делать", "активная, любишь двигаться и что-то делать"), ("энерджайзер, на месте не сидится", "энерджайзер, на месте не сидится")],
    "humor": [("очень серьёзный, шутишь редко", "очень серьёзная, шутишь редко"), ("скорее серьёзный", "скорее серьёзная"), ("с нормальным чувством юмора", "с нормальным чувством юмора"),
              ("с хорошим чувством юмора, любишь пошутить", "с хорошим чувством юмора, любишь пошутить"), ("шутник, постоянно дурачишься и подкалываешь", "хохотушка, постоянно дурачишься и подкалываешь")],
    "curiosity": [("равнодушный к новому", "равнодушная к новому"), ("не очень любопытный", "не очень любопытная"), ("в меру любопытный", "в меру любопытная"),
                  ("любопытный, интересуешься людьми и миром", "любопытная, интересуешься людьми и миром"), ("очень любопытный, всё хочешь узнать и обо всём расспросить", "очень любопытная, всё хочешь узнать и обо всём расспросить")],
    "tidiness": [("небрежный, бардак тебя не волнует", "небрежная, бардак тебя не волнует"), ("не слишком аккуратный", "не слишком аккуратная"), ("в меру аккуратный", "в меру аккуратная"),
                 ("аккуратный, любишь чистоту", "аккуратная, любишь чистоту"), ("чистюля и аккуратист, беспорядок раздражает", "чистюля и аккуратистка, беспорядок раздражает")],
    "sensitivity": [("невозмутимый, тебя трудно задеть", "невозмутимая, тебя трудно задеть"), ("спокойный", "спокойная"), ("обычной чувствительности", "обычной чувствительности"),
                    ("чувствительный", "чувствительная"), ("очень ранимый, всё принимаешь близко к сердцу", "очень ранимая, всё принимаешь близко к сердцу")],
}


def character_text():
    parts = []
    for k in TRAITS:
        band = min(4, int(trait(k) * 5))
        m, f = TRAIT_WORDS[k][band]
        parts.append(m if S["male"] else f)
    return "; ".join(parts)


def persona():
    return f"""Ты — {S['name']}, {g('парень', 'девушка')}, 27 лет. Ты живёшь {g('один', 'одна')} в маленькой квартире: спальня (кровать, шкаф с одеждой, окно на город), гостиная-кухня (диван, телевизор с игровой приставкой, проигрыватель пластинок, холодильник, плита, полки с посудой) и санузел (унитаз, раковина с зеркалом, зубные щётки, расчёска, полотенце, душ).
У тебя есть тело, потребности, настроение, характер, увлечения и свои планы. Ты живёшь своей жизнью: никто не говорит тебе, что делать, ты решаешь сам{g('', 'а')}.
Иногда с тобой разговаривает гость — человек, который смотрит на твою квартиру «через стекло». Ты о нём знаешь и рад{g('', 'а')} поболтать, но твоя жизнь не крутится вокруг него.
Иногда в квартире что-то происходит само: гаснет свет, включается телевизор, прорывает трубу. Возможно, это проделки гостя — он, кажется, умеет влиять на твой мир. Реагируй на такое как живой человек: заметь, исправь, если мешает, удивись, поворчи или спроси гостя.
Гость может дарить подарки — вкусняшки и вещи. Если тебе чего-то по-настоящему хочется, можешь попросить его (поле wish), но не выпрашивай постоянно: он сам решает, дарить ли и когда.
Гость может и прикоснуться к тебе: погладить по голове, поцеловать в щёку, взять за руку, обнять, подарить цветы. Отвечай по-своему, исходя из того, как ты к нему сейчас относишься: это может быть приятно, трогательно, смущать или раздражать, если ты на него сердишься или он перебарщивает.
У тебя живые эмоции — базовые по Экману: радость, грусть, страх, злость, удивление, отвращение, презрение. Они видны на лице и в позе и влияют на твои решения и слова. Каждый раз честно называй, что чувствуешь сейчас, и с какой силой; не каждое событие вызывает сильную эмоцию, а спокойствие — это neutral.
Твой характер (это главное в тебе, важнее старых заметок о себе — если заметки противоречат характеру, верь характеру): {character_text()}.
Говори о себе в {g('мужском', 'женском')} роде. Пиши по-русски, живо и естественно, без пафоса и без канцелярита. Ты бодрствуешь с {wake_h()}:00 до {sleep_h()}:00, потом спишь.

Что умеет твоё тело (поле "do" в actions):
{ACTIONS_DOC}
Намерение и действия должны совпадать: если решаешь что-то сделать (открыть подарок, поесть, включить свет) — это обязательно должно быть в actions, иначе тело ничего не сделает.
Как работают действия: actions — цепочка, которую тело выполняет сразу, за секунды. До нужного места действия доводят сами (watch_tv сам усадит на диван, cook сам подведёт к плите, music_on — к проигрывателю), так что walk_to перед ними не нужен; walk_to — только чтобы просто пойти куда-то. Заканчивай цепочку тем, ради чего идёшь: не «подойти к телевизору», а watch_tv. Мысли и слова — о том, что делаешь сейчас целиком, а не «иду к…».
minutes — сколько продлится последнее долгое занятие (watch_tv, play_game, music_on, read_book, write_diary, phone_call, workout, look_window, sit). Если в цепочке только быстрые дела (cook, eat, drink, change_clothes, tidy_up, жесты), ставь minutes 1–3: ты закончишь и сразу решишь, что дальше.
Места для walk_to.place: {", ".join(PLACES)}. Цвета для change_clothes.color: {", ".join(COLORS)}.
Отвечай только JSON указанной формы, без пояснений."""


def room_of(loc):
    if loc in ("toilet", "sink", "shower"):
        return "bathroom"
    return "bedroom" if loc in ("bed", "window", "wardrobe") else "kitchen" if loc in ("fridge", "stove") else "living"


def room_ru(room):
    return {"bedroom": "спальня", "living": "гостиная", "kitchen": "кухня", "bathroom": "санузел"}[room]


def world_line():
    L = S["lights"]
    lit = lambda keys: any(L[k] for k in keys)
    lights = f"Свет: спальня {'горит' if L['bed'] else 'выключен'} (ночник {'вкл' if L['night'] else 'выкл'}), гостиная {'горит' if L['liv'] else 'выключен'} (торшер {'вкл' if L['floor'] else 'выкл'}), кухня {'горит' if L['kit'] else 'выключен'}, санузел {'горит' if L['bath'] else 'выключен'}."
    here = room_of(S["location"])
    dark = "" if lit(ROOMS[here]) else f" Там, где ты ({room_ru(here)}), свет не горит — темновато."
    tv = "выключен" if S["tv"] == "off" else "показывает игру с приставки" if S["tv"] == "game" else "включён"
    water = ""
    if S["leak"]:
        water = f" ВНИМАНИЕ: под мойкой течёт вода, на полу уже {S['water']:.0f} см воды и прибывает!"
    elif S["water"] > 0.2:
        water = f" На полу лужа: {S['water']:.1f} см воды (течь уже перекрыта)."
    flowers = " На подоконнике в спальне стоят цветы от гостя." if time.time() - (S.get("flowers_ts") or 0) < 3 * 86400 else ""
    wrapped = [it for it in S["items"] if it["state"] == "wrapped"]
    treats = [it for it in S["items"] if it["state"] == "open" and it["kind"] in ("sweet", "drink")]
    things = [it for it in S["items"] if it["state"] == "open" and it["kind"] not in ("sweet", "drink", "flowers")]
    if wrapped:
        flowers += " Неоткрытые подарки от гостя: " + ", ".join(f"коробка id={it['id']}" + (f" (похоже, {it['name']})" if it.get("wish") else "") for it in wrapped) + "."
    if treats:
        flowers += " Вкусняшки от гостя на столике: " + ", ".join(f"{it['name']} (id={it['id']})" for it in treats) + "."
    if things:
        flowers += " Подаренные вещи на полке: " + ", ".join(f"{it['name']} (id={it['id']})" for it in things[-8:]) + "."
    if S["wishes"]:
        flowers += " Ты уже просил" + g("", "а") + " гостя подарить: " + ", ".join(w["name"] for w in S["wishes"]) + " — он сам решает, дарить ли и когда."
    return (f"Телевизор: {tv}. Приставка: {'включена' if S['console'] else 'выключена'}. Музыка: {'играет' if S['music'] else 'нет'}. "
            + lights + dark + water + flowers)


def situation():
    t = now()
    with state_lock:
        n = S["needs"]
        left = max(0, int((today_sleep(t) - t).total_seconds() // 60))
        hints = []
        if n["hunger"] < 30: hints.append(g("ты проголодался", "ты проголодалась"))
        if n["energy"] < 25: hints.append(g("ты устал", "ты устала"))
        if n["fun"] < 25: hints.append("тебе скучно")
        if n["social"] < 25: hints.append("хочется с кем-нибудь поговорить")
        if n["hygiene"] < 35: hints.append("хочется освежиться — в душ или хотя бы умыться")
        if n["bladder"] < 30: hints.append("очень хочется в туалет" if n["bladder"] < 15 else "хочется в туалет")
        lines = [
            f"Сейчас {human_date(t)}. До сна {left // 60} ч {left % 60} мин.",
            f"Ты: {S['label']} ({room_ru(room_of(S['location']))}).",
            world_line() + f" На тебе {COLORS.get(S['outfit'], S['outfit'])}.",
            "Самочувствие (0 — плохо, 100 — отлично): " + ", ".join(f"{NEED_RU[k]} {int(v)} ({need_word(k, v)})" for k, v in n.items()) + (". " + "; ".join(hints).capitalize() + "." if hints else "."),
            emo_line(),
        ]
        if S["plan"]:
            lines.append("Твой план на сегодня:\n" + "\n".join("- " + p for p in S["plan"]))
    lines.append("Что ты знаешь о себе:\n" + (store.get("self_notes") or SEED_SELF))
    guest = store.get("guest_notes")
    if guest:
        lines.append("Что ты знаешь о госте:\n" + guest)
    return "\n\n".join(lines)


def recent_lines(limit=18):
    out = []
    for e in store.events(["thought", "action", "chat_user", "chat_reply", "aloud", "plan", "world", "gift", "wish"], limit=limit):
        who = {"thought": "думал(а)", "action": "делал(а)", "chat_user": "гость сказал", "chat_reply": "ты ответил(а)",
               "aloud": "сказал(а) вслух", "plan": "план", "world": "случилось", "gift": "подарок", "wish": "попросил(а)"}[e["kind"]]
        out.append(f"[{hhmm(e['ts'])}] {who}: {e['text']}")
    return "\n".join(out) or "(пока ничего)"


def chat_lines(limit=12):
    out = []
    for e in store.events(["chat_user", "chat_reply", "aloud"], limit=limit):
        out.append({"chat_user": "Гость: ", "chat_reply": "Ты: ", "aloud": "Ты (вслух): "}[e["kind"]] + e["text"])
    return "\n".join(out)


# ---------------------------------------------------------------- what the mind does
def decide(reason="next", happened=None):
    if happened:
        reason_text = "Только что, прямо сейчас:\n" + "\n".join("- " + h for h in happened) + "\nТы это замечаешь и реагируешь (можно прервать текущее занятие)."
    else:
        reason_text = "Прошлое занятие закончилось." if reason == "next" else "Тебя отвлекло самочувствие."
    prompt = f"""{situation()}

Недавно:
{recent_lines()}

{reason_text} Реши, чем заняться дальше. Твой характер: {character_text()} — пусть он определяет, чем тебе хочется заняться. Это твоя жизнь: следуй своим желаниям, плану и самочувствию, не повторяй одно и то же без причины, иногда делай что-то неожиданное.
Ответ JSON:
{{"thought": "внутренний монолог, 1–3 предложения", "intent": "коротко, что сейчас делаешь", "actions": [{{"do": "..."}}], "minutes": сколько минут продлится последнее долгое занятие (1–90), "emotion": "{EMO_LIST}", "intensity": сила эмоции 0.1–1, "aloud": "что говоришь вслух сам{g('', 'а')} себе, или пусто", "diary": "короткая заметка в блокнот, если случилось важное, иначе пусто", "wish": "ОБЯЗАТЕЛЬНО заполни, если в этом ответе ты говоришь, что хотел{g('', 'а')} бы получить что-то в подарок или просишь что-то подарить: что именно, коротко (например «круассан», «книга Бунина в твёрдом переплёте»); иначе пусто"}}"""
    r = llm("decide", MODEL_FAST, persona(), prompt)
    actions = resolve_gifts(body_allows(complete_chain(clean_actions(r.get("actions")))))
    if json.dumps(r.get("actions"), ensure_ascii=False, sort_keys=True) != json.dumps(actions, ensure_ascii=False, sort_keys=True):
        log("actions:", json.dumps(r.get("actions"), ensure_ascii=False)[:300], "->", json.dumps(actions, ensure_ascii=False)[:300])
    minutes = max(1, min(90, int(r.get("minutes") or 20)))
    if not actions:
        minutes = min(minutes, 5)  # nothing actually done: look again soon
    thought = str(r.get("thought") or "").strip()
    with state_lock:
        S["last_decide"] = time.time()
    if thought:
        emit_event("thought", thought)
    aloud = str(r.get("aloud") or "").strip()
    if aloud:
        emit_event("aloud", aloud)
    if str(r.get("diary") or "").strip():
        emit_event("note", str(r["diary"]).strip())
    if r.get("wish"):
        add_wish(r["wish"])
    act(actions, minutes=minutes, thought=thought, intent=str(r.get("intent") or "").strip(), emotion=parse_emotion(r), aloud=aloud)


def morning():
    t = now()
    diary = store.events(["diary"], limit=1)
    prompt = f"""{situation()}

Вчерашний дневник:
{diary[-1]['text'] if diary else '(дневника ещё нет — это твой первый день здесь)'}

Ты только что {g('проснулся', 'проснулась')}. Составь себе нестрогий план на сегодня (с {wake_h()}:00 до {sleep_h()}:00): 3–6 пунктов — дела, желания, маленькие цели. Учитывай свои увлечения, проекты и то, что было вчера.
Ответ JSON: {{"plan": ["пункт", "..."], "thought": "первая мысль утром, 1–2 предложения", "emotion": "{EMO_LIST}", "intensity": сила эмоции 0.1–1}}"""
    try:
        r = llm("plan", MODEL_DEEP, persona(), prompt)
        plan = [str(p).strip() for p in (r.get("plan") or []) if str(p).strip()][:6]
        thought = str(r.get("thought") or "").strip()
        emotion = parse_emotion(r)
    except LLMError as e:
        emit_event("system", f"Утренний план не составился: {e}")
        plan, thought, emotion = [], "", None
    with state_lock:
        S["plan"], S["plan_day"] = plan, t.strftime("%Y-%m-%d")
        S["needs"]["energy"] = max(S["needs"]["energy"], 85)
        S["needs"]["bladder"] = min(S["needs"]["bladder"], 30)
        S["needs"]["hygiene"] = min(S["needs"]["hygiene"], 55)
    if plan:
        emit_event("plan", "; ".join(plan), {"plan": plan})
    if thought:
        emit_event("thought", thought)
    act([{"do": "stand"}, {"do": "stretch"}], minutes=1, thought=thought, intent="просыпается", emotion=emotion)


def reflect():
    """Evening reflection = diary + memory compaction (rewrite notes about self and guest)."""
    since = S.get("reflect_ts") or 0
    evs = store.events(["thought", "action", "chat_user", "chat_reply", "aloud", "plan", "note", "world", "gift", "wish"], limit=400, since=since)
    if not evs:
        with state_lock:
            S["reflect_ts"] = time.time()
        save_state()
        return
    lines = "\n".join(f"[{hhmm(e['ts'])}] {e['kind']}: {e['text']}" for e in evs)[-60000:]
    prompt = f"""{situation()}

Всё, что было с прошлого вечера:
{lines}

День закончился, ты ложишься спать. Подведи итоги.
Ответ JSON:
{{"diary": "запись в дневник за сегодня от первого лица, 4–8 предложений: что делал{g('', 'а')}, что чувствовал{g('', 'а')}, что запомнилось",
 "self_notes": "обновлённые заметки о себе (до 1500 символов, короткие пункты «- »): характер, привычки, увлечения, текущие проекты и цели, отношения с друзьями и родными, важные события. Сохрани важное из старых заметок, обнови устаревшее, добавь новое",
 "guest_notes": "обновлённые заметки о госте (до 1000 символов, пункты «- »): как зовут, что о нём известно, о чём говорили, о чём договорились. Если гость не появлялся — верни прежние заметки как есть или пусто"}}"""
    r = llm("reflect", MODEL_DEEP, persona(), prompt, timeout=300)
    if str(r.get("diary") or "").strip():
        emit_event("diary", str(r["diary"]).strip())
    if str(r.get("self_notes") or "").strip():
        store.set("self_notes", str(r["self_notes"]).strip()[:2500])
    if str(r.get("guest_notes") or "").strip():
        store.set("guest_notes", str(r["guest_notes"]).strip()[:2000])
    with state_lock:
        S["reflect_ts"] = time.time()
    save_state()
    hub.publish({"type": "notes", "notes": notes(), "diary": store.events(["diary"], limit=10)})


def notes():
    return {"self": store.get("self_notes") or SEED_SELF, "guest": store.get("guest_notes") or ""}


SLEEPY = ["Ззз…", "(сонно) м-м… утром поговорим…", "(переворачивается на другой бок)", "Хр-р… пять минуточек…", "(бормочет во сне что-то про пластинки)"]


DOING_WORDS = re.compile(r"\b(открыва|откро|пойд|пошл|иду|идём|идем|едем|сейчас|свар|приготов|включ|выключ|поставл|почита|поигра|посмотр|переоде|умо|приму|лягу|сяду|возьм|давай)")


def chat(text):
    emit_event("chat_user", text)
    with state_lock:
        S["needs"]["social"] = clampn(S["needs"]["social"] + 4 + 8 * trait("extraversion"))
        S["needs"]["energy"] = clampn(S["needs"]["energy"] - 1.5 * (1 - trait("extraversion")))  # talking tires an introvert
        asleep = not is_awake_time()
    if asleep:
        line = random.choice(SLEEPY)
        emit_event("chat_reply", line, {"asleep": True, "wake_at": next_wake().timestamp()})
        hub.publish({"type": "say", "text": line})
        return
    with busy_lock:
        set_busy("chat")
        try:
            prompt = f"""{situation()}

Недавно:
{recent_lines(12)}

Разговор с гостем:
{chat_lines()}

Гость только что сказал: {text}

Твой характер: {character_text()}. Отвечай так, как ответил бы человек именно с таким характером — даже если раньше вы спорили или ты был{g('', 'а')} другой; характер важнее прошлых реплик и заметок.
Ответь гостю как живой человек: коротко (1–3 предложения), в своём характере и настроении. Если хочешь или гость просит — сделай что-то (actions); если нет — actions пустой, и ты продолжаешь своё занятие.
ВАЖНО: тело делает только то, что в actions. Если в реплике ты говоришь, что что-то делаешь или сейчас сделаешь («открываю», «пойду сварю кофе», «включу музыку», «давай почитаю»), — обязательно добавь это действие в actions (open_gift, cook, music_on, read_book…). Не обещай словами то, чего не делаешь.
Ответ JSON: {{"say": "реплика гостю", "thought": "что ты при этом подумал{g('', 'а')}, 1 предложение", "emotion": "{EMO_LIST}", "intensity": сила эмоции 0.1–1, "actions": [], "minutes": сколько минут займёт новое занятие, если actions не пустой, "wish": "ОБЯЗАТЕЛЬНО заполни, если в этом ответе ты говоришь, что хотел{g('', 'а')} бы получить что-то в подарок или просишь что-то подарить: что именно, коротко (например «круассан», «книга Бунина в твёрдом переплёте»); иначе пусто"}}"""
            r = llm("chat", MODEL_FAST, persona(), prompt)
            say = str(r.get("say") or "").strip() or "…"
            actions = resolve_gifts(body_allows(complete_chain(clean_actions(r.get("actions")))))
            thought = str(r.get("thought") or "").strip()
            emit_event("chat_reply", say, {"actions": actions})
            if r.get("wish"):
                add_wish(r["wish"])
            if thought:
                emit_event("thought", thought)
            minutes = max(3, min(90, int(r.get("minutes") or 15))) if actions else None
            if not actions and DOING_WORDS.search(say.lower()):
                # she promised to do something but the answer carried no actions: let her own mind follow through
                with state_lock:
                    S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"Ты только что сказал{g('', 'а')} гостю: «{say[:200]}». Сделай то, что пообещал{g('', 'а')}."]
                    S["react_at"] = time.time() + 2
                log("chat promised without actions, follow-up scheduled:", say[:120])
            act(actions, minutes=minutes, thought=thought or None, emotion=parse_emotion(r), source="chat")
            hub.publish({"type": "say", "text": say})
        except (LLMError, ValueError) as e:
            emit_event("chat_reply", "Прости, задумал" + g("ся", "ась") + "… повтори?", {"error": str(e)})
            emit_event("system", f"Ответ не получился: {e}")
        finally:
            set_busy(None)


POKES = ("bed", "night", "liv", "floor", "kit", "bath", "tv", "console", "music", "flood", "pat", "kiss", "hand", "hug", "flowers")
# tender touches: (what she perceives, what the guest did, joy, surprise)
TOUCHES = {
    "pat": ("Кто-то невидимый нежно погладил тебя по голове.", "погладили по голове", 0.5, 0.25),
    "kiss": ("Ты почувствовал{a} лёгкий поцелуй в щёку — кажется, это гость.", "чмокнули в щёчку", 0.6, 0.35),
    "hand": ("Кто-то тёплый взял тебя за руку и немного подержал.", "взяли за руку", 0.45, 0.2),
    "hug": ("Тебя вдруг тепло и крепко обняли — никого не видно, но объятие настоящее.", "обняли", 0.65, 0.3),
    "flowers": ("На подоконнике в спальне вдруг появился букет свежих цветов!", "подарили цветы", 0.6, 0.6),
}


def poke(what):
    """The guest changes the world. The resident perceives it as something that just happened."""
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
            appraise("joy", joy * f * (0.5 + trait("romance")) * (0.7 + 0.6 * trait("friendliness")))
            appraise("surprise", surprise * (0.7 ** len(recent)))
            S["needs"]["social"] = clampn(S["needs"]["social"] + 8 * f)
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
            appraise("surprise", 0.9); appraise("fear", 0.5)
        elif what in LAMP_RU:
            appraise("surprise", 0.35 if on else 0.5)
            if not on: appraise("fear", 0.15)
        else:
            appraise("surprise", 0.4)
            if not on and ((what == "music" and was in ("listen",)) or (what in ("tv", "console") and was in ("watch", "game", "sit"))):
                appraise("anger", 0.35)
        awake = is_awake_time()
        if awake:
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = public_state()
    emit_event("world", text, {"by": "guest", "what": what, "guest": guest})
    hub.publish({"type": "world", "what": what, "text": text, "guest": guest, "state": st})
    return st


def give_gift(key=None, name=None, kind=None, wish_id=None):
    with state_lock:
        wish = None
        if wish_id is not None:
            wish = next((w for w in S["wishes"] if w["id"] == wish_id), None)
            if not wish:
                return None, "такого желания уже нет"
            name, kind = wish["name"], wish["kind"]
            S["wishes"] = [w for w in S["wishes"] if w["id"] != wish_id]
        elif key in GIFT_CATALOG:
            name, kind = GIFT_CATALOG[key]
        else:
            name = re.sub(r"\s+", " ", str(name or "")).strip()[:80]
            if len(name) < 2:
                return None, "напишите, что подарить"
            kind = kind if kind in GIFT_KINDS else guess_kind(name)
            wish = next((w for w in S["wishes"] if w["name"].lower() == name.lower()), None)
            if wish:
                S["wishes"] = [w for w in S["wishes"] if w["id"] != wish["id"]]
        it = {"id": S["next_id"], "name": name, "kind": kind, "ts": time.time(), "state": "wrapped", "wish": bool(wish)}
        S["next_id"] += 1
        if kind == "flowers":
            it["state"], S["flowers_ts"] = "open", time.time()
            text = f"На подоконнике в спальне появился букет: {name}" + (" — ты же об этом просил" + g("", "а") + "!" if wish else "!")
        else:
            text = "Перед телевизором появилась коробка с бантом — подарок от гостя" + (f". Кажется, это то, что ты просил{g('', 'а')}: {name}!" if wish else ". Что внутри — непонятно.")
        S["items"] = (S["items"] + [it])[-40:]
        appraise("surprise", 0.45)
        appraise("joy", 0.5 if wish else 0.25)
        if is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = public_state()
    emit_event("world", text, {"by": "guest", "what": "gift", "guest": f"подарили: {name}", "item": it})
    hub.publish({"type": "world", "what": "gift", "text": text, "guest": f"подарили: {name}", "state": st})
    return st, None


def drop_wishes(wish_id=None):
    with state_lock:
        S["wishes"] = [] if wish_id is None else [w for w in S["wishes"] if w["id"] != wish_id]
        save_state()
        st = public_state()
    hub.publish({"type": "state", "state": st})
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
    hub.publish({"type": "state", "state": public_state()})


# ---------------------------------------------------------------- the clock that runs the life
def mind_step():
    update_needs()
    t = now()
    if not is_awake_time(t):
        # evening: one reflection per day (diary + memory compaction), then sleep; no model calls at night
        if S.get("reflect_day") != day_key(t):
            with busy_lock:
                set_busy("reflect")
                try:
                    reflect()
                except (LLMError, ValueError) as e:
                    emit_event("system", f"Вечерние итоги не получились: {e}")
                finally:
                    with state_lock:
                        S["reflect_day"] = day_key(t)
                    set_busy(None)
        if S["loop"] != "sleep":
            act([{"do": "sleep"}], thought="Всё, на сегодня хватит. Спать.", intent="спит", mood="sleepy", aloud="Спокойной ночи.")
        with state_lock:
            S["until"] = next_wake(t).timestamp()
        if S["leak"] or int(time.time()) % 60 < TICK:
            save_state()
            hub.publish({"type": "needs", "needs": S["needs"], "needs_view": needs_view(), "water": S["water"], "leak": S["leak"], "emo": S["emo"]})
        return
    if S["plan_day"] != t.strftime("%Y-%m-%d"):
        with busy_lock:
            set_busy("plan")
            try:
                morning()
            finally:
                set_busy(None)
        return
    if S["loop"] == "sleep" and S["until"] > today_sleep(t).timestamp():
        with state_lock:
            S["until"] = time.time()  # night sleep but it's daytime now (hours changed, server was down): wake up
    if S.get("react_reasons") and time.time() >= S.get("react_at", 0):
        if not busy_lock.acquire(blocking=False):
            return
        with state_lock:
            happened, S["react_reasons"], S["last_react"] = S["react_reasons"], [], time.time()
        set_busy("think")
        try:
            decide("react", happened=happened)
        except (LLMError, ValueError) as e:
            emit_event("system", f"Реакция не сложилась ({e}).")
        finally:
            set_busy(None)
            busy_lock.release()
        return
    n = S["needs"]
    urgent = min(n.values()) < 10 and time.time() - S["last_decide"] > 600 and S["loop"] != "sleep"
    if time.time() >= S["until"] or urgent:
        if not busy_lock.acquire(blocking=False):
            return
        set_busy("think")
        try:
            decide("urgent" if urgent and time.time() < S["until"] else "next")
        except (LLMError, ValueError) as e:
            emit_event("system", f"Мысль не сложилась ({e}). Попробую через 10 минут.")
            act([{"do": "look_window"}], minutes=10, thought="…", intent="задумался")
        finally:
            set_busy(None)
            busy_lock.release()
    elif S["leak"] or S["loop"] == "mop" or int(time.time()) % 60 < TICK:
        save_state()
        hub.publish({"type": "needs", "needs": S["needs"], "needs_view": needs_view(), "water": S["water"], "leak": S["leak"], "emo": S["emo"]})


def mind_loop():
    while True:
        try:
            mind_step()
        except Exception:
            log("mind error:\n" + traceback.format_exc())
        time.sleep(TICK)


# ---------------------------------------------------------------- HTTP
def snapshot():
    return {
        "state": public_state(), "now": time.time(), "tz": str(TZ), "wake_h": wake_h(), "sleep_h": sleep_h(), "settings": SETTINGS,
        "chat": store.events(["chat_user", "chat_reply", "aloud"], limit=40),
        "feed": store.events(["thought", "action", "aloud", "plan", "note", "system", "world", "gift", "wish"], limit=40),
        "diary": store.events(["diary"], limit=10),
        "notes": notes(), "usage": store.usage_today(),
    }


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>За стеклом</title><style>
:root{--bg:#e9ece6;--panel:#f8faf5;--fg:#1c2124;--muted:#5b6661;--line:#d0d7cd;--accent:#2c52c4;--danger:#b8392b}
@media (prefers-color-scheme:dark){:root{--bg:#13171a;--panel:#1b2024;--fg:#e6ebe7;--muted:#97a29d;--line:#2b3237;--accent:#8ea6ff;--danger:#f08a7c;color-scheme:dark}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding-inline:16px}
form{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px;display:grid;gap:12px;width:min(320px,100%)}
h1{margin:0;font-size:20px} p{margin:0;color:var(--muted);font-size:14px} .err{color:var(--danger)}
input{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
button{font:inherit;font-weight:600;padding:10px;border-radius:10px;border:0;background:var(--accent);color:#fff;cursor:pointer}
</style></head><body><form method="post" action="/login"><h1>За стеклом</h1><p>Введите пароль, чтобы заглянуть в квартиру.</p>%ERR%
<input type="password" name="password" autofocus autocomplete="current-password" aria-label="Пароль"><button>Войти</button></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ZaSteklom/1.0"

    def authed(self):
        if not PASSWORD:
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "zs_auth" and v == AUTH_TOKEN:
                return True
        return False

    def send_login(self, error=False):
        body = LOGIN_PAGE.replace("%ERR%", '<p class="err">Неверный пароль.</p>' if error else "").encode()
        self.send_response(401 if error else 200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def redirect_home(self, set_cookie=False):
        self.send_response(303)
        self.send_header("Location", "/")
        if set_cookie:
            self.send_header("Set-Cookie", f"zs_auth={AUTH_TOKEN}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20000:
            raise ValueError("слишком большой запрос")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if PASSWORD and not self.authed():
            key = urllib.parse.parse_qs(qs).get("key", [""])[0]
            if key == PASSWORD:
                return self.redirect_home(set_cookie=True)
            if path.startswith("/api/"):
                return self.send_json({"error": "нужен пароль"}, 401)
            return self.send_login()
        if path in ("/", "/index.html"):
            body = (WEB / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self.send_json(snapshot())
        elif path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = hub.subscribe()
            try:
                self.wfile.write(b": hello\n\n")
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(b"data: " + data.encode() + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/login":
            n = min(int(self.headers.get("Content-Length") or 0), 2000)
            pw = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace")).get("password", [""])[0]
            if PASSWORD and pw == PASSWORD:
                return self.redirect_home(set_cookie=True)
            return self.send_login(error=True)
        if not self.authed():
            return self.send_json({"error": "нужен пароль"}, 401)
        try:
            body = self.read_json()
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        if path == "/api/say":
            text = str(body.get("text") or "").strip()[:1000]
            if not text:
                return self.send_json({"error": "пустое сообщение"}, 400)
            threading.Thread(target=chat, args=(text,), daemon=True).start()
            self.send_json({"ok": True})
        elif path == "/api/gift":
            wid = body.get("wish_id")
            st, err = give_gift(key=body.get("key"), name=body.get("name"), kind=body.get("kind"),
                                wish_id=int(wid) if str(wid or "").isdigit() else None)
            if err:
                return self.send_json({"error": err}, 400)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/wish/delete":
            wid = body.get("id")
            st = drop_wishes(None if body.get("all") else int(wid) if str(wid or "").isdigit() else -1)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/settings":
            err = apply_settings(body)
            if err:
                return self.send_json({"error": err}, 400)
            emit_event("system", "Настройки изменены: распорядок " + f"{wake_h()}:00–{sleep_h()}:00, голод ×{SETTINGS['hunger_rate']}, характер обновлён.")
            st = public_state()
            hub.publish({"type": "settings", "settings": SETTINGS, "wake_h": wake_h(), "sleep_h": sleep_h(), "state": st})
            self.send_json({"ok": True, "settings": SETTINGS, "state": st})
        elif path == "/api/poke":
            what = str(body.get("what") or "")
            if what not in POKES:
                return self.send_json({"error": "неизвестное воздействие"}, 400)
            st = poke(what)
            self.send_json({"ok": True, "state": st or public_state()})
        elif path == "/api/identity":
            name = re.sub(r"[^\w\s'-]", "", str(body.get("name") or ""), flags=re.U).strip()[:20]
            male = body.get("male")
            set_identity(None if male is None else bool(male), name or None)
            self.send_json({"ok": True, "state": public_state()})
        else:
            self.send_json({"error": "not found"}, 404)


def main():
    log(f"За стеклом: http://{HOST}:{PORT}  ·  {'пароль включён' if PASSWORD else 'без пароля'}  ·  бодрствует {wake_h()}:00–{sleep_h()}:00 {TZ}  ·  модели {MODEL_FAST}/{MODEL_DEEP}")
    try:
        log("claude:", claude_bin())
    except LLMError as e:
        log("ВНИМАНИЕ:", e)
    threading.Thread(target=mind_loop, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
