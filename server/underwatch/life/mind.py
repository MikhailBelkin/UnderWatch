"""Thinking: the next thing to do, the morning plan, the evening diary, replies to the guest, and the clock of life."""
import json
import random
import re
import time
import traceback

from ..config import MODEL_DEEP, MODEL_FAST, TICK, log
from ..context import RESIDENTS, S, as_resident, busy_lock, emit_event, g, hub, save_state, set_busy, spawn, state_lock, store
from ..settings import sleep_h, trait, wake_h
from ..clock import day_key, hhmm, is_awake_time, next_wake, now, today_sleep
from ..brain import LLMError, llm, mind_paused
from . import bonds, emotions, gifts, goals, memory, needs, prompts, state
from . import body


def decide(reason="next", happened=None):
    if happened:
        reason_text = "Только что, прямо сейчас:\n" + "\n".join("- " + h for h in happened) + "\nТы это замечаешь и реагируешь (можно прервать текущее занятие)."
    else:
        reason_text = "Прошлое занятие закончилось." if reason == "next" else "Тебя отвлекло самочувствие."
    prompt = f"""{prompts.situation()}

Недавно:
{prompts.recent_lines()}

{reason_text} Реши, чем заняться дальше. Твой характер: {prompts.character_text()} — пусть он определяет, чем тебе хочется заняться. Не забывай про свою цель (тренировка — practice) и про главную — сблизиться с гостем (можно написать ему первым через to_guest, спросить о нём что-то из того, чего ты ещё не знаешь). Это твоя жизнь: следуй своим желаниям, плану и самочувствию, не повторяй одно и то же без причины, иногда делай что-то неожиданное.
Ответ JSON:
{{"thought": "внутренний монолог, 1–3 предложения", "intent": "коротко, что сейчас делаешь", "actions": [{{"do": "..."}}], "minutes": сколько минут продлится последнее долгое занятие (1–90), "emotion": "{emotions.EMO_LIST}", "intensity": сила эмоции 0.1–1, "aloud": "что говоришь вслух сам{g('', 'а')} себе, или пусто", "diary": "короткая заметка в блокнот, если случилось важное, иначе пусто", "to_guest": "если скучаешь или хочешь что-то сказать гостю сам{g('', 'а')}, первым — короткое сообщение ему; иначе пусто", "wish": "ОБЯЗАТЕЛЬНО заполни, если в этом ответе ты говоришь, что хотел{g('', 'а')} бы получить что-то в подарок или просишь что-то подарить: что именно, коротко (например «круассан», «книга Бунина в твёрдом переплёте»); иначе пусто"}}"""
    r = llm("decide", MODEL_FAST, prompts.persona(), prompt)
    actions = body.understand(r.get("actions"))
    if json.dumps(r.get("actions"), ensure_ascii=False, sort_keys=True) != json.dumps(actions, ensure_ascii=False, sort_keys=True):
        log("actions:", json.dumps(r.get("actions"), ensure_ascii=False)[:300], "->", json.dumps(actions, ensure_ascii=False)[:300])
    minutes = max(1, min(90, int(r.get("minutes") or 20)))
    if not actions:
        minutes = min(minutes, 5)  # nothing actually done: look again soon
    thought = str(r.get("thought") or "").strip()
    with state_lock:
        S["last_decide"] = time.time()
    if thought:
        emit_event("thought", thought)
    aloud = str(r.get("aloud") or "").strip()
    if aloud:
        emit_event("aloud", aloud)
    if str(r.get("diary") or "").strip():
        emit_event("note", str(r["diary"]).strip())
    if r.get("wish"):
        gifts.add_wish(r["wish"])
    note = str(r.get("to_guest") or "").strip()
    if note and time.time() - (S.get("last_initiative") or 0) > (90, 30, 15)[prompts.talk_level()] * 60:  # talkative ones write first more often
        with state_lock:
            S["last_initiative"] = time.time()
        emit_event("chat_reply", note, {"initiated": True})
    body.act(actions, minutes=minutes, thought=thought, intent=str(r.get("intent") or "").strip(), emotion=emotions.parse_emotion(r), aloud=aloud)


def morning():
    t = now()
    diary = store.events(["diary"], limit=1)
    prompt = f"""{prompts.situation()}

Вчерашний дневник:
{diary[-1]['text'] if diary else '(дневника ещё нет — это твой первый день здесь)'}

Ты только что {g('проснулся', 'проснулась')}. Составь себе нестрогий план на сегодня (с {wake_h()}:00 до {sleep_h()}:00): 3–6 пунктов — дела, желания, маленькие цели. Учитывай свои увлечения, проекты и то, что было вчера. Если у тебя есть цель — обязательно впиши тренировку к ней. Помни и о главной цели — узнать гостя лучше.
Ответ JSON: {{"plan": ["пункт", "..."], "thought": "первая мысль утром, 1–2 предложения", "emotion": "{emotions.EMO_LIST}", "intensity": сила эмоции 0.1–1, "own_goal": "если своей цели сейчас нет и тебе хочется её поставить — коротко какую (например «научиться делать шпагат»), иначе пусто"}}"""
    try:
        r = llm("plan", MODEL_DEEP, prompts.persona(), prompt)
        plan = [str(p).strip() for p in (r.get("plan") or []) if str(p).strip()][:6]
        own = str(r.get("own_goal") or "").strip()
        thought = str(r.get("thought") or "").strip()
        emotion = emotions.parse_emotion(r)
    except LLMError as e:
        emit_event("system", f"Утренний план не составился: {e}")
        plan, thought, emotion, own = [], "", None, ""
    with state_lock:
        S["plan"], S["plan_day"] = plan, t.strftime("%Y-%m-%d")
        S["needs"]["energy"] = max(S["needs"]["energy"], 85)
        S["needs"]["bladder"] = min(S["needs"]["bladder"], 30)
        S["needs"]["hygiene"] = min(S["needs"]["hygiene"], 55)
    if plan:
        emit_event("plan", "; ".join(plan), {"plan": plan})
    if thought:
        emit_event("thought", thought)
    body.act([{"do": "stand"}, {"do": "stretch"}], minutes=1, thought=thought, intent="просыпается", emotion=emotion)
    if own and not S.get("goal"):
        spawn(goals.set_goal_from_text, own, "self")


def reflect():
    """Evening reflection = diary + memory compaction (rewrite notes about self and guest)."""
    since = S.get("reflect_ts") or 0
    evs = store.events(["thought", "action", "chat_user", "chat_reply", "aloud", "plan", "note", "world", "gift", "wish", "learned", "practice", "milestone", "goal"], limit=400, since=since)
    if not evs:
        with state_lock:
            S["reflect_ts"] = time.time()
        save_state()
        return
    lines = "\n".join(f"[{hhmm(e['ts'])}] {e['kind']}: {e['text']}" for e in evs)[-60000:]
    prompt = f"""{prompts.situation()}

Всё, что было с прошлого вечера:
{lines}

День закончился, ты ложишься спать. Подведи итоги.
Ответ JSON:
{{"diary": "запись в дневник за сегодня от первого лица, 4–8 предложений: что делал{g('', 'а')}, что чувствовал{g('', 'а')}, что запомнилось",
 "self_notes": "обновлённые заметки о себе (до 1500 символов, короткие пункты «- »): привычки, увлечения, текущие проекты и цели, отношения с друзьями и родными, важные события. Сохрани важное из старых заметок, обнови устаревшее, добавь новое. Заметки не должны противоречить основе личности, заданной в начале — она главнее",
 "guest_notes": "обновлённые заметки о госте (до 1000 символов, пункты «- »): как зовут, что о нём известно, о чём говорили, о чём договорились. Ссоры записывай коротко как факт и чем кончилось, без выводов на будущее и без обид — ты отходчив{g('', 'а')}. Если на какой-то вопрос гость ответил — запиши ответ, а не вопрос; не переноси состояния вроде «сейчас пропал» или «надо поговорить о…», если это уже выяснилось. Если гость не появлялся — верни прежние заметки как есть или пусто"}}"""
    r = llm("reflect", MODEL_DEEP, prompts.persona(), prompt, timeout=300)
    if str(r.get("diary") or "").strip():
        emit_event("diary", str(r["diary"]).strip())
    if str(r.get("self_notes") or "").strip():
        store.set("self_notes", str(r["self_notes"]).strip()[:2500])
    if str(r.get("guest_notes") or "").strip():
        store.set("guest_notes", str(r["guest_notes"]).strip()[:2000])
    store.set("day_memory", "")  # folded into the notes above
    store.set("memory_upto", memory.last_chat_id())
    with state_lock:
        S["reflect_ts"] = time.time()
    save_state()
    hub.publish({"type": "notes", "notes": state.notes(), "diary": store.events(["diary"], limit=10)})


SLEEPY = ["Ззз…", "(сонно) м-м… утром поговорим…", "(переворачивается на другой бок)", "Хр-р… пять минуточек…", "(бормочет во сне что-то про пластинки)"]

DOING_WORDS = re.compile(r"\b(открыва|откро|пойд|пошл|иду|идём|идем|едем|сейчас|свар|приготов|включ|выключ|поставл|почита|поигра|посмотр|переоде|умо|приму|лягу|сяду|возьм|давай)")


def chat(text):
    emit_event("chat_user", text)
    emotions.guest_here()
    bonds.grow_closeness(0.4, "chat")
    with state_lock:
        S["needs"]["social"] = needs.clampn(S["needs"]["social"] + 4 + 8 * trait("extraversion"))
        S["needs"]["energy"] = needs.clampn(S["needs"]["energy"] - 1.5 * (1 - trait("extraversion")))  # talking tires an introvert
        asleep = not is_awake_time()
    if mind_paused():
        line = f"({S['name']} задумал{g('ся', 'ась')} и не отвечает — разум на паузе)"
        emit_event("chat_reply", line, {"paused": True})
        hub.publish({"type": "say", "text": line})
        return
    if asleep:
        line = random.choice(SLEEPY)
        emit_event("chat_reply", line, {"asleep": True, "wake_at": next_wake().timestamp()})
        hub.publish({"type": "say", "text": line})
        return
    with busy_lock:
        set_busy("chat")
        try:
            prompt = f"""{prompts.situation()}

Недавно:
{prompts.recent_lines(12)}

Разговор с гостем:
{prompts.chat_lines()}

{bonds.guest_knowledge_text()}

Гость только что сказал: {text}

Твой характер: {prompts.character_text()}. Отвечай так, как ответил бы человек именно с таким характером — даже если раньше вы спорили или ты был{g('', 'а')} другой; характер важнее прошлых реплик и заметок.
Не задавай снова вопрос, который уже задавал{g('', 'а')}, если гость на него ответил — пусть шуткой, уклончиво или не так, как хотелось: прими ответ, можешь отреагировать на него, но не переспрашивай. Если гость прямо отказался отвечать — не дави и не возвращайся к этому сегодня. Не заканчивай каждую реплику одним и тем же требованием.
Ответь гостю как живой человек: {["очень коротко, 1–2 предложения — ты немногословн" + g("ый", "ая"), "коротко (1–3 предложения)", "живо и развёрнуто, 2–5 предложений — ты любишь рассказывать"][prompts.talk_level()]}, в своём характере и настроении. Если хочешь или гость просит — сделай что-то (actions); если нет — actions пустой, и ты продолжаешь своё занятие.
ВАЖНО: тело делает только то, что в actions. Если в реплике ты говоришь, что что-то делаешь или сейчас сделаешь («открываю», «пойду сварю кофе», «включу музыку», «давай почитаю»), — обязательно добавь это действие в actions (open_gift, cook, music_on, read_book…). Не обещай словами то, чего не делаешь.
Ответ JSON: {{"say": "реплика гостю", "thought": "что ты при этом подумал{g('', 'а')}, 1 предложение", "emotion": "{emotions.EMO_LIST}", "intensity": сила эмоции 0.1–1, "actions": [], "minutes": сколько минут займёт новое занятие, если actions не пустой, "wish": "ОБЯЗАТЕЛЬНО заполни, если в этом ответе ты говоришь, что хотел{g('', 'а')} бы получить что-то в подарок или просишь что-то подарить: что именно, коротко (например «круассан», «книга Бунина в твёрдом переплёте»); иначе пусто", "learned": [{{"topic": "одна из тем: {', '.join(bonds.GUEST_TOPICS)}", "fact": "что гость рассказал о себе в последней реплике, коротко"}}] — только то, что он сам сказал о себе, иначе пустой список, "goal": "только если вы прямо сейчас договорились о новой цели для тебя (гость предложил, и ты согласил{g('ся', 'ась')}, или ты сам{g('', 'а')} решил{g('', 'а')}) — коротко какую; иначе пусто"}}"""
            r = llm("chat", MODEL_FAST, prompts.persona(), prompt)
            say = str(r.get("say") or "").strip() or "…"
            actions = body.understand(r.get("actions"))
            thought = str(r.get("thought") or "").strip()
            emit_event("chat_reply", say, {"actions": actions})
            if r.get("wish"):
                gifts.add_wish(r["wish"])
            bonds.learn_facts(r.get("learned"))
            if str(r.get("goal") or "").strip():
                spawn(goals.set_goal_from_text, str(r["goal"]), "chat")
            if thought:
                emit_event("thought", thought)
            minutes = max(3, min(90, int(r.get("minutes") or 15))) if actions else None
            if not actions and DOING_WORDS.search(say.lower()):
                # she promised to do something but the answer carried no actions: let her own mind follow through
                with state_lock:
                    S["react_reasons"] = (S.get("react_reasons") or [])[-5:] + [f"Ты только что сказал{g('', 'а')} гостю: «{say[:200]}». Сделай то, что пообещал{g('', 'а')}."]
                    S["react_at"] = time.time() + 2
                log("chat promised without actions, follow-up scheduled:", say[:120])
            body.act(actions, minutes=minutes, thought=thought or None, emotion=emotions.parse_emotion(r), source="chat")
            hub.publish({"type": "say", "text": say})
        except (LLMError, ValueError) as e:
            emit_event("chat_reply", "Прости, задумал" + g("ся", "ась") + "… повтори?", {"error": str(e)})
            emit_event("system", f"Ответ не получился: {e}")
        finally:
            set_busy(None)
    memory.maybe_remember()


def mind_step():
    needs.update_needs()
    if mind_paused():  # the GPU is needed elsewhere: the body lives on, the mind waits
        if int(time.time()) % 60 < TICK:
            save_state()
            hub.publish({"type": "needs", "needs": {k: round(v, 1) for k, v in S["needs"].items()}, "needs_view": needs.needs_view(), "water": S["water"], "leak": S["leak"], "emo": {k: round(v, 3) for k, v in S["emo"].items()}})
        return
    gone = [v for v in S.get("visitors", []) if v.get("until") and v["until"] < time.time()]
    if gone:
        with state_lock:
            S["visitors"] = [v for v in S["visitors"] if v not in gone]
            save_state()
        hub.publish({"type": "state", "state": state.public_state()})
    t = now()
    if not is_awake_time(t):
        # evening: one reflection per day (diary + memory compaction), then sleep; no model calls at night
        if S.get("reflect_day") != day_key(t):
            with busy_lock:
                set_busy("reflect")
                try:
                    reflect()
                except (LLMError, ValueError) as e:
                    emit_event("system", f"Вечерние итоги не получились: {e}")
                finally:
                    with state_lock:
                        S["reflect_day"] = day_key(t)
                    set_busy(None)
        if S["loop"] != "sleep":
            dress = [] if state.outfit_of()["type"] == "pajamas" else [{"do": "change_clothes", "outfit": "pajamas", "private": body.clothes.wants_privacy()}]  # at the wardrobe, not by magic
            body.act(dress + [{"do": "sleep"}], thought="Всё, на сегодня хватит. Переоденусь в пижаму — и спать.", intent="спит", mood="sleepy", aloud="Спокойной ночи.")
        with state_lock:
            S["until"] = next_wake(t).timestamp()
        if S["leak"] or int(time.time()) % 60 < TICK:
            save_state()
            hub.publish({"type": "needs", "needs": {k: round(v, 1) for k, v in S["needs"].items()}, "needs_view": needs.needs_view(), "water": S["water"], "leak": S["leak"], "emo": {k: round(v, 3) for k, v in S["emo"].items()}})
        return
    if S["plan_day"] != t.strftime("%Y-%m-%d"):
        with busy_lock:
            set_busy("plan")
            try:
                morning()
            finally:
                set_busy(None)
        return
    if S["loop"] == "sleep" and S["until"] > today_sleep(t).timestamp():
        with state_lock:
            S["until"] = time.time()  # night sleep but it's daytime now (hours changed, server was down): wake up
    if S.get("react_reasons") and time.time() >= S.get("react_at", 0):
        if not busy_lock.acquire(blocking=False):
            return
        with state_lock:
            happened, S["react_reasons"], S["last_react"] = S["react_reasons"], [], time.time()
        set_busy("think")
        try:
            decide("react", happened=happened)
        except (LLMError, ValueError) as e:
            emit_event("system", f"Реакция не сложилась ({e}).")
        finally:
            set_busy(None)
            busy_lock.release()
        return
    n = S["needs"]
    urgent = min(n.values()) < 10 and time.time() - S["last_decide"] > 600 and S["loop"] != "sleep"
    if time.time() >= S["until"] or urgent:
        if not busy_lock.acquire(blocking=False):
            return
        set_busy("think")
        try:
            decide("urgent" if urgent and time.time() < S["until"] else "next")
        except (LLMError, ValueError) as e:
            emit_event("system", f"Мысль не сложилась ({e}). Попробую через 10 минут.")
            body.act([{"do": "look_window"}], minutes=10, thought="…", intent="задумался")
        finally:
            set_busy(None)
            busy_lock.release()
    elif S["leak"] or S["loop"] == "mop" or int(time.time()) % 60 < TICK:
        save_state()
        hub.publish({"type": "needs", "needs": {k: round(v, 1) for k, v in S["needs"].items()}, "needs_view": needs.needs_view(), "water": S["water"], "leak": S["leak"], "emo": {k: round(v, 3) for k, v in S["emo"].items()}})


def mind_loop():
    while True:
        for r in list(RESIDENTS.values()):
            try:
                as_resident(r, mind_step)
            except Exception:
                log(f"mind error ({r.login}):\n" + traceback.format_exc())
        time.sleep(TICK)
