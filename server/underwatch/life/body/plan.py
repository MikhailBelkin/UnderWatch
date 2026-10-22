"""Reading what the model wants the body to do: cleaning a chain of actions and filling in what is obvious."""
import re

from ...context import R, S, emit_event, g
from ...clock import is_awake_time, now, today_sleep
from ...world import ACTIONS, COLORS, MOTIONS, MOVE_RANGES, NATURAL, OUTFIT_TYPES, PLACES, ROOMS, SPOTS, SURFACES, TOGETHER
from .. import gifts, goals, state
from . import clothes


def clean_move(a):
    frames = []
    for fr in (a.get("frames") or [])[:12]:
        if not isinstance(fr, dict):
            continue
        f = {}
        for k, (lo, hi) in MOVE_RANGES.items():
            if k in fr:
                try:
                    f[k] = max(lo, min(hi, float(fr[k])))
                except (TypeError, ValueError):
                    pass
        f.setdefault("t", 0.8)
        frames.append(f)
    if not frames:
        return None
    try:
        repeat = max(1, min(10, int(a.get("repeat") or 1)))
    except (TypeError, ValueError):
        repeat = 1
    per = sum(f["t"] + f.get("hold", 0) for f in frames)
    while repeat > 1 and per * repeat > 40:
        repeat -= 1
    if per > 40:
        return None
    return {"frames": frames, "repeat": repeat, "end": "hold" if a.get("end") == "hold" else "stand",
            "label": str(a.get("label") or "двигается").strip()[:40], "secs": round(per * repeat, 1),
            "on": a.get("on") if a.get("on") in ("bed", "sofa", "coffee_table", "floor") else "floor"}


def clean_actions(raw):
    out = []
    for a in (raw if isinstance(raw, list) else [])[:6]:
        if not isinstance(a, dict):
            continue
        for nest in ("args", "params", "parameters"):  # the model sometimes nests the parameters
            if isinstance(a.get(nest), dict):
                a = {**a[nest], **{k: v for k, v in a.items() if k != nest}}
        d = str(a.get("do", "")).strip()
        m = re.fullmatch(r"(\w+)\s*[{(]\s*([^})]*?)\s*[})]", d)  # the model sometimes writes the doc notation: open_gift{4}, light_on{living}
        if m:
            d, arg = m.group(1), m.group(2).strip("'\" ")
            a = dict(a)
            for tok in [t.strip("'\" ") for t in arg.split(",")]:
                if tok in SURFACES:
                    a.setdefault("on", tok)
                elif tok in ("sit", "lie", "stand"):
                    a.setdefault("how", tok)
            if arg.isdigit():
                a.setdefault("id", int(arg))
            elif arg in PLACES:
                a.setdefault("place", arg)
            elif arg in ROOMS:
                a.setdefault("room", arg)
            elif arg in ("date", "movie", "dance", "cook", "custom"):
                a.setdefault("kind", arg)
            elif arg in COLORS:
                a.setdefault("color", arg)
            elif arg.split(",")[0].strip() in OUTFIT_TYPES:
                parts = [x.strip() for x in arg.split(",")]
                a.setdefault("outfit", parts[0])
                if len(parts) > 1 and parts[1] in COLORS:
                    a.setdefault("color", parts[1])
        if d not in ACTIONS:
            continue
        x = {"do": d}
        if d == "walk_to":
            if a.get("place") not in PLACES:
                continue
            x["place"] = a["place"]
        if d == "sit" and (a.get("on") or a.get("place")) in SURFACES and (a.get("on") or a.get("place")) != "sofa":
            d, a = "rest", dict(a, on=a.get("on") or a.get("place"), how="sit")
            x["do"] = "rest"
        if d == "practice":
            for k in ("minutes", "result", "note"):
                if a.get(k) is not None:
                    x[k] = a[k]
        if d == "rest":
            on = a.get("on") if a.get("on") in SURFACES else ("sofa" if a.get("how") == "lie" else "sofa")
            how = a.get("how") if a.get("how") in SURFACES[on] else SURFACES[on][0]
            x["on"], x["how"] = on, how
        if d == "sleep" and a.get("on") in ("bed", "sofa", "floor"):
            x["on"] = a["on"]
        if d == "move":
            mv = clean_move(a)
            if not mv:
                continue
            x.update(mv)
        if d == "together" and a.get("kind") in ("date", "movie", "dance", "cook", "custom"):
            x["kind"] = a["kind"]
        if d == "use_item":
            try:
                if a.get("with") is not None:
                    x["with"] = int(a["with"][0] if isinstance(a["with"], list) and a["with"] else a["with"])
            except (TypeError, ValueError):
                pass
            if a.get("at") in PLACES:
                x["at"] = a["at"]
            if a.get("motion") in MOTIONS:
                x["motion"] = a["motion"]
            if a.get("put") in SPOTS:
                x["put"] = a["put"]
            for k in ("status", "label"):
                if str(a.get(k) or "").strip():
                    x[k] = str(a[k]).strip()[:40]
        if d in ("open_gift", "eat_treat", "use_item", "shoo") and a.get("id") is not None:
            try:
                x["id"] = int(a["id"])
            except (TypeError, ValueError):
                pass
        if d in ("light_on", "light_off") and a.get("room") in ROOMS:
            x["room"] = a["room"]
        if d in ("change_clothes", "shower"):
            x["private"] = clothes.wants_privacy(a.get("private"))
        if d == "change_clothes" and a.get("outfit") in OUTFIT_TYPES:
            x["outfit"] = a["outfit"]
        if d == "change_clothes" and a.get("color") in COLORS:
            x["color"] = a["color"]
        out.append(x)
    return out


def complete_chain(actions):
    out = []
    for i, a in enumerate(actions):
        nxt = actions[i + 1] if i + 1 < len(actions) else None
        # a walk right before an action that walks there by itself is redundant
        if a["do"] == "walk_to" and nxt and ACTIONS[nxt["do"]][0]:
            continue
        out.append(a)
    if out and out[-1]["do"] == "walk_to" and out[-1]["place"] in NATURAL:
        nat = NATURAL[out[-1]["place"]]
        out[-1] = dict(nat) if isinstance(nat, dict) else {"do": nat}
    return out


def resolve_together(actions):
    """together{kind} becomes concrete actions; she dresses up for a date."""
    out = []
    for a in actions:
        if a["do"] != "together":
            out.append(a)
            continue
        kind = a.get("kind") or (S.get("invite") or {}).get("kind") or "date"
        if kind not in TOGETHER:
            continue
        mark = {"together": kind}
        if kind == "date":
            dressed = any(x["do"] == "change_clothes" and x.get("outfit") in ("dress", "mini") for x in out)
            if state.outfit_of()["type"] not in ("dress", "mini") and not dressed:
                out.append({"do": "change_clothes", "outfit": "dress", "private": clothes.wants_privacy()})
            out.append(dict(mark, do="date"))
        elif kind == "movie":
            out.append(dict(mark, do="watch_tv"))
        elif kind == "dance":
            out += [{"do": "music_on"}, dict(mark, do="dance_together")]
        elif kind == "cook":
            out += [dict(mark, do="cook"), dict(mark, do="date")]
        elif kind == "custom":
            out.append(dict(mark, do="date"))
    return out


def body_allows(actions):
    """The body has a say: you can't fall asleep in the daytime when you're full of energy."""
    t = now()
    left = (today_sleep(t) - t).total_seconds() / 60
    if any(a["do"] == "sleep" for a in actions) and is_awake_time(t) and S["needs"]["energy"] >= 30 and left > 15:
        e = int(S["needs"]["energy"])
        where = next((a.get("on") for a in actions if a["do"] == "sleep" and a.get("on")), "bed")
        emit_event("system", f"Хотел{g('', 'а')} лечь спать, но сна ни в одном глазу (бодрость {e}) — вместо этого просто прилег{g('', 'ла')}.")
        actions = [a for a in actions if a["do"] not in ("sleep", "walk_to")] + [{"do": "rest", "on": where, "how": "lie"}]
    return actions


def understand(raw):
    """The model's actions → what the body will do: cleaned, completed, checked against the body, gifts and time together resolved."""
    return goals.with_practice_activity(resolve_together(gifts.resolve_gifts(body_allows(complete_chain(clean_actions(raw))))))
