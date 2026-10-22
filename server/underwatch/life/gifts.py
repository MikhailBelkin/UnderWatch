"""Gifts, wishes and the things in the flat: unwrapping, eating, using, pairing, taking back, drawing anew."""
import re
import time

from ..config import MODEL_FAST, log
from ..context import S, emit_event, g, hub, save_state, spawn, state_lock
from ..clock import is_awake_time
from ..brain import LLMError, llm
from . import bonds, drawings, emotions, needs, state


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

# actions that, given an item id, open, eat or use that gift (see gift_effects)
GIFT_ACTIONS = ("open_gift", "eat_treat", "use_item", "read_book", "music_on", "look_window", "cozy", "light_candle", "wear_item")


def guess_kind(name):
    low = name.lower()
    for kind, rx in KIND_WORDS:
        if re.search(rx, low):
            return kind
    return "other"


def find_item(item_id, states, edible=None):
    for it in S["items"]:
        if it["state"] not in states:
            continue
        if edible is not None and (it["kind"] in ("sweet", "drink")) != edible:
            continue
        if item_id is None or it["id"] == item_id:
            return it
    return None


USE_RULES = [(r"плед|одеял|покрывал", "cozy"), (r"свеч", "light"),
             (r"шарф|шапк|варежк|перчат|носк|свитер|кофт|худи|шал[ьи]|кардиган", "wear"), (r"мишк|игрушк|плюш|зайч|котик|единорог", "hug")]


def item_use(it):
    low = it["name"].lower()
    for rx, how in USE_RULES:
        if re.search(rx, low):
            return how
    return {"toy": "hug", "clothes": "wear"}.get(it["kind"], "admire")


def it_edible(it):
    return it["kind"] in ("sweet", "drink")


def resolve_gifts(actions):
    """Turn open_gift / eat_treat / use_item into concrete actions on real items; drop the impossible ones."""
    out, opened, used = [], set(), set()

    def pick(item_id, edible):
        # an item is usable if it's already open, or was unwrapped earlier in this same chain
        named = next((it for it in S["items"] if it["id"] == item_id and it["id"] not in used
                      and (it["state"] == "open" or (it["state"] == "wrapped" and it["id"] in opened))), None)
        if named and (not edible or it_edible(named)):
            return named  # asked for by id: a coffee pot is used, not drunk, whatever its kind
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
        if it.get("sprite"):
            info["sprite"] = it["sprite"]
        how = item_use(it) if d == "use_item" else None
        if d == "use_item" and it.get("sprite") and how not in ("cozy", "light", "wear"):
            mate = next((x for x in S["items"] if x["id"] == a.get("with") and x["id"] != it["id"] and x["state"] == "open"), None)
            use = dict(info, do="use_item", motion=a.get("motion") or it.get("motion") or "admire")
            for k in ("at", "put", "status", "label"):
                if a.get(k):
                    use[k] = a[k]
            if mate:
                use["with"] = mate["id"]
                used.add(mate["id"])
            out.append(use)
            continue
        if how == "cozy":
            out.append(dict(info, do="cozy"))
        elif how == "light":
            out.append(dict(info, do="light_candle"))
        elif how == "wear":
            out.append(dict(info, do="wear_item"))
        elif d == "use_item" and it["kind"] == "book":
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
        emotions.appraise("joy", 0.85 if it.get("wish") else 0.55)
        emotions.appraise("surprise", 0.4)
        emit_event("gift", f"Открыл{g('', 'а')} подарок: {it['name']}" + (" — то самое, что просил" + g("", "а") + "!" if it.get("wish") else "."), {"item": it})
    elif d == "eat_treat" and it["state"] == "open":
        it["state"] = "eaten"
        S["needs"]["hunger"] = needs.clampn(S["needs"]["hunger"] + (25 if it["kind"] == "sweet" else 12))
        S["needs"]["bladder"] = needs.clampn(S["needs"]["bladder"] - (8 if it["kind"] == "sweet" else 25))
        S["needs"]["fun"] = needs.clampn(S["needs"]["fun"] + needs.fun_gain(5))
        emotions.feel("joy", 0.35)
        emit_event("gift", f"Съел{g('', 'а')} {it['name']}.", {"item": it})
    elif d in ("use_item", "read_book", "music_on", "look_window", "cozy", "light_candle", "wear_item") and it["state"] == "open":
        if d == "light_candle":
            it["lit_ts"] = time.time()
        if d == "wear_item":
            S["accessory"] = {"id": it["id"], "name": it["name"]}
        if d == "use_item":
            mate = find_item(a.get("with"), ("open",)) if a.get("with") is not None else None
            for x in [it] + ([mate] if mate else []):
                if a.get("put"):
                    x["spot"] = a["put"]
                x["status"] = a.get("status") or ""
                x["paired"] = (mate["id"] if x is it else it["id"]) if mate and a.get("status") else None
        it["used"] = it.get("used", 0) + 1
        S["needs"]["fun"] = needs.clampn(S["needs"]["fun"] + needs.fun_gain(12))
        emotions.feel("joy", 0.3)


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
    hub.publish({"type": "state", "state": state.public_state()})


def give_gift(key=None, name=None, kind=None, wish_id=None):
    emotions.guest_here()
    bonds.grow_closeness(3.0 if wish_id is not None else 1.5, "gift")
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
        emotions.appraise("surprise", 0.45)
        emotions.appraise("joy", 0.5 if wish else 0.25)
        if is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [text]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = state.public_state()
    emit_event("world", text, {"by": "guest", "what": "gift", "guest": f"подарили: {name}", "item": it})
    hub.publish({"type": "world", "what": "gift", "text": text, "guest": f"подарили: {name}", "state": st})
    spawn(drawings.visualize_item, it["id"])
    return st, None


# everyday props a gift can replace, and the action that uses them
PROPS = {"pad": ("геймпад", "play_game"), "book": ("книга", "read_book"), "phone": ("телефон", "phone_call"), "cup": ("чашка", "drink"),
         "plate": ("тарелка", "eat"), "pen": ("ручка", "write_diary"), "note": ("блокнот", "write_diary"), "toothbrush": ("зубная щётка", "brush_teeth"), "comb": ("расчёска", "comb_hair")}

PROP_DOC = ("если эта вещь заменяет обычный предмет в бытовом действии — какой: " + ", ".join(f"{k} ({v[0]}, {v[1]})" for k, v in PROPS.items())
            + "; например, руль или джойстик для приставки — pad, кружка — cup, смартфон — phone; иначе none")


def classify_item(item_id):
    """Old gifts drawn before props existed: one short question to the fast model."""
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it or "prop" in it:
            return
        name = it["name"]
    try:
        r = llm("classify", MODEL_FAST, "Ты помогаешь игре понять, для чего вещь. Отвечай только JSON.",
                f"Вещь: «{name}». Ответ JSON: {{\"replaces\": \"{PROP_DOC}\", \"uses\": \"для чего это и как этим пользоваться, 1 предложение\"}}")
    except (LLMError, ValueError) as e:
        log("classify failed:", name, e)
        return
    with state_lock:
        it["prop"] = r.get("replaces") if r.get("replaces") in PROPS else ""
        if r.get("uses") and not it.get("uses"):
            it["uses"] = str(r["uses"])[:200]
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})


def classify_all():
    for it in list(S["items"]):
        if it["state"] == "open" and "prop" not in it:
            classify_item(it["id"])


def redrawing(item_id):
    return any(x["id"] == item_id and x.get("redraw") for x in S["items"])


def item_action(item_id, action, hint=""):
    """The guest takes a gift back, or asks for it to be drawn again."""
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it:
            return None
        if action == "remove":
            S["items"] = [x for x in S["items"] if x["id"] != item_id]
            for x in S["items"]:
                if x.get("paired") == item_id:
                    x["paired"], x["status"] = None, ""
            if (S.get("accessory") or {}).get("id") == item_id:
                S["accessory"] = None
            if is_awake_time():
                S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"Подарок «{it['name']}» вдруг исчез — кажется, гость забрал его."]
                S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        else:
            for k in ("sprite", "sw", "sh", "px"):
                it.pop(k, None)
            it["redraw"] = True
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})
    if action == "remove":
        emit_event("system", f"Гость убрал подарок: {it['name']}.")
    else:
        spawn(drawings.visualize_item, item_id, hint)
    return st


def drop_wishes(wish_id=None):
    with state_lock:
        S["wishes"] = [] if wish_id is None else [w for w in S["wishes"] if w["id"] != wish_id]
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})
    return st
