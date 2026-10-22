"""The resident's own goal for a few days: designed by the model, trained for, progressing believably."""
import random
import time

from ..config import MODEL_DEEP
from ..context import S, busy_lock, emit_event, g, hub, save_state, set_busy, state_lock, world_epoch
from ..clock import is_awake_time, now
from ..world import ACTIONS
from ..brain import LLMError, llm
from . import emotions, needs, prompts, state


def goal_text():
    G = S.get("goal")
    if not G:
        return "Своей цели на ближайшие дни у тебя сейчас нет — можешь придумать её утром или если станет скучно."
    m = G.get("metric")
    metric = f" Показатель: {m['name']} — сейчас {fmt_num(m['current'])} {m['unit']}, цель {fmt_num(m['target'])} {m['unit']}." if m else ""
    today = now().strftime("%Y-%m-%d")
    done_today = sum(x["minutes"] for x in G["sessions"] if x["day"] == today)
    days_left = max(0, int((G["deadline"] - time.time()) / 86400 + 0.99))
    nxt = next((ms for ms in G["milestones"] if not ms.get("done")), None)
    return (f"Твоя текущая цель: «{G['title']}» — {G['description']} Прогресс {int(G['progress'])}%.{metric}"
            f" Осталось дней: {days_left}. Сегодня ты занимал{g('ся', 'ась')} уже {done_today} мин (норма ~{G['practice_minutes']} мин)."
            + (f" Следующий этап: {nxt['title']}." if nxt else "")
            + f" Как тренироваться: {G['practice']} Отметь тренировку действием practice{{minutes, result}} в той же цепочке, где само занятие.")


def fmt_num(x):
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def make_goal(spec, source):
    """Normalise a goal designed by the model."""
    title = str(spec.get("title") or "").strip()[:80]
    if not title:
        return None
    m = spec.get("metric") if isinstance(spec.get("metric"), dict) else None
    metric = None
    if m:
        try:
            start, target = float(m.get("start", 0)), float(m.get("target", 0))
            if target != start:
                metric = {"name": str(m.get("name") or "результат")[:40], "unit": str(m.get("unit") or "")[:12],
                          "start": start, "target": target, "current": start}
        except (TypeError, ValueError):
            metric = None
    days = max(2, min(30, int(spec.get("days") or 7)))
    ms = [str(x).strip()[:60] for x in (spec.get("milestones") or []) if str(x).strip()][:5] or ["начало", "половина пути", "финиш"]
    default = spec.get("default_action") if spec.get("default_action") in ACTIONS else "workout"
    return {"title": title, "description": str(spec.get("description") or "").strip()[:240], "metric": metric, "days": days,
            "deadline": time.time() + days * 86400, "practice": str(spec.get("practice") or "").strip()[:300],
            "practice_minutes": max(5, min(90, int(spec.get("practice_minutes") or 20))), "default_action": default,
            "milestones": [{"title": t, "at": round(100 * (i + 1) / len(ms)), "done": False} for i, t in enumerate(ms)],
            "progress": 0.0, "sessions": [], "source": source, "started": time.time()}


GOAL_DESIGN = """Спроектируй цель для персонажа, который живёт в маленькой квартире (спальня, гостиная с диваном, телевизором, проигрывателем, кухня, санузел) и может делать зарядку, двигаться в любых позах, готовить, читать, рисовать в блокноте, слушать музыку.
Цель должна быть достижима дома за несколько дней регулярных занятий. Если цель измеримая (секунды, повторы, сантиметры, блюда) — задай показатель со стартом и целью, реалистичными для обычного человека.
Ответ JSON: {"title": "коротко", "description": "1 предложение, зачем и что получится", "metric": {"name": "что меряем", "unit": "ед.", "start": число, "target": число} или null, "days": сколько дней (3–21), "practice": "как тренироваться в квартире, 1–2 предложения, через доступные действия (workout, move с позами, cook, read_book, write_diary, look_window…)", "practice_minutes": минут в день, "default_action": "одно действие для тренировки: workout | cook | read_book | write_diary | look_window | dance", "milestones": ["3–5 этапов по порядку"]}"""


def set_goal_from_text(text, source="guest"):
    epoch = world_epoch["v"]
    prompt = f"{GOAL_DESIGN}\n\nЦель ({'предложил гость' if source == 'guest' else 'договорились в разговоре' if source == 'chat' else 'придумал сам персонаж'}): {text}"
    with busy_lock:
        set_busy("plan")
        try:
            r = llm("goal", MODEL_DEEP, prompts.persona(), prompt)
        except (LLMError, ValueError) as e:
            emit_event("system", f"Цель не получилось оформить: {e}")
            return None
        finally:
            set_busy(None)
    G = make_goal(r, source)
    if not G or epoch != world_epoch["v"]:
        return None
    with state_lock:
        S["goal"] = G
        save_state()
    emit_event("goal", f"Новая цель: {G['title']} — {G['description']}", {"goal": G})
    hub.publish({"type": "state", "state": state.public_state()})
    if source == "guest" and is_awake_time():
        with state_lock:
            S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"Гость предложил тебе цель: «{G['title']}». Отреагируй — можешь сразу начать первую тренировку."]
            S["react_at"] = time.time() + 2
    return G


def practice(a):
    """Log a practice session; progress grows believably."""
    G = S.get("goal")
    if not G:
        return
    try:
        minutes = max(1, min(120, int(a.get("minutes") or G["practice_minutes"])))
    except (TypeError, ValueError):
        minutes = G["practice_minutes"]
    today = now().strftime("%Y-%m-%d")
    today_min = sum(x["minutes"] for x in G["sessions"] if x["day"] == today)
    m, result = G.get("metric"), None
    if m:
        step = max(abs(m["target"] - m["start"]) / (G["days"] * 0.8), 0.5)
        sign = 1 if m["target"] > m["start"] else -1
        try:
            result = float(a.get("result"))
        except (TypeError, ValueError):
            result = m["current"] + sign * step * min(1.0, minutes / G["practice_minutes"]) * random.uniform(0.3, 0.9)
        best = m["current"] + sign * step
        result = min(result, best) if sign > 0 else max(result, best)
        if (result - m["current"]) * sign > 0:
            m["current"] = round(result, 1)
        G["progress"] = round(max(0, min(100, 100 * (m["current"] - m["start"]) / (m["target"] - m["start"]))), 1)
    else:
        useful = max(0, min(minutes, G["practice_minutes"] * 2 - today_min))  # practice beyond twice the daily norm doesn't count
        G["progress"] = round(min(100, G["progress"] + 100 * useful / (G["practice_minutes"] * G["days"])), 1)
    G["sessions"] = (G["sessions"] + [{"ts": time.time(), "day": today, "minutes": minutes, "result": result,
                                       "note": str(a.get("note") or "")[:120]}])[-60:]
    S["needs"]["energy"] = needs.clampn(S["needs"]["energy"] - minutes * 0.1)
    S["needs"]["fun"] = needs.clampn(S["needs"]["fun"] + needs.fun_gain(3))
    emit_event("practice", f"Тренировка к цели «{G['title']}»: {minutes} мин" + (f", результат {fmt_num(result)} {m['unit']}" if m and result is not None else "") + f" — прогресс {int(G['progress'])}%")
    for ms in G["milestones"]:
        if not ms["done"] and G["progress"] >= ms["at"]:
            ms["done"] = True
            emotions.appraise("joy", 0.6)
            emit_event("milestone", f"Этап цели «{G['title']}» пройден: {ms['title']}")
    if G["progress"] >= 100:
        emotions.appraise("joy", 0.9)
        emit_event("milestone", f"Цель достигнута: {G['title']}!")
        S["goals_done"] = (S.get("goals_done") or []) + [{"title": G["title"], "done": time.time(), "days": round((time.time() - G["started"]) / 86400, 1)}]
        S["goal"] = None


def with_practice_activity(actions):
    if any(a["do"] == "practice" for a in actions) and not any(a["do"] != "practice" for a in actions) and S.get("goal"):
        return [{"do": S["goal"].get("default_action") or "workout"}] + actions
    return actions
