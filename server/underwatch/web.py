"""The HTTP side: pages, the JSON/SSE API, HTTPS on the same port as a plain-http redirect."""
import hmac
import json
import queue
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import HOST, MODEL_DEEP, MODEL_FAST, PORT, TLS_DIR, TZ, WEB, log
from .context import ACC, R, RESIDENTS, S, SETTINGS, _cur, admin_resident, busy_what, emit_event, hub, save_state, spawn, state_lock, store
from .settings import apply_settings, sleep_h, wake_h
from .world import TOGETHER
from .brain import LLMError, brain, claude_bin, loaded_models, local_models, mind_paused, set_paused
from .accounts import register as register_user, LEGACY_TOKEN, SESSION_DAYS, admin_view, auth_lock, check_password, drop_sessions, new_session, note_fail, session_user, set_password, token_key, too_many_fails
from .life.drawings import drop_visitor
from .life.gifts import drop_wishes, give_gift, item_action
from .life.goals import set_goal_from_text
from .life.guest import POKES, invite, poke, poke_custom, set_identity
from .life.mind import chat, mind_loop
from .life.state import notes, public_state
from .residents import boot, new_game


def page_version():
    try:
        st = (WEB / "index.html").stat()
        return f"{int(st.st_mtime)}-{st.st_size}-{int(Path(__file__).stat().st_mtime)}"
    except OSError:
        return "0"


SERVER_STARTED = str(int(time.time()))


def snapshot():
    return {
        "version": page_version() + "-" + SERVER_STARTED,
        "state": public_state(), "now": time.time(), "tz": str(TZ), "brain": brain(), "wake_h": wake_h(), "sleep_h": sleep_h(), "settings": R().settings,
        "chat": store.events(["chat_user", "chat_reply", "aloud"], limit=40),
        "feed": store.events(["thought", "action", "aloud", "plan", "note", "system", "world", "gift", "wish", "learned", "goal", "practice", "milestone"], limit=40),
        "diary": store.events(["diary"], limit=10),
        "notes": notes(), "usage": store.usage_today(), "auth": {"on": True},
        "me": {"login": R().login, "admin": R().admin}, "rel": R().meta.get("rel", "romantic"),
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
</style></head><body><form method="post" action="/login"><h1>За стеклом</h1><p>Войдите, чтобы заглянуть в свою квартиру.</p>%ERR%
<input name="login" autofocus autocomplete="username" aria-label="Логин" placeholder="логин" required autocapitalize="none" spellcheck="false">
<input type="password" name="password" autocomplete="current-password" aria-label="Пароль" placeholder="пароль" required><button>Войти</button>
<p>Есть приглашение? <a href="/register">Заведите своего жильца</a>.</p></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ZaSteklom/1.0"
    timeout = 60  # a client that sends nothing for a minute is dropped (slow-request attacks)
    upgrade_cookie = None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        if self.https():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if self.upgrade_cookie:
            self.send_header("Set-Cookie", self.cookie_header(self.upgrade_cookie))
            self.upgrade_cookie = None
        super().end_headers()

    def https(self):
        return TLS["on"] or (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def client(self):
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1"):  # behind a local tunnel or proxy, the real address comes in a header
            ip = (self.headers.get("CF-Connecting-IP") or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or ip)
        return ip

    def cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "zs_auth":
                return v
        return ""

    def cookie_header(self, token, max_age=SESSION_DAYS * 86400):
        return f"zs_auth={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if self.https() else "")

    def who(self):
        return self.client() + " " + (self.headers.get("User-Agent") or "")

    def authed(self):
        """Finds the user behind the cookie and makes their resident the one this request talks about."""
        c = self.cookie()
        uid = session_user(c)
        if uid is None and c and LEGACY_TOKEN and ACC.get("legacy_ok") and hmac.compare_digest(c, LEGACY_TOKEN):
            uid = admin_resident().uid
            self.upgrade_cookie = new_session(uid, self.who())  # the old shared cookie becomes the owner's own session
        if uid is None:
            return False
        self.uid = uid
        _cur.set(RESIDENTS[uid])
        return True

    def send_login(self, error="", code=200):
        body = LOGIN_PAGE.replace("%ERR%", f'<p class="err">{error}</p>' if error else "").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def redirect_home(self, token=None, logout=False):
        self.send_response(303)
        self.send_header("Location", "/")
        if token:
            self.send_header("Set-Cookie", self.cookie_header(token))
        if logout:
            self.send_header("Set-Cookie", self.cookie_header("", 0))
        self.end_headers()

    def register(self):
        """A new account and a new resident, by invitation (see accounts.register)."""
        try:
            b = self.read_json()
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        code, payload, token = register_user(b, self.client(), self.who())
        if token:
            self.upgrade_cookie = token
        self.send_json(payload, code)

    def send_file(self, path, ctype):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        if path in ("/register", "/register.html"):
            return self.send_file(WEB / "register.html", "text/html; charset=utf-8")
        if not self.authed():
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
        elif path == "/api/admin":
            if not R().admin:
                return self.send_json({"error": "только для владельца"}, 403)
            self.send_json(admin_view())
        elif path == "/api/models":
            self.send_json({"local": local_models(), "brain": brain(), "loaded": loaded_models(), "paused": bool(mind_paused())})
        elif path == "/api/version":
            self.send_json({"version": page_version() + "-" + SERVER_STARTED})
        elif path == "/api/state":
            self.send_json(snapshot())
        elif path.startswith("/api/sprite/"):
            svg = ACC.sprite_svg(int(path.rsplit("/", 1)[1].split(".")[0])) if path.rsplit("/", 1)[1].split(".")[0].isdigit() else None
            if not svg:
                return self.send_json({"error": "not found"}, 404)
            body = svg.encode()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=31536000, immutable")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)
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
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
            login, pw = form.get("login", [""])[0].strip(), form.get("password", [""])[0]
            wait = too_many_fails(self.client())
            if wait:
                return self.send_login(f"Слишком много неудачных попыток. Попробуйте через {wait} мин.", 429)
            u = ACC.user(login=login) if login else None
            if u and check_password(u["id"], pw):
                ACC.touch(u["id"])
                return self.redirect_home(token=new_session(u["id"], self.who()))
            note_fail(self.client())
            return self.send_login("Неверный логин или пароль.", 401)
        if path == "/api/register":
            return self.register()
        if path == "/logout":
            c = self.cookie()
            if c:
                with auth_lock:
                    ses = ACC.get("sessions") or {}
                    ses.pop(token_key(c), None)
                    ACC.set("sessions", ses)
            return self.redirect_home(logout=True)
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
            spawn(chat, text)
            self.send_json({"ok": True})
        elif path == "/api/gift":
            wid = body.get("wish_id")
            st, err = give_gift(key=body.get("key"), name=body.get("name"), kind=body.get("kind"),
                                wish_id=int(wid) if str(wid or "").isdigit() else None)
            if err:
                return self.send_json({"error": err}, 400)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/mind":
            if not R().admin:
                return self.send_json({"error": "только для владельца"}, 403)
            set_paused(body.get("action") == "stop")
            self.send_json({"ok": True, "state": public_state(), "loaded": loaded_models()})
        elif path == "/api/goal":
            text = str(body.get("text") or "").strip()[:200]
            if body.get("cancel"):
                with state_lock:
                    old = S.get("goal")
                    S["goal"] = None
                    save_state()
                if old:
                    emit_event("goal", f"Цель отменена: {old['title']}")
                hub.publish({"type": "state", "state": public_state()})
                return self.send_json({"ok": True, "state": public_state()})
            if len(text) < 3:
                return self.send_json({"error": "напишите цель"}, 400)
            spawn(set_goal_from_text, text, "guest")
            self.send_json({"ok": True})
        elif path == "/api/invite":
            kind = str(body.get("kind") or "")
            if kind not in TOGETHER and kind != "end":
                return self.send_json({"error": "неизвестное приглашение"}, 400)
            self.send_json({"ok": True, "state": invite(kind, body.get("text"))})
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
            hub.publish({"type": "settings", "settings": R().settings, "wake_h": wake_h(), "sleep_h": sleep_h(), "state": st})
            self.send_json({"ok": True, "settings": R().settings, "state": st})
        elif path == "/api/poke" and body.get("what") in ("custom_world", "custom_touch"):
            st = poke_custom("world" if body["what"] == "custom_world" else "touch", body.get("text"))
            if not st:
                return self.send_json({"error": "опишите, что сделать"}, 400)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/persona":
            for key in ("identity", "self_notes", "guest_notes"):
                if key in body:
                    store.set(key, str(body.get(key) or "").strip()[:4000])
            emit_event("system", "Личность и память персонажа отредактированы в настройках.")
            hub.publish({"type": "notes", "notes": notes(), "diary": store.events(["diary"], limit=10)})
            self.send_json({"ok": True, "notes": notes()})
        elif path == "/api/poke":
            what = str(body.get("what") or "")
            if what not in POKES:
                return self.send_json({"error": "неизвестное воздействие"}, 400)
            st = poke(what)
            self.send_json({"ok": True, "state": st or public_state()})
        elif path == "/api/reset":
            if body.get("sure") is not True:
                return self.send_json({"error": "нужно подтвердить, что вы хотите начать заново"}, 400)
            waiting = busy_what["v"]
            spawn(new_game)
            self.send_json({"ok": True, "waiting": waiting})
        elif path == "/api/password":
            wait = too_many_fails(self.client())
            if wait:
                return self.send_json({"error": f"слишком много неудачных попыток, подождите {wait} мин."}, 429)
            new = str(body.get("new") or "")
            if not check_password(self.uid, str(body.get("current") or "")):
                note_fail(self.client())
                return self.send_json({"error": "текущий пароль неверный"}, 400)
            if len(new) < 8:
                return self.send_json({"error": "новый пароль — не короче 8 символов"}, 400)
            set_password(self.uid, new)
            token = new_session(self.uid, self.who())
            drop_sessions(self.uid, keep=token)  # every other device has to log in again
            self.upgrade_cookie = token
            emit_event("system", "Пароль изменён; все остальные устройства вышли.")
            log("password changed")
            self.send_json({"ok": True})
        elif path == "/api/admin":
            if not R().admin:
                return self.send_json({"error": "только для владельца"}, 403)
            if body.get("action") == "invite":
                ACC.add_invite(str(body.get("note") or ""))
            elif body.get("action") == "drop_invite":
                ACC.drop_invite(str(body.get("code") or ""))
            self.send_json(admin_view())
        elif path == "/api/item":
            iid, action = body.get("id"), body.get("action")
            if action not in ("remove", "redraw") or not str(iid or "").isdigit():
                return self.send_json({"error": "неизвестное действие"}, 400)
            st = item_action(int(iid), action, re.sub(r"\s+", " ", str(body.get("hint") or "")).strip()[:200])
            if not st:
                return self.send_json({"error": "такого подарка уже нет"}, 400)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/visitor":
            vid = body.get("id")
            st = drop_visitor(int(vid), by_guest=True) if str(vid or "").isdigit() else None
            if not st:
                return self.send_json({"error": "этого уже нет"}, 400)
            self.send_json({"ok": True, "state": st})
        elif path == "/api/identity":
            name = re.sub(r"[^\w\s'-]", "", str(body.get("name") or ""), flags=re.U).strip()[:20]
            male = body.get("male")
            set_identity(None if male is None else bool(male), name or None)
            self.send_json({"ok": True, "state": public_state()})
        else:
            self.send_json({"error": "not found"}, 404)


TLS = {"on": False}


class PlainRedirect(BaseHTTPRequestHandler):
    """Plain http on the https port, any method: read the request (so closing doesn't reset the connection) and point to https.
    307 keeps the method and the body and isn't cached for good, unlike 301."""
    timeout = 15

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        self.raw_requestline = self.rfile.readline(65537)
        if not self.raw_requestline or not self.parse_request():
            self.close_connection = True
            return
        try:
            left = min(int(self.headers.get("Content-Length") or 0), 65536)
        except ValueError:
            left = 0
        while left > 0:
            chunk = self.rfile.read(min(left, 8192))
            if not chunk:
                break
            left -= len(chunk)
        host = (self.headers.get("Host") or f"localhost:{PORT}").strip()
        self.send_response(307)
        self.send_header("Location", f"https://{host}{self.path}")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    tls_ctx = None

    def finish_request(self, request, client_address):
        """One port for both: a TLS hello gets HTTPS, plain HTTP gets a redirect to it (old bookmarks, typed addresses)."""
        if self.tls_ctx:
            request.settimeout(15)
            try:
                first = request.recv(1, socket.MSG_PEEK)
            except OSError:
                return
            if first != b"\x16":  # not a TLS handshake record: plain http
                PlainRedirect(request, client_address, self)
                return
            try:
                request = self.tls_ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError):
                return
        try:
            self.RequestHandlerClass(request, client_address, self)
        finally:
            if isinstance(request, ssl.SSLSocket):  # the original socket is detached; close the TLS one the way socketserver would
                try:
                    request.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                try:
                    request.close()
                except OSError:
                    pass

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError, OSError)):
            return  # plain http on the https port, dropped connections, scanners: not worth a traceback
        super().handle_error(request, client_address)


def main():
    boot()
    admin = admin_resident()
    cert, key = TLS_DIR / "cert.pem", TLS_DIR / "key.pem"
    TLS["on"] = cert.exists() and key.exists()
    log(f"За стеклом: {'https' if TLS['on'] else 'http'}://{HOST}:{PORT}  ·  пользователей: {len(RESIDENTS)}  ·  владелец: {admin.login}  ·  модели {MODEL_FAST}/{MODEL_DEEP}")
    try:
        log("claude:", claude_bin())
    except LLMError as e:
        log("ВНИМАНИЕ:", e)
    spawn(mind_loop)
    srv = Server((HOST, PORT), Handler)
    if TLS["on"]:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        srv.tls_ctx = ctx  # each connection is sorted out in its own thread (see Server.finish_request)
    srv.serve_forever()
