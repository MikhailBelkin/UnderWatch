"""The model: a local one through Ollama or Claude through Claude Code; one call at a time; the pause that frees the GPU."""
import glob
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

from .config import DATA, MODEL_FAST, OLLAMA_URL, log
from .context import ACC, R, S, admin_resident, emit_event, hub, spawn, store


class LLMError(Exception):
    pass


def claude_bin():
    for c in (os.environ.get("CLAUDE_BIN"), os.environ.get("CLAUDE_CODE_EXECPATH"), shutil.which("claude")):
        if c and os.path.exists(c):
            return c
    found = glob.glob(os.path.expanduser("~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude"))
    if not found:
        raise LLMError("не найден Claude Code (claude)")
    ver = lambda p: [int(x) for x in re.findall(r"claude-code-(\d+)\.(\d+)\.(\d+)", p)[0]]
    return sorted(found, key=ver)[-1]


def parse_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise LLMError("ответ не JSON: " + text[:200])


def brain():
    b = admin_resident().settings.get("brain") or {}
    out = {"backend": b.get("backend") or os.environ.get("LLM_BACKEND", "claude"),
            "fast": b.get("fast") or os.environ.get("LOCAL_FAST", "qwen3.5:27b"),
            "deep": b.get("deep") or os.environ.get("LOCAL_DEEP", "qwen3.5:27b"),
            "fallback": b.get("fallback", True)}
    if not R().admin:  # other people's residents never touch the owner's Claude subscription
        out.update(backend="local", fallback=False)
    return out


def local_models():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as r:
            return sorted(m["name"] for m in json.load(r).get("models", []))
    except (OSError, ValueError):
        return []


def ollama_post(path, body, timeout=30):
    req = urllib.request.Request(OLLAMA_URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def loaded_models():
    """Models Ollama holds in memory now, with their GPU footprint."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=5) as r:
            return [{"name": m["name"], "vram": m.get("size_vram", 0)} for m in json.load(r).get("models", [])]
    except (OSError, ValueError):
        return []


def unload_models():
    for m in loaded_models():
        try:
            ollama_post("/api/generate", {"model": m["name"], "keep_alive": 0})
        except (OSError, ValueError):
            pass


def warm_up():
    b = brain()
    if b["backend"] == "local":
        try:
            ollama_post("/api/generate", {"model": b["fast"], "keep_alive": "30m"}, timeout=300)
            log("local model loaded:", b["fast"])
        except (OSError, ValueError) as e:
            log("warm-up failed:", e)


def mind_paused():
    return bool(ACC.get("paused"))


def set_paused(paused):
    ACC.set("paused", bool(paused))
    if paused:
        unload_models()
        emit_event("system", "Разум остановлен: модели выгружены, видеокарта свободна. " + S["name"] + " живёт по текущему занятию, но не думает и не отвечает.")
    else:
        emit_event("system", "Разум снова запущен.")
        spawn(warm_up)
    from .life.state import public_state  # life imports the brain, so this one import waits until it is needed
    hub.publish({"type": "state", "state": public_state()})


def llm(purpose, model, system, prompt, timeout=240):
    """One call to the brain: local model through Ollama, or Claude through Claude Code (and Claude as the fallback)."""
    b = brain()
    if b["backend"] == "local":
        local = b["fast"] if model == MODEL_FAST else b["deep"]
        try:
            return llm_local(purpose, local, system, prompt, timeout)
        except LLMError as e:
            if not b["fallback"]:
                raise
            log(f"local model failed ({e}); falling back to Claude")
    return llm_claude(purpose, model, system, prompt, timeout)


def llm_local(purpose, model, system, prompt, timeout=240):
    body = {"model": model, "stream": False, "format": "json", "think": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0.8, "top_p": 0.95, "num_ctx": 16384, "num_predict": 1500}}
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except (OSError, ValueError) as e:
        store.log_usage(purpose, "local:" + model, 0, 0, 0, time.time() - t0, False)
        raise LLMError(f"локальная модель недоступна: {e}")
    secs = time.time() - t0
    tin, tout = d.get("prompt_eval_count", 0), d.get("eval_count", 0)
    text = ((d.get("message") or {}).get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        result = parse_json(text)
        ok = isinstance(result, dict)
    except (LLMError, ValueError):
        result, ok = None, False
    store.log_usage(purpose, "local:" + model, tin, tout, 0, secs, ok)
    hub.publish({"type": "usage", "usage": store.usage_today()})
    if not ok:
        raise LLMError("локальная модель ответила не JSON: " + text[:200])
    log(f"llm {purpose} local:{model}: {tin} in / {tout} out, {secs:.1f}s")
    return result


def llm_claude(purpose, model, system, prompt, timeout=240):
    cmd = [claude_bin(), "-p", "--model", model, "--tools", "", "--system-prompt", system,
           "--output-format", "json", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
    env = dict(os.environ)
    if model == MODEL_FAST:
        env["MAX_THINKING_TOKENS"] = "0"  # everyday decisions don't need extended thinking: ~3 s and ~150 tokens instead of ~30 s and ~4k
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(DATA), env=env)
    except subprocess.TimeoutExpired:
        store.log_usage(purpose, model, 0, 0, 0, time.time() - t0, False)
        raise LLMError("таймаут")
    secs = time.time() - t0
    try:
        d = json.loads(p.stdout)
    except ValueError:
        store.log_usage(purpose, model, 0, 0, 0, secs, False)
        raise LLMError((p.stderr or p.stdout or "пустой ответ")[-300:])
    mu = d.get("modelUsage") or {}
    tin = sum(v.get("inputTokens", 0) + v.get("cacheReadInputTokens", 0) + v.get("cacheCreationInputTokens", 0) for v in mu.values())
    tout = sum(v.get("outputTokens", 0) for v in mu.values())
    cost = sum(v.get("costUSD", 0) for v in mu.values())
    store.log_usage(purpose, model, tin, tout, cost, secs, not d.get("is_error"))
    hub.publish({"type": "usage", "usage": store.usage_today()})
    if d.get("is_error"):
        raise LLMError(str(d.get("result"))[:300])
    log(f"llm {purpose} {model}: {tin} in / {tout} out, {secs:.1f}s")
    return parse_json(d.get("result", ""))
