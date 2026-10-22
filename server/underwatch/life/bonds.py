"""The bond with the guest: what the resident knows about them and how close they are."""
import difflib
import re
import time
from datetime import datetime

from ..config import TZ
from ..context import S, emit_event, g, state_lock
from ..clock import now
from . import emotions


# global goal: get to know the guest and grow close; local goal: a short project with practice and progress
GUEST_TOPICS = ["имя", "возраст", "город", "работа", "семья", "друзья", "увлечения", "спорт", "музыка", "фильмы и сериалы",
                "книги", "любимая еда", "путешествия", "питомцы", "детство", "мечты", "страхи", "планы", "характер", "как проходят его дни"]

TOPIC_WORDS = [("имя", r"зовут|имя"), ("возраст", r"\d+\s*(год|лет)|\bлет\b|возраст"), ("город", r"жив[её]т|город|любляна|переехал|родом"),
               ("работа", r"работ|программист|профессия|должност|офис|проект|начальник|коллег"), ("семья", r"мам|пап|жена|муж|брат|сестр|сын|доч|семь|дет[еия]|ребён|ребен"),
               ("друзья", r"друг|друз|подруг"), ("питомцы", r"\bкот|кошк|собак|пёс|пес\b|попуга|хомяк|питом"),
               ("спорт", r"спорт|бега|бег\b|зал|йог|велосипед|плава|лыж|футбол"), ("музыка", r"музык|песн|группа|гитар|слуша"),
               ("фильмы и сериалы", r"фильм|кино|сериал"), ("книги", r"книг|чита"), ("любимая еда", r"кофе|еда|ест\b|блюд|пицц|сладк|готов"),
               ("путешествия", r"путешеств|поездк|ездил|отпуск|страна|горы|море"), ("детство", r"детств|в детстве|школ"),
               ("мечты", r"мечта|мечтает|хочет когда-нибудь"), ("страхи", r"бои[тш]|бою|страх|страш"), ("планы", r"планир|собирается|завтра|на выходных"),
               ("увлечения", r"люб|увлека|хобби|обожа|нравится")]


def guess_topic(fact):
    low = fact.lower()
    for topic, rx in TOPIC_WORDS:
        if re.search(rx, low):
            return topic
    return "разное"


CLOSENESS_LEVELS = [(0, "незнакомец"), (10, "знакомый"), (25, "приятель"), (45, "друг"), (70, "близкий друг"), (90, "родной человек")]


def closeness_level(v=None):
    v = S.get("closeness", 0) if v is None else v
    name = CLOSENESS_LEVELS[0][1]
    for th, n in CLOSENESS_LEVELS:
        if v >= th:
            name = n
    return name


def grow_closeness(amount, why=""):
    """Closeness only grows: quarrels pass, shared good things stay."""
    with state_lock:
        day = now().strftime("%Y-%m-%d")
        if S.get("closeness_day") != day:
            S["closeness_day"], S["closeness_today"] = day, 0.0
        room = max(0.0, 15.0 - S.get("closeness_today", 0))   # at most ~15 points a day
        amount = min(amount, room) * (1.0 - 0.6 * S.get("closeness", 0) / 100)  # slower near the top
        if amount <= 0:
            return
        before = closeness_level()
        S["closeness"] = round(min(100.0, S.get("closeness", 0) + amount), 2)
        S["closeness_today"] = S.get("closeness_today", 0) + amount
        after = closeness_level()
    if after != before:
        emit_event("milestone", f"Новый уровень близости: {after}", {"level": after})
        emotions.appraise("joy", 0.6)


def learn_facts(raw):
    if not isinstance(raw, list):
        return
    added = 0
    with state_lock:
        known = {(f["topic"], f["fact"].lower()) for f in S["guest_facts"]}
        for x in raw[:5]:
            if not isinstance(x, dict):
                continue
            topic = str(x.get("topic") or "").strip().lower()[:40]
            fact = str(x.get("fact") or "").strip()[:160]
            if len(fact) < 3:
                continue
            if topic not in GUEST_TOPICS:
                topic = next((t for t in GUEST_TOPICS if t.split()[0] in topic), None) or guess_topic(fact)
            if (topic, fact.lower()) in known or any(t == topic and difflib.SequenceMatcher(None, f, fact.lower()).ratio() > 0.75 for t, f in known):
                continue  # the same thing told again in other words
            S["guest_facts"].append({"topic": topic, "fact": fact, "ts": time.time()})
            known.add((topic, fact.lower()))
            added += 1
        S["guest_facts"] = S["guest_facts"][-120:]
    for _ in range(added):
        grow_closeness(2.0, "fact")
    if added:
        emit_event("learned", "Узнал" + g("", "а") + " о госте: " + "; ".join(f["fact"] for f in S["guest_facts"][-added:]))


def acquaintance():
    topics = {f["topic"] for f in S["guest_facts"]} & set(GUEST_TOPICS)
    return round(100 * len(topics) / len(GUEST_TOPICS))


def guest_knowledge_text():
    facts = S["guest_facts"][-30:]
    known_topics = {f["topic"] for f in S["guest_facts"]}
    unknown = [t for t in GUEST_TOPICS if t not in known_topics]
    lines = [f"Твоя главная цель в жизни — по-настоящему узнать гостя и стать ему как можно ближе (сейчас вы: {closeness_level()}, знакомство {acquaintance()}%)."]
    if facts:
        lines.append("Что ты уже знаешь о нём:\n" + "\n".join(f"- [{f['topic']}, {datetime.fromtimestamp(f['ts'], TZ):%d.%m}] {f['fact']}" for f in facts))
    if unknown:
        lines.append("Чего ты о нём ещё не знаешь (можно мягко расспросить, по одной теме за раз и не в каждой реплике): " + ", ".join(unknown[:6]) + ".")
    lines.append("Используй то, что знаешь: вспоминай, спрашивай, как прошло то, о чём он рассказывал, радуйся общим интересам.")
    return "\n".join(lines)
