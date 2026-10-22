"""People: passwords, sessions, failed logins, invitations, registration, the owner's view, the passwd command."""
import hashlib
import hmac
import re
import secrets
import threading
import time

from .config import PASSWORD, log
from .passwords import PW_ITER, make_pw, pw_hash
from .context import as_resident, emit_event, ACC, RESIDENTS
from .life.prompts import REL_RU, REL_TEXT
from .passwords import make_pw
from .residents import Resident, create_resident


LEGACY_TOKEN = hashlib.sha256(("za-steklom:" + PASSWORD).encode()).hexdigest() if PASSWORD else ""  # old cookies, upgraded on sight

LOGIN_RX = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

NAME_RX = re.compile(r"^[^\W\d_][\w' -]{0,19}$")


def admin_view():
    users = []
    for u in ACC.users():
        r = RESIDENTS.get(u["id"])
        users.append({"login": u["login"], "admin": u["role"] == "admin", "name": r.S["name"] if r else "", "rel": REL_RU.get((r.meta if r else {}).get("rel", "romantic"), ""),
                      "ts": u["ts"], "seen": u["seen"]})
    logins = {u["id"]: u["login"] for u in ACC.users()}
    return {"users": users, "invites": [dict(i, used_login=logins.get(i["used_by"], "")) for i in ACC.invites()]}


SESSION_DAYS = 180

auth_lock = threading.Lock()

fails = {}  # client -> timestamps of failed logins


def password_on():
    return True  # every resident belongs to an account now


def check_password(uid, pw):
    u = ACC.user(uid=uid)
    if not u or not u["pw"].get("hash"):
        return False
    a = u["pw"]
    return hmac.compare_digest(pw_hash(pw, a["salt"], a.get("iter", PW_ITER)), a["hash"])


def set_password(uid, pw):
    """New password: every session made before this moment stops working (checked in session_user), so no shared list needs editing."""
    u = ACC.user(uid=uid)
    ACC.set_pw(uid, make_pw(pw))
    if u and u["role"] == "admin":
        ACC.set("legacy_ok", False)  # the old shared cookie dies with the old password


def token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()  # only hashes of session tokens are kept


def new_session(uid, who=""):
    token = secrets.token_urlsafe(32)
    with auth_lock:
        ses = ACC.get("sessions") or {}
        ses[token_key(token)] = {"uid": uid, "ts": time.time(), "seen": time.time(), "who": who[:120]}
        mine = sorted((k for k, v in ses.items() if v["uid"] == uid), key=lambda k: ses[k]["seen"])
        for k in mine[:-20]:  # at most 20 devices per person; the oldest go first
            del ses[k]
        ACC.set("sessions", ses)
    return token


def session_user(token):
    """The user id behind a session cookie, or None."""
    if not token:
        return None
    with auth_lock:
        ses = ACC.get("sessions") or {}
        s = ses.get(token_key(token))
        if not s or time.time() - s["seen"] > SESSION_DAYS * 86400 or s.get("uid") not in RESIDENTS:
            return None
        u = ACC.user(uid=s["uid"])
        if not u or s["ts"] < u["pw"].get("ts", 0):  # made before the last password change
            return None
        if time.time() - s["seen"] > 3600:  # sliding expiry, written at most hourly
            s["seen"] = time.time()
            ACC.set("sessions", ses)
            ACC.touch(s["uid"])
    return s["uid"]


def drop_sessions(uid, keep=None):
    with auth_lock:
        ses = ACC.get("sessions") or {}
        ACC.set("sessions", {k: v for k, v in ses.items() if v["uid"] != uid or (keep and k == token_key(keep))})


def too_many_fails(client):
    """5 wrong passwords from one place in 15 minutes, or 30 from anywhere, lock the door for a while."""
    now_ts = time.time()
    with auth_lock:
        for k in list(fails):
            fails[k] = [t for t in fails[k] if now_ts - t < 900]
            if not fails[k]:
                del fails[k]
        mine, total = fails.get(client, []), sum(len(v) for v in fails.values())
    if len(mine) >= 5:
        return int(900 - (now_ts - mine[0])) // 60 + 1
    if total >= 30:
        return 15
    return 0


def note_fail(client):
    with auth_lock:
        fails.setdefault(client, []).append(time.time())
    log("wrong password from", client)


def passwd_cli(login):
    """python3 server/app.py passwd <login> — set a password from the machine itself, when the web won't let you in."""
    import getpass
    u = ACC.user(login=login)
    if not u:
        print("нет такого пользователя:", login, "· есть:", ", ".join(x["login"] for x in ACC.users()))
        return 1
    a, b = getpass.getpass("Новый пароль: "), getpass.getpass("Ещё раз: ")
    if a != b or len(a) < 8:
        print("не совпадают или короче 8 символов — пароль не изменён")
        return 1
    set_password(u["id"], a)  # older sessions are refused from now on, even by the running server
    print(f"пароль для {u['login']} изменён; все его устройства вышли")
    return 0


def register(b, client, who):
    """A new account and a new resident, by invitation. Returns (http status, reply, session token or None)."""
    wait = too_many_fails(client)
    if wait:
        return 429, {"error": f"слишком много попыток, подождите {wait} мин."}, None
    code, login, pw = str(b.get("invite") or "").strip().upper(), str(b.get("login") or "").strip(), str(b.get("password") or "")
    c = b.get("character") if isinstance(b.get("character"), dict) else {}
    if not ACC.invite_free(code):
        note_fail(client)
        return 400, {"error": "такого приглашения нет или оно уже использовано"}, None
    err = None
    try:
        ch = {"male": bool(c.get("male", True)), "name": re.sub(r"\s+", " ", str(c.get("name") or "")).strip(),
              "age": int(c.get("age") or 27), "profession": str(c.get("profession") or "").strip()[:60],
              "interests": str(c.get("interests") or "").strip()[:200], "rel": str(c.get("rel") or ""),
              "talk": int(max(0, min(100, float(c.get("talk", 50))))), "traits": c.get("traits") if isinstance(c.get("traits"), dict) else {},
              "guest_name": re.sub(r"\s+", " ", str(b.get("guest_name") or "")).strip()[:30], "guest_male": bool(b.get("guest_male", True))}
    except (TypeError, ValueError):
        ch, err = {}, "неверные данные персонажа"
    if not err:
        err = ("логин: 3–32 латинских буквы, цифры, точка, дефис или подчёркивание" if not LOGIN_RX.match(login)
               else "такой логин уже занят" if ACC.user(login=login)
               else "пароль — не короче 8 символов" if len(pw) < 8
               else "как зовут жильца? (буквы, до 20 символов)" if not NAME_RX.match(ch["name"])
               else "возраст жильца — от 18 до 80" if not 18 <= ch["age"] <= 80
               else "выберите, кем жилец будет для вас" if ch["rel"] not in REL_TEXT
               else "романтический вариант — только для тех, кому есть 18" if ch["rel"] == "romantic" and not b.get("adult")
               else None)
    if err:
        return 400, {"error": err}, None
    if not ACC.take_invite(code, 0):  # claimed before anything is created, so a code can't be used twice
        return 400, {"error": "приглашение только что использовали"}, None
    uid = ACC.add_user(login, make_pw(pw), "user", "")
    db = create_resident(uid, login, ch)
    with ACC.lock:
        ACC.db.execute("UPDATE users SET db=? WHERE id=?", (db, uid))
        ACC.db.execute("UPDATE invites SET used_by=? WHERE code=?", (uid, code))
        ACC.db.commit()
    RESIDENTS[uid] = Resident(ACC.user(uid=uid))
    as_resident(RESIDENTS[uid], emit_event, "system", f"{ch['name']} въезжает в квартиру. Знакомьтесь!")
    log(f"new user «{login}» with resident {ch['name']} ({ch['rel']})")
    return 200, {"ok": True}, new_session(uid, who)
