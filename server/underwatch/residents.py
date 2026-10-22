"""Residents: loading each user's flat, moving the old single-user flat in, creating one at registration, starting over."""
import json
import random
import secrets
import threading
import time

from .config import DATA, DB_PATH, OWNER_LOGIN, PASSWORD, log
from .storage import Store
from .passwords import PW_ITER, pw_hash
from .context import ACC, Hub, RESIDENTS, S, as_resident, busy_lock, emit_event, hub, save_state, set_busy, state_lock, store, world_epoch
from .settings import DEFAULT_SETTINGS, TRAITS
from .world import COLORS
from .life.bonds import guess_topic
from .life.gifts import classify_all
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


class Resident:
    """One user's resident: their own database, state, settings and live channel."""

    def __init__(self, user):
        self.uid, self.login, self.admin = user["id"], user["login"], user["role"] == "admin"
        self.store = Store(DATA / user["db"])
        self.lock = threading.RLock()
        self.hub = Hub()
        self.busy = {"v": None}
        self.epoch = {"v": 0}
        self.memory_running = threading.Event()
        st = self.store
        if st.get("identity") is None and st.get("self_notes"):
            st.set("identity", st.get("self_notes"))
        self.meta = st.get("meta") or {}  # relationship, talkativeness, age… chosen at registration
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        saved = st.get("settings") or {}
        self.settings.update({k: v for k, v in saved.items() if k != "traits"})
        self.settings["traits"].update(saved.get("traits") or {})
        S = dict(DEFAULT_STATE, **(st.get("state") or {}))
        S["needs"] = dict(DEFAULT_STATE["needs"], **S.get("needs", {}))
        if "light" in S:  # older state had one switch for the whole flat
            S["lights"] = {k: bool(S["light"]) for k in DEFAULT_STATE["lights"]}
            del S["light"]
        S["lights"] = dict(DEFAULT_STATE["lights"], **S.get("lights", {}))
        S["emo"] = dict(DEFAULT_STATE["emo"], **S.get("emo", {}))
        for f in S.get("guest_facts", []):  # facts saved before topics were recognised
            if f.get("topic") == "разное":
                f["topic"] = guess_topic(f["fact"])
        self.S = S


def boot():
    """Open the accounts, move the single-user flat in as the owner's, wake every resident."""
    (DATA / "residents").mkdir(exist_ok=True)
    if not ACC.users():
        old = Store(DB_PATH)
        pw = old.get("auth")
        if not pw:
            first = PASSWORD or secrets.token_urlsafe(9)
            if not PASSWORD:
                log("ВНИМАНИЕ: пароля не было; пароль владельца:", first)
            salt = secrets.token_hex(16)
            pw = {"salt": salt, "iter": PW_ITER, "hash": pw_hash(first, salt)}
        uid = ACC.add_user(OWNER_LOGIN, pw, "admin", DB_PATH.name)
        ACC.set("legacy_ok", not old.get("auth"))
        ACC.set("sessions", {k: dict(v, uid=uid) for k, v in (old.get("sessions") or {}).items()})  # devices already logged in stay in
        with old.lock:  # drawings move to the shared cache under the same ids
            rows = old.db.execute("SELECT id, key, svg, w, h, meta, ts FROM sprites").fetchall()
        with ACC.lock:
            ACC.db.executemany("INSERT OR IGNORE INTO sprites (id, key, svg, w, h, meta, ts) VALUES (?,?,?,?,?,?,?)", rows)
            ACC.db.commit()
        if old.get("brain_paused") is None and (old.get("state") or {}).get("mind_paused"):
            ACC.set("paused", True)
        old.db.close()
        log(f"single-user flat moved to the owner account «{OWNER_LOGIN}» ({len(rows)} drawings)")
    for u in ACC.users():
        RESIDENTS[u["id"]] = Resident(u)
    for r in RESIDENTS.values():
        if any(it["state"] == "open" and "prop" not in it for it in r.S["items"]):
            threading.Thread(target=as_resident, args=(r, classify_all), daemon=True).start()


REL_IDENTITY = {
    "romantic": "Гость мне очень нравится: между нами романтика, хотя мы только знакомимся.",
    "support": "Гость — мой близкий друг: я всегда за него и хочу знать, как у него дела.",
    "interests": "С гостем мы сошлись на общих увлечениях — с ним интересно.",
    "mentor": "С гостем мы вместе ставим цели и подтягиваем друг друга.",
}


def years(n):
    return "год" if n % 10 == 1 and n % 100 != 11 else "года" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "лет"


def create_resident(uid, login, c):
    """A new flat with a new resident, built from what the player chose at registration."""
    db = f"residents/{uid}.sqlite"
    st = Store(DATA / db)
    male, name, age = bool(c["male"]), c["name"], c["age"]
    a = (lambda m, f: m if male else f)
    prof = c.get("profession") or ""
    likes = c.get("interests") or ""
    identity = "\n".join(x for x in [
        f"- Мне {age} {years(age)}." + (f" Работаю: {prof}." if prof else ""),
        f"- Живу {a('один', 'одна')} в небольшой квартире.",
        f"- Люблю: {likes}." if likes else "",
        "- " + REL_IDENTITY[c["rel"]],
    ] if x)
    st.set("identity", identity)
    st.set("self_notes", f"- Недавно {a('переехал', 'переехала')} в эту квартиру и потихоньку обустраиваюсь." + (f"\n- Хочу больше времени на то, что люблю: {likes}." if likes else ""))
    traits = {k: int(max(0, min(100, float(c["traits"].get(k, TRAITS[k][2]))))) for k in TRAITS}
    st.set("settings", {"wake": 9, "sleep": 23, "hunger_rate": 1.0, "traits": traits, "look": c.get("look") or {}})  # people visit after work: awake into the evening
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(name=name, male=male, outfit={"type": "casual", "color": random.choice(list(COLORS))})
    st.set("state", state)
    st.set("meta", {"rel": c["rel"], "talk": c["talk"], "age": age, "profession": prof, "interests": likes,
                    "guest_name": c.get("guest_name") or "", "guest_male": c.get("guest_male", True), "created": time.time()})
    st.db.close()
    return db
