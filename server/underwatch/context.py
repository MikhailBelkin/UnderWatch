"""Whose resident is this? The names S, store, SETTINGS, hub… stand for the resident of the current request or mind step."""
import contextvars
import json
import queue
import threading

from .config import DATA
from .storage import Accounts



# Every user has a resident of their own. The code below speaks of S, store, SETTINGS, hub… as if there were one;
# these names are stand-ins that resolve to the resident of the current request or mind step.
_cur = contextvars.ContextVar("resident")


def R():
    return _cur.get()


class _Here:
    """A stand-in for one attribute of the current resident."""
    __slots__ = ("_attr",)

    def __init__(self, attr):
        object.__setattr__(self, "_attr", attr)

    def _t(self):
        return getattr(_cur.get(), self._attr)

    def __getattr__(self, k): return getattr(self._t(), k)
    def __getitem__(self, k): return self._t()[k]
    def __setitem__(self, k, v): self._t()[k] = v
    def __delitem__(self, k): del self._t()[k]
    def __contains__(self, k): return k in self._t()
    def __iter__(self): return iter(self._t())
    def __len__(self): return len(self._t())
    def __bool__(self): return bool(self._t())
    def __enter__(self): return self._t().__enter__()
    def __exit__(self, *a): return self._t().__exit__(*a)


def spawn(fn, *args):
    """A background thread that keeps working on the same resident."""
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(fn,) + args, daemon=True).start()


def as_resident(r, fn, *args):
    tok = _cur.set(r)
    try:
        return fn(*args)
    finally:
        _cur.reset(tok)


store = _Here("store")

SETTINGS = _Here("settings")


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


hub = _Here("hub")


def emit_event(kind, text, data=None):
    ev = store.add_event(kind, text, data)
    hub.publish({"type": "event", "ev": ev})
    return ev


busy_lock = threading.Lock()   # one model call at a time, for all residents: there is one GPU

busy_what = _Here("busy")

world_epoch = _Here("epoch")  # bumped on a new game, so late answers from the old one are dropped


def set_busy(what):
    busy_what["v"] = what
    hub.publish({"type": "busy", "what": what})


state_lock = _Here("lock")

S = _Here("S")


def save_state():
    with state_lock:
        store.set("state", R().S)


def g(m, f):
    return m if S["male"] else f


memory_running = _Here("memory_running")

RESIDENTS = {}  # user id -> Resident

ACC = Accounts(DATA / "accounts.sqlite")  # accounts, invites, sessions, shared drawings


def admin_resident():
    return next(r for r in RESIDENTS.values() if r.admin)
