"""Drawings made on the fly: gifts and the guest's creatures as SVG, and the creatures' life in the flat."""
import re
import time

from ..config import MODEL_DEEP, log
from ..context import ACC, S, hub, save_state, state_lock, world_epoch
from ..clock import is_awake_time
from ..world import MOTIONS, ROOMS, SPOTS
from ..brain import LLMError, llm
from . import gifts, state


SVG_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}

SVG_SYS = ("Ты художник и геймдизайнер маленькой 2D-игры: квартира в разрезе в плоском векторном стиле (flat), "
           "у предмета 3–6 цветов, без градиентов, без текста, вид сбоку или спереди. Отвечай только JSON.")

SVG_RULES = ("SVG: viewBox по размеру рисунка (например \"0 0 48 64\"), прозрачный фон, только теги svg, g, path, rect, circle, ellipse, polygon, polyline, line; "
             "без script, image, style, текста и внешних ссылок, цвета — атрибутами fill/stroke; до 3000 символов; нижний край рисунка — нижний край viewBox.")


def clean_svg(raw):
    """Keep only plain shapes; returns (svg, width, height) or None."""
    svg = str(raw or "").strip()
    m = re.search(r"<svg\b.*?</svg>", svg, re.S | re.I)
    if not m or len(m.group(0)) > 12000:
        return None
    svg = m.group(0)
    for tag in re.findall(r"<\s*/?\s*([a-zA-Z][\w:-]*)", svg):
        if tag.lower() not in SVG_TAGS:
            return None
    if re.search(r"\bon\w+\s*=|javascript:|href|url\s*\(|<!|&\w", svg, re.I):
        return None
    vb = re.search(r'viewBox\s*=\s*["\']\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)', svg)
    if not vb:
        return None
    w, h = float(vb.group(3)), float(vb.group(4))
    if not (1 <= w <= 2000 and 1 <= h <= 2000):
        return None
    head = re.match(r"<svg\b[^>]*>", svg).group(0)
    attrs = re.sub(r'\s(xmlns|width|height)\s*=\s*(["\']).*?\2', "", head[4:-1])
    head = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}"{attrs}>'  # images need a size to be drawn on canvas
    return head + svg[len(re.match(r"<svg\b[^>]*>", svg).group(0)):], w, h


def sprite_key(kind, name):
    return kind + ":" + re.sub(r"\s+", " ", name.lower()).strip(" .!«»\"'")[:80]


def draw_sprite(key, prompt):
    """Ask the deep model for a drawing plus what it means; cached by key."""
    known = ACC.sprite_by_key(key)
    if known:
        return known
    r = llm("draw", MODEL_DEEP, SVG_SYS, prompt)
    meta = {k: v for k, v in r.items() if k != "svg"}
    got = clean_svg(r.get("svg")) if r.get("visible") else None
    if r.get("visible") and not got:
        log("drawing rejected:", key, str(r.get("svg"))[:200])
    svg, w, h = got or ("", 0, 0)
    return ACC.add_sprite(key, svg, w, h, meta)


def spot_or(v, default):
    return v if v in SPOTS else default


def visualize_item(item_id, hint=""):
    epoch = world_epoch["v"]
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it or it.get("sprite"):
            return
        others = ", ".join(f"{x['name']} (id={x['id']})" for x in S["items"] if x["id"] != item_id and x["state"] != "eaten") or "ничего"
        name, kind = it["name"], it["kind"]
    redo = f"\nЭто перерисовка: прошлый рисунок не устроил гостя. Его подсказка: {hint}" if hint else ""
    prompt = f"""Гость дарит жильцу квартиры подарок: «{name}» (тип: {gifts.KIND_RU.get(kind, 'вещь')}).{redo}
Подаренные раньше вещи: {others}.
1. Можно ли показать это маленьким рисунком в квартире? Нельзя (visible=false), если это слишком большое (мебель, машина), абстрактное (поездка, любовь, деньги, подписка), непонятное или то, что не узнать в маленьком рисунке.
2. Если можно — нарисуй. {SVG_RULES}
3. Куда это естественно поставить (spot): {"; ".join(f"{k} — {v}" for k, v in SPOTS.items())}.
Ответ JSON: {{"visible": true или false, "svg": "<svg ...>...</svg>" или "", "height_cm": реальная высота в см, "spot": "...", "uses": "для чего это и как этим пользоваться, 1 предложение", "works_with": "с какими из подаренных раньше вещей это работает вместе и как (с id), или пусто", "motion": "как выглядит использование: {'|'.join(MOTIONS)}", "kind": "что это: {'|'.join(gifts.GIFT_KINDS)} (sweet и drink — только то, что едят и пьют; посуда — decor или other)", "replaces": "{gifts.PROP_DOC}"}}"""
    try:
        sp = draw_sprite(sprite_key("item", name) + (f"|{hint}|{time.time():.0f}" if hint is not None and hint != "" or gifts.redrawing(item_id) else ""), prompt)
    except (LLMError, ValueError) as e:
        log("gift drawing failed:", name, e)
        return
    meta = sp["meta"]
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it or epoch != world_epoch["v"]:
            return
        it.pop("redraw", None)
        if hint:
            it["spot"] = spot_or(meta.get("spot"), it.get("spot") or "shelf")  # a new drawing may belong elsewhere
        it["uses"] = str(meta.get("uses") or "")[:200]
        it["works_with"] = str(meta.get("works_with") or "")[:200]
        it["motion"] = meta.get("motion") if meta.get("motion") in MOTIONS else "admire"
        it["prop"] = meta.get("replaces") if meta.get("replaces") in gifts.PROPS else ""
        if meta.get("kind") in gifts.GIFT_KINDS and it["kind"] != "flowers":
            it["kind"] = meta["kind"]
        it.setdefault("spot", spot_or(meta.get("spot"), "shelf"))
        if sp["h"]:
            cm = max(1.0, min(200.0, float(meta.get("height_cm") or 15)))
            it.update(sprite=sp["id"], sw=sp["w"], sh=sp["h"], px=round(max(12, min(110, cm * 1.4))))  # a bit larger than life, or a phone is 10 px
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})


BEHAVIORS = ("fly", "crawl", "walk", "hop", "wall", "perch", "static")


def visualize_world(text):
    """Something the guest made up: if it's a thing or a creature, draw it and let it live in the flat."""
    epoch = world_epoch["v"]
    prompt = f"""Гость вмешался в мир квартиры: «{text}».
Покажи это, только если в квартире появился конкретный предмет или существо (птица, кот, паук, мышь, мяч, воздушный шарик, письмо). Погоду, звуки, запахи, свет, чувства и события без нового предмета не показывай (visible=false). Если существ несколько — нарисуй одно, а сколько их — в count.
{SVG_RULES} Существо рисуй в профиль, головой в сторону facing.
Ответ JSON: {{"visible": true или false, "name": "коротко, что это (например «синица»)", "svg": "<svg ...>...</svg>" или "", "height_cm": реальная высота в см, "facing": "left" или "right", "behavior": "fly — летает | crawl — ползает по полу | walk — бегает по полу | hop — прыгает по полу | wall — ползает по стене | perch — сидит на месте и шевелится | static — предмет, просто лежит/стоит", "room": "bedroom|living|kitchen|bathroom", "spot": "для perch и static — где: {'|'.join(SPOTS)}", "count": 1–6, "enter": "window — влетает в окно | door — входит из прихожей | appear — просто появляется", "stays_min": "через сколько минут уйдёт само (0 — пока не выгонят)"}}"""
    try:
        sp = draw_sprite(sprite_key("world", text), prompt)
    except (LLMError, ValueError) as e:
        log("event drawing failed:", text[:80], e)
        return
    meta = sp["meta"]
    if not sp["h"] or epoch != world_epoch["v"]:
        return
    try:
        stays = max(0, min(600, int(float(meta.get("stays_min") or 0))))
        count = max(1, min(6, int(meta.get("count") or 1)))
        cm = max(0.5, min(150.0, float(meta.get("height_cm") or 10)))
    except (TypeError, ValueError):
        stays, count, cm = 0, 1, 10.0
    behavior = meta.get("behavior") if meta.get("behavior") in BEHAVIORS else "static"
    small = behavior != "static"
    with state_lock:
        v = {"id": S["next_id"], "name": str(meta.get("name") or text)[:40], "sprite": sp["id"], "sw": sp["w"], "sh": sp["h"],
             "px": round(max(12, min(70 if small else 110, cm * (2.0 if small else 1.4)))),
             "facing": "left" if meta.get("facing") == "left" else "right", "behavior": behavior,
             "room": meta.get("room") if meta.get("room") in ROOMS and meta.get("room") != "all" else "living",
             "spot": spot_or(meta.get("spot"), "floor"), "count": count,
             "enter": meta.get("enter") if meta.get("enter") in ("window", "door", "appear") else "appear",
             "since": time.time(), "until": time.time() + stays * 60 if stays else 0}
        S["next_id"] += 1
        S["visitors"] = (S["visitors"] + [v])[-8:]
        if is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"Теперь в квартире: {v['name']}" + (f" ×{count}" if count > 1 else "") + f" (id={v['id']}). Если мешает — можно выгнать: shoo{{{v['id']}}}."]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})


def drop_visitor(vid, by_guest=False):
    with state_lock:
        v = next((x for x in S["visitors"] if x["id"] == vid), None)
        if not v:
            return None
        S["visitors"] = [x for x in S["visitors"] if x["id"] != vid]
        if by_guest and is_awake_time():
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"{v['name'].capitalize()} вдруг исчез(ла) из квартиры — кажется, гость убрал."]
            S["react_at"] = max(time.time() + 3, (S.get("last_react") or 0) + 20)
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})
    return st
