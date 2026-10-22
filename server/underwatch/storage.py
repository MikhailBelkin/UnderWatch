"""SQLite stores: one per resident (state, events, usage) and one for accounts, invites, sessions and shared drawings."""
import json
import secrets
import sqlite3
import threading
import time

from datetime import datetime

from .config import TZ


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
            CREATE TABLE IF NOT EXISTS sprites (id INTEGER PRIMARY KEY, key TEXT UNIQUE, svg TEXT, w REAL, h REAL, meta TEXT, ts REAL);
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
                            (time.time(), datetime.now(TZ).strftime("%Y-%m-%d"), purpose, model, tin, tout, cost, secs, 1 if ok else 0))
            self.db.commit()

    def usage_today(self):
        with self.lock:
            r = self.db.execute("SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost),0) FROM usage WHERE day=?",
                                (datetime.now(TZ).strftime("%Y-%m-%d"),)).fetchone()
            loc = self.db.execute("SELECT COUNT(*) FROM usage WHERE day=? AND model LIKE 'local:%'", (datetime.now(TZ).strftime("%Y-%m-%d"),)).fetchone()
            by = self.db.execute("SELECT purpose, COUNT(*) FROM usage WHERE day=? GROUP BY purpose", (datetime.now(TZ).strftime("%Y-%m-%d"),)).fetchall()
        return {"calls": r[0], "local_calls": loc[0], "input": r[1], "output": r[2], "cost": round(r[3], 4), "by": dict(by)}

    def sprite_by_key(self, key):
        with self.lock:
            r = self.db.execute("SELECT id, w, h, meta FROM sprites WHERE key=?", (key,)).fetchone()
        return {"id": r[0], "w": r[1], "h": r[2], "meta": json.loads(r[3] or "{}")} if r else None

    def add_sprite(self, key, svg, w, h, meta):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sprites (key, svg, w, h, meta, ts) VALUES (?,?,?,?,?,?)",
                            (key, svg, w, h, json.dumps(meta, ensure_ascii=False), time.time()))
            self.db.commit()
        return self.sprite_by_key(key)

    def sprite_svg(self, sid):
        with self.lock:
            r = self.db.execute("SELECT svg FROM sprites WHERE id=?", (sid,)).fetchone()
        return r[0] if r else None

    def forget_life(self):
        """New game: drop everything that happened and the resident's own memory. Settings, identity and usage stay."""
        with self.lock:
            self.db.execute("DELETE FROM events")
            self.db.execute("DELETE FROM kv WHERE k IN ('self_notes', 'guest_notes', 'day_memory', 'memory_upto')")
            self.db.commit()


class Accounts(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, login TEXT UNIQUE COLLATE NOCASE, pw TEXT, role TEXT, db TEXT, ts REAL, seen REAL);
                CREATE TABLE IF NOT EXISTS invites (code TEXT PRIMARY KEY, ts REAL, note TEXT, used_by INTEGER, used_ts REAL);
            """)
            self.db.commit()

    def users(self):
        with self.lock:
            rows = self.db.execute("SELECT id, login, pw, role, db, ts, seen FROM users ORDER BY id").fetchall()
        return [{"id": r[0], "login": r[1], "pw": json.loads(r[2] or "{}"), "role": r[3], "db": r[4], "ts": r[5], "seen": r[6]} for r in rows]

    def user(self, uid=None, login=None):
        return next((u for u in self.users() if (uid is not None and u["id"] == uid) or (login and u["login"].lower() == login.lower())), None)

    def add_user(self, login, pw, role, db):
        with self.lock:
            cur = self.db.execute("INSERT INTO users (login, pw, role, db, ts, seen) VALUES (?,?,?,?,?,?)", (login, json.dumps(pw), role, db, time.time(), time.time()))
            self.db.commit()
        return cur.lastrowid

    def set_pw(self, uid, pw):
        with self.lock:
            self.db.execute("UPDATE users SET pw=? WHERE id=?", (json.dumps(pw), uid))
            self.db.commit()

    def touch(self, uid):
        with self.lock:
            self.db.execute("UPDATE users SET seen=? WHERE id=?", (time.time(), uid))
            self.db.commit()

    def invites(self):
        with self.lock:
            rows = self.db.execute("SELECT code, ts, note, used_by, used_ts FROM invites ORDER BY ts DESC").fetchall()
        return [{"code": r[0], "ts": r[1], "note": r[2], "used_by": r[3], "used_ts": r[4]} for r in rows]

    def add_invite(self, note=""):
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        with self.lock:
            self.db.execute("INSERT INTO invites (code, ts, note) VALUES (?,?,?)", (code, time.time(), note[:60]))
            self.db.commit()
        return code

    def take_invite(self, code, uid):
        """Marks the code used; False if it doesn't exist or is gone."""
        with self.lock:
            cur = self.db.execute("UPDATE invites SET used_by=?, used_ts=? WHERE code=? AND used_by IS NULL", (uid, time.time(), code.strip().upper()))
            self.db.commit()
        return cur.rowcount == 1

    def invite_free(self, code):
        with self.lock:
            r = self.db.execute("SELECT used_by FROM invites WHERE code=?", (code.strip().upper(),)).fetchone()
        return bool(r) and r[0] is None

    def drop_invite(self, code):
        with self.lock:
            self.db.execute("DELETE FROM invites WHERE code=? AND used_by IS NULL", (code,))
            self.db.commit()
