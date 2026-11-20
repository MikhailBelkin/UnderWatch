"""Residents: loading each user's ship, moving the old flats on board, creating one at registration, starting over."""
import json
import random
import secrets
import sqlite3
import threading
import time

from .config import DATA, DB_PATH, OWNER_LOGIN, PASSWORD, log
from .storage import Store
from .passwords import make_pw
from .context import ACC, Hub, RESIDENTS, S, busy_lock, emit_event, hub, save_state, set_busy, state_lock, store, world_epoch
from .settings import DEFAULT_SETTINGS, TRAITS
from .world import COLORS
from .life.state import DEFAULT_STATE, identity


def new_game():
    """Start over: the resident forgets the guest, the days, gifts and goals. Name, identity, character and schedule stay."""
    with busy_lock:  # let a model call in flight finish, so its answer doesn't land in the new world
        set_busy("reset")
        try:
            with state_lock:
                keep = {"name": S["name"], "male": S["male"]}
                S.clear()
                S.update(json.loads(json.dumps(DEFAULT_STATE)), **keep)
                S["last_tick"] = S["reflect_ts"] = time.time()
                world_epoch["v"] += 1
                store.forget_life()
                save_state()
        finally:
            set_busy(None)
    log("new game")
    emit_event("system", "Игра начата заново.")
    hub.publish({"type": "reset"})


def SHIP_LINE(male):
    return (f"- Я {'астронавт' if male else 'астронавтка'}: лечу {'один' if male else 'одна'} на корабле «Странник» к Проксиме Центавра. "
            "Всё, что сказано обо мне ниже, — моя жизнь на Земле до полёта.")


def move_to_ship(r):
    """The flat became the ship «Странник» (November 2026): the resident's life starts over on board.
    Name, character, looks, the player's identity and what she knows about the guest (notes, facts, closeness) stay;
    the diary, the feed, self-notes, gifts, wishes and goals go. The old database is copied to data/backup first."""
    st = r.store
    if st.get("world") == "ship":
        return
    backup = DATA / "backup"
    backup.mkdir(exist_ok=True)
    dest = sqlite3.connect(backup / f"{r.login}-flat-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")
    with st.lock:
        st.db.backup(dest)
    dest.close()
    old, male = r.S, r.S["male"]
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update({k: old[k] for k in ("name", "male", "guest_facts", "closeness", "closeness_day", "closeness_today") if k in old})
    color = (old.get("outfit") or {}).get("color") if isinstance(old.get("outfit"), dict) else old.get("outfit")
    state["outfit"] = {"type": "casual", "color": color if color in COLORS else random.choice(list(COLORS))}
    state["last_tick"] = state["reflect_ts"] = time.time()
    r.S.clear()
    r.S.update(state)
    st.set("state", state)
    with st.lock:
        st.db.execute("DELETE FROM events")
        st.db.execute("DELETE FROM kv WHERE k IN ('self_notes', 'day_memory', 'memory_upto')")
        st.db.commit()
    lines = [l for l in (st.get("identity") or "").splitlines() if "квартир" not in l]
    st.set("identity", "\n".join([SHIP_LINE(male)] + lines))
    st.set("world", "ship")
    st.add_event("system", f"Квартира осталась на Земле: {state['name']} теперь летит на «Страннике» к Проксиме Центавра. "
                           f"Жизнь на борту начинается заново, но всё, что {'он' if male else 'она'} знал{'' if male else 'а'} о вас, — с {'ним' if male else 'ней'}.")
    log(f"{r.login}: moved on board the ship (backup in data/backup)")


class Resident:
    """One user's resident: their own database, state, settings and live channel."""

    def __init__(self, user):
        self.uid, self.login, self.admin = user["id"], user["login"], user["role"] == "admin"
        self.guest_seen = user["seen"] or user["ts"] or time.time()  # the guest's last request, kept fresh by the sessions
        self.store = Store(DATA / user["db"])
        self.lock = threading.RLock()
        self.hub = Hub()
        self.busy = {"v": None}
        self.epoch = {"v": 0}
        self.memory_running = threading.Event()
        st = self.store
        self.meta = st.get("meta") or {}  # relationship, talkativeness, age… chosen at registration
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        saved = st.get("settings") or {}
        self.settings.update({k: v for k, v in saved.items() if k != "traits"})
        self.settings["traits"].update(saved.get("traits") or {})
        S = dict(DEFAULT_STATE, **(st.get("state") or {}))
        S["needs"] = dict(DEFAULT_STATE["needs"], **S.get("needs", {}))
        S["lights"] = {k: S.get("lights", {}).get(k, v) for k, v in DEFAULT_STATE["lights"].items()}
        S["emo"] = dict(DEFAULT_STATE["emo"], **S.get("emo", {}))
        self.S = S


def boot():
    """Wake every resident. On a fresh install the owner's account comes first: its flat is data/mind.sqlite,
    its password PASSWORD (or a random one, printed to the log)."""
    (DATA / "residents").mkdir(exist_ok=True)
    if not ACC.users():
        first = PASSWORD or secrets.token_urlsafe(9)
        if not PASSWORD:
            log("ВНИМАНИЕ: PASSWORD не задан; пароль владельца:", first)
        ACC.add_user(OWNER_LOGIN, make_pw(first), "admin", DB_PATH.name)
        log(f"owner account «{OWNER_LOGIN}» created")
    for u in ACC.users():
        RESIDENTS[u["id"]] = Resident(u)
        move_to_ship(RESIDENTS[u["id"]])


REL_IDENTITY = {
    "romantic": "Гость мне очень нравится: между нами романтика, хотя мы только знакомимся.",
    "support": "Гость — мой близкий друг: я всегда за него и хочу знать, как у него дела.",
    "interests": "С гостем мы сошлись на общих увлечениях — с ним интересно.",
    "mentor": "С гостем мы вместе ставим цели и подтягиваем друг друга.",
}


def years(n):
    return "год" if n % 10 == 1 and n % 100 != 11 else "года" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "лет"


def create_resident(uid, login, c):
    """A new ship with a new resident, built from what the player chose at registration."""
    db = f"residents/{uid}.sqlite"
    st = Store(DATA / db)
    male, name, age = bool(c["male"]), c["name"], c["age"]
    a = (lambda m, f: m if male else f)
    prof = c.get("profession") or ""
    likes = c.get("interests") or ""
    identity = "\n".join(x for x in [
        f"- Мне {age} {years(age)}." + (f" Работаю: {prof}." if prof else ""),
        SHIP_LINE(male),
        f"- Люблю: {likes}." if likes else "",
        "- " + REL_IDENTITY[c["rel"]],
    ] if x)
    st.set("identity", identity)
    st.set("self_notes", "- Полёт только начался: обживаю корабль и привыкаю к звёздам за иллюминатором." + (f"\n- Хочу больше времени на то, что люблю: {likes}." if likes else ""))
    st.set("world", "ship")
    traits = {k: int(max(0, min(100, float(c["traits"].get(k, TRAITS[k][2]))))) for k in TRAITS}
    st.set("settings", {"wake": 9, "sleep": 23, "hunger_rate": 1.0, "traits": traits, "look": c.get("look") or {}})  # people visit after work: awake into the evening
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(name=name, male=male, outfit={"type": "casual", "color": random.choice(list(COLORS))})
    st.set("state", state)
    st.set("meta", {"rel": c["rel"], "talk": c["talk"], "age": age, "profession": prof, "interests": likes,
                    "guest_name": c.get("guest_name") or "", "guest_male": c.get("guest_male", True), "created": time.time()})
    st.db.close()
    return db
