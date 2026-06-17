"""Диалоговый помощник."""
import json
import logging
import httpx
import config

logger = logging.getLogger(__name__)
CONFIRM_THRESHOLD = 5000

BOT_KNOWLEDGE = """
ФУНКЦИОНАЛ БОТА:
- 💰 Доход — записать доход (Такси/Зарплата/Родители/Прочее), бот сам покажет распределение.
- 💸 Расход — трата по категории (Еда, Каршеринг, Метро, Аренда, Связь, Долги/кредиты, Разработка, Озон, Прочее).
- 📊 Сколько есть — баланс и свободно на жизнь.
- 🍔 Остаток на категорию — потрачено за месяц.
- ⚠️ Что горит — ближайшие платежи и просрочки.
- 🤖 Совет — финансовый совет.
- 📋 Мои долги — долги по приоритету.
- ⚙️ Настройки — оклад, премия, аренда, связь.
- 🔄 Выставить баланс — подогнать под реальную сумму.
Зарплата авто 1 и 16 числа. Все деньги в одном кошельке, рубли. Долги гасить: просрочки -> дорогие микрозаймы -> банки -> беспроцентные людям.
"""

SYSTEM_PROMPT = """Ты — личный финансовый помощник в Telegram-боте. Пользователь пишет текстом или голосом. Помогай коротко и по делу.
""" + BOT_KNOWLEDGE + """
ПРАВИЛА:
- КОРОТКО, 2-3 абзаца макс, без воды.
- Тон спокойный, на стороне человека. У него долги, много работает.
- Используй ТОЛЬКО данные что дали, не выдумывай цифры.
- "Как сделать X" — объясни какую кнопку нажать.
- Хочет записать операцию — предложи в поле action.
ДЕЙСТВИЯ (бот выполнит сам):
- add_income: amount, category
- add_expense: amount, category
- pay_debt: amount, debt_name
- set_balance: amount
- set_setting: param, value
ОГРАНИЧЕНИЯ: только эти действия, ничего не удалять/чистить. Не уверен — переспроси, не предлагай action. Одно действие за раз.
ФОРМАТ — строго JSON без markdown:
{"reply": "ответ", "action": null или {"type":"add_expense","amount":500,"category":"Еда"}}
"""


def _build_context(data):
    lines = ["ДАННЫЕ:", f"Баланс: {data.get('баланс',0):,} руб",
             f"Свободно: {data.get('на_жизнь',0):,} руб, дней до дохода {data.get('дней_до_дохода','?')}",
             f"Долг всего: {data.get('общий_долг',0):,} (людям {data.get('долг_людям',0):,})"]
    for d in data.get("долги_топ", [])[:8]:
        p = " ПРОСРОЧКА" if str(d.get("просрочка","")).upper()=="ДА" else ""
        lines.append(f"  - {d['название']}: {int(d['остаток']):,} руб, {int(d.get('ставка',0))}%{p}")
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
        {"x-api-key": config.LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"Authorization": f"Bearer {config.LLM_API_KEY}", "anthropic-version": "2023-06-01", "content-type": "application/json"},
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
                text = "".join(p.get("text","") for p in parts if p.get("type")=="text").strip()
                return _parse(text)
            except Exception as e:
                logger.warning(f"assistant err: {e}")
                continue
    return {"reply": "Не удалось связаться, попробуй ещё.", "action": None}


def _parse(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        o = json.loads(t)
        a = o.get("action")
        if a and not isinstance(a, dict):
            a = None
        return {"reply": str(o.get("reply","")).strip() or "Готово.", "action": a}
    except Exception:
        return {"reply": text, "action": None}


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
            return r.json().get("text","").strip()
    except Exception as e:
        logger.warning(f"transcribe err: {e}")
        return ""
