"""The day memory of conversations: answers already given are not asked again."""

from ..config import MODEL_FAST, log
from ..context import S, busy_lock, g, hub, memory_running, set_busy, spawn, store, world_epoch
from ..clock import hhmm
from ..brain import LLMError, llm
from . import state


MEMORY_EVERY = 10  # guest + resident lines between memory updates


def last_chat_id():
    ev = store.events(["chat_user", "chat_reply"], limit=1)
    return ev[-1]["id"] if ev else 0


def remember():
    """Fold the latest conversation into the day memory, so answers outlive the chat window."""
    epoch = world_epoch["v"]
    try:
        with busy_lock:
            set_busy("memory")
            try:
                upto = store.get("memory_upto") or 0
                new = [e for e in store.events(["chat_user", "chat_reply"], limit=80) if e["id"] > upto]
                if not new:
                    return
                since = new[0]["ts"] - 12 * 3600
                facts = "\n".join(f"- [{hhmm(f['ts'])}] {f['fact']}" for f in S["guest_facts"] if f["ts"] >= since) or "(нет)"
                talk = "\n".join(f"[{hhmm(e['ts'])}] {'Гость' if e['kind'] == 'chat_user' else 'Ты'}: {e['text']}" for e in new)
                prompt = f"""Ты ведёшь рабочую память {S['name']} ({g('он', 'она')}) о разговорах с гостем.

Память сейчас:
{store.get("day_memory") or "(пусто)"}

Что ты знаешь о госте по старым заметкам (для справки, не переписывай их в память):
{store.get("guest_notes") or "(пусто)"}

Что гость рассказал о себе за последние часы (выписки, в том числе из реплик, которых ниже уже нет):
{facts}

Новые реплики:
{talk}

Ответ JSON из двух полей.
"closed": вопросы, которые {S['name']} уже задавал{g('', 'а')} гостю и на которые он ответил (даже шуткой, уклончиво или противоречиво) или прямо отказался отвечать. Каждый пункт — «вопрос — что ответил» или «вопрос — отказался отвечать». Сохрани и пункты из старой памяти.
"memory": до 1000 символов, короткие пункты «- », от первого лица {S['name']}: о чём договорились и что пообещали; чем кончились споры и обиды — коротко, без накручивания; что важного произошло в разговоре; что осталось открытым — только то, о чём гостя ещё не спрашивали; закрытые вопросы сюда не повторяй.
Пиши только о разговорах и отношениях; биографию гостя из старых заметок не повторяй. Если что-то из заметок уже устарело (например, там написано, что он пропал, а он вернулся) — так и запиши. Старое из памяти сохраняй, если оно ещё важно. Не придумывай того, чего не было в репликах.
{{"closed": ["вопрос — ответ"], "memory": "..."}}"""
                r = llm("memory", MODEL_FAST, f"Ты помогаешь вести память персонажа по имени {S['name']}. Пиши по-русски. Отвечай только JSON.", prompt)
            except (LLMError, ValueError) as e:
                log("memory update failed:", e)
                return
            finally:
                set_busy(None)
        mem = str(r.get("memory") or "").strip()[:1400]
        closed = [str(x).strip()[:200] for x in (r.get("closed") or []) if str(x).strip()][:12]
        if closed:
            mem += "\nУже спрашивал" + g("", "а") + " — больше не спрашивай, тема закрыта (ответ можно вспомнить и обсудить, но не требуй другого):\n" + "\n".join("- " + x for x in closed)
        if mem.strip() and epoch == world_epoch["v"]:
            store.set("day_memory", mem)
            store.set("memory_upto", new[-1]["id"])
            hub.publish({"type": "notes", "notes": state.notes(), "diary": store.events(["diary"], limit=10)})
    finally:
        memory_running.clear()


def maybe_remember():
    upto = store.get("memory_upto") or 0
    if memory_running.is_set():
        return
    pending = [e for e in store.events(["chat_user", "chat_reply"], limit=MEMORY_EVERY) if e["id"] > upto]
    if len(pending) >= MEMORY_EVERY:
        memory_running.set()
        spawn(remember)
