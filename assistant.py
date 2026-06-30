"""Диалоговый помощник — только расходы."""
import json
import logging
import httpx
import config
import categories as cat

logger = logging.getLogger(__name__)

BOT_KNOWLEDGE = """
ЭТО БОТ УЧЁТА РАСХОДОВ. Доходы, долги и баланс тут НЕ ведутся.
Кнопки: 💸 Расход (выбрать категорию и сумму), 📊 Статистика с начала месяца, 💬 Помощник (этот чат).
Категории расходов: Еда, Курение, Транспорт, Покупки, Развлечения.
"""

SYSTEM_PROMPT = ("""Ты — помощник по учёту расходов в Telegram-боте. Пользователь пишет текстом или диктует голосом. Отвечай коротко и по делу, без воды.
"""
    + BOT_KNOWLEDGE +
    """
ЧТО ТЫ МОЖЕШЬ:
1. Записать расход — если пользователь сказал, что потратил (например «потратил 800 на доставку», «350 сигареты»). Тогда верни action add_expense.
2. Ответить на вопрос про траты (сколько потрачено, на что больше всего и т.п.) — по данным, что дали. Не выдумывай цифры.

ДЕЙСТВИЕ (бот выполнит сам):
add_expense: amount (число, рубли), category (одна из: Еда, Курение, Транспорт, Покупки, Развлечения), sub (подкатегория словом или null), note (короткое описание или "")

ОГРАНИЧЕНИЯ: только запись расхода. Никаких доходов, долгов, баланса, удаления. Категорию выбирай ТОЛЬКО из списка выше. Не уверен в категории — ставь "Покупки" и опиши в note. Одно действие за раз.

ФОРМАТ — строго JSON без markdown:
{"reply": "короткий ответ", "action": null или {"type":"add_expense","amount":800,"category":"Еда","sub":"Доставка","note":""}}
""")


def _build_context(data):
    lines = ["РАСХОДЫ С НАЧАЛА МЕСЯЦА:",
             f"Всего: {data.get('total', 0):,} руб, трат: {data.get('count', 0)}"]
    by_cat = data.get("by_cat", {})
    if by_cat:
        lines.append("По категориям:")
        for c, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"  - {c}: {int(v):,} руб")
    return "\n".join(lines)


async def ask_assistant(user_text, data, history=None):
    if not config.LLM_API_KEY:
        return {"reply": "Помощник недоступен: нет ключа LLM_API_KEY.", "action": None}
    messages = []
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": f"{_build_context(data)}\n\nСООБЩЕНИЕ:\n{user_text}"})
    url = f"{config.LLM_BASE_URL}/v1/messages"
    body = {"model": config.LLM_MODEL, "max_tokens": 1024, "system": SYSTEM_PROMPT, "messages": messages}
    variants = [
        {"Authorization": f"Bearer {config.LLM_API_KEY}", "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"x-api-key": config.LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    ]
    async with httpx.AsyncClient(timeout=40.0) as client:
        for h in variants:
            try:
                r = await client.post(url, json=body, headers=h)
                if r.status_code in (401, 403):
                    continue
                if r.status_code >= 400:
                    logger.warning(f"assistant HTTP {r.status_code}: {r.text[:300]}")
                r.raise_for_status()
                parts = r.json().get("content", [])
                text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
                return _parse(text)
            except Exception as e:
                logger.warning(f"assistant err: {e}")
                continue
    return {"reply": "Не удалось связаться, попробуй ещё.", "action": None}


def _parse(text):
    import re as _re
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    obj = None
    try:
        obj = json.loads(t)
    except Exception:
        m = _re.search(r"\{.*\}", t, _re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if isinstance(obj, dict) and "reply" in obj:
        a = obj.get("action")
        if a and not isinstance(a, dict):
            a = None
        reply = str(obj.get("reply", "")).strip().replace("**", "").strip()
        return {"reply": reply or "Готово.", "action": a}
    clean = t.replace("**", "").strip()
    return {"reply": clean, "action": None}


async def transcribe_voice(file_bytes):
    if not config.LLM_API_KEY:
        return ""
    url = "https://api.proxyapi.ru/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    files = {"file": ("voice.ogg", file_bytes, "audio/ogg")}
    data = {"model": "whisper-1"}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, files=files, data=data)
            r.raise_for_status()
            return r.json().get("text", "").strip()
    except Exception as e:
        logger.warning(f"transcribe err: {e}")
        return ""
