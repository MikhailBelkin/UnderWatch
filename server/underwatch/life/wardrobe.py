"""The wardrobe: the built-in outfits plus clothes the guest gave, turned into outfits.

A gifted piece of clothing is described by the model in the same terms the page draws every outfit with
(colours of the top and the bottom, sleeves, legs, a skirt and its length, shoes, a pattern, a belt),
so it needs no drawing. It is worn as the outfit "gift:<item id>"."""
import re

from ..config import MODEL_FAST, log
from ..context import S, hub, save_state, state_lock
from ..world import OUTFIT_TYPES
from ..brain import LLMError, llm
from . import state

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
REACH = ("none", "short", "long")
DESIGN = """Гость подарил одежду: «{name}». В маленькой 2D-игре одежда — это цвета частей тела человечка, без рисунков.
Можно ли носить это как наряд целиком (что-то, что надевают вместо обычной одежды: платье, костюм, комбинезон, бельё, пижама, свитер с брюками)?
Шарф, шапка, перчатки, носки, украшения, сумка — это аксессуары, не наряд (wearable: false).
Ответ JSON: {{"wearable": true или false, "label": "как коротко назвать наряд", "top": "#rrggbb — цвет верха, или null, если верха нет",
"sleeves": "none | short | long", "bottom": "#rrggbb — цвет низа (трусики, шорты, брюки)", "legs": "none — голые ноги | short — до середины бедра | long — до щиколоток (брюки, колготки, чулки)",
"skirt": "#rrggbb — если есть юбка или подол платья, иначе null", "skirt_len": "длина юбки от 0.4 (очень короткая) до 1.2 (ниже колен)",
"shoes": "#rrggbb или null — босиком", "dots": "true, если на ткани мелкий узор или горошек", "belt": "#rrggbb или null"}}"""


def clean_spec(raw):
    """Only what the page can draw gets through; colours must be #rrggbb."""
    if not isinstance(raw, dict) or not raw.get("wearable"):
        return None
    col = lambda v: v if isinstance(v, str) and HEX.match(v) else None
    spec = {"top": col(raw.get("top")), "bottom": col(raw.get("bottom")) or col(raw.get("top")) or "#2d3340",
            "sleeves": raw.get("sleeves") if raw.get("sleeves") in REACH else "short",
            "legs": raw.get("legs") if raw.get("legs") in REACH else "long",
            "skirt": col(raw.get("skirt")), "shoes": col(raw.get("shoes")), "belt": col(raw.get("belt")),
            "dots": bool(raw.get("dots"))}
    try:
        spec["skirtLen"] = round(max(0.4, min(1.2, float(raw.get("skirt_len") or 1.0))), 2)
    except (TypeError, ValueError):
        spec["skirtLen"] = 1.0
    spec["label"] = str(raw.get("label") or "").strip()[:40]
    return spec


def design_outfit(item_id):
    """Ask the model how a gifted garment looks as an outfit; an accessory stays an accessory (outfit = None)."""
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it or it.get("outfit") is not None:
            return
        name = it["name"]
    try:
        spec = clean_spec(llm("outfit", MODEL_FAST, "Ты помогаешь 2D-игре описать одежду. Отвечай только JSON.", DESIGN.format(name=name)))
    except (LLMError, ValueError) as e:
        log("outfit design failed:", name, e)
        return
    with state_lock:
        it = next((x for x in S["items"] if x["id"] == item_id), None)
        if not it:
            return
        it["outfit"] = spec or False  # False: looked at, it's an accessory
        save_state()
        st = state.public_state()
    hub.publish({"type": "state", "state": st})
    log(f"outfit for «{name}»:", spec or "accessory")


def gift_item(outfit_type):
    """The gift behind an outfit type like "gift:6", if she still has it and it is wearable."""
    m = re.fullmatch(r"gift:(\d+)", str(outfit_type or ""))
    if not m:
        return None
    return next((it for it in S["items"] if it["id"] == int(m.group(1)) and it["state"] == "open" and it.get("outfit")), None)


def known(outfit_type):
    return outfit_type in OUTFIT_TYPES or gift_item(outfit_type) is not None


def label(outfit_type):
    """How an outfit is called in words."""
    if outfit_type in OUTFIT_TYPES:
        return OUTFIT_TYPES[outfit_type]
    it = gift_item(outfit_type)
    return (it["outfit"].get("label") or it["name"]) if it else "одежда"


def line():
    """For the description of the flat: the gifted clothes she can change into."""
    gifts = [it for it in S["items"] if it["state"] == "open" and it.get("outfit")]
    if not gifts:
        return ""
    return " В шкафу и подаренная одежда — в неё можно переодеться: " + ", ".join(f"«{it['name']}» (outfit gift:{it['id']})" for it in gifts) + "."
