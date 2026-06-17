"""
LLM-советник через ProxyAPI (формат Anthropic Messages API).
LLM НЕ считает деньги — только переформулирует готовые цифры по-человечески.
При недоступности LLM — graceful fallback на сухие цифры.
"""
import logging
import httpx

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — личный финансовый помощник. Тебе дают ТОЧНЫЕ цифры о финансах человека (баланс, долги, платежи). Твоя задача — коротко, по-человечески объяснить ситуацию и дать совет.

ПРАВИЛА:
- Пиши КОРОТКО. Максимум 3-4 небольших абзаца. Никаких простыней.
- Не выдумывай цифры. Используй ТОЛЬКО те числа, что тебе дали.
- Не считай сам — все расчёты уже сделаны, тебе дан готовый результат.
- Тон: спокойный, поддерживающий, на стороне человека. Без морализаторства и без паники.
- Говори конкретно: что сделать в первую очередь, на чём сфокусироваться.
- У человека долги, он много работает (основная работа + такси по выходным). Поддержи, но без сюсюканья.
- Пиши на русском, простым языком, можно с лёгкой прямотой.
- Не используй обращения вроде "дорогой" или эмодзи в избытке. 1-2 эмодзи максимум."""


def _build_user_message(data: dict) -> str:
    """Собирает сообщение с готовыми цифрами для LLM."""
    lines = []
    lines.append(f"Баланс сейчас: {data.get('баланс', 0):,} ₽")
    lines.append(f"Дней до следующего дохода: {data.get('дней_до_дохода', '?')}")
    lines.append(f"Свободно на жизнь до дохода: {data.get('на_жизнь', 0):,} ₽")
    if data.get("дефицит", 0) > 0:
        lines.append(f"ДЕФИЦИТ (не хватает на обязательное): {data['дефицит']:,} ₽")
    lines.append("")
    lines.append(f"Общий долг: {data.get('общий_долг', 0):,} ₽")
    lines.append(f"  из них людям: {data.get('долг_людям', 0):,} ₽")
    lines.append(f"  ежемесячные платежи банкам/МФО: {data.get('банк_в_мес', 0):,} ₽")
    lines.append("")
    долги = data.get("долги_топ", [])
    if долги:
        lines.append("Долги по приоритету (что гасить первым):")
        for d in долги[:6]:
            пометка = " [ПРОСРОЧКА]" if str(d.get("просрочка", "")).upper() == "ДА" else ""
            lines.append(f"  - {d['название']}: остаток {int(d['остаток']):,} ₽, "
                         f"ставка {int(d.get('ставка', 0))}%{пометка}")
    горит = data.get("что_горит", [])
    if горит:
        lines.append("")
        lines.append("Ближайшие платежи:")
        for g in горит[:6]:
            lines.append(f"  - {g}")
    lines.append("")
    lines.append("Дай короткий совет: на чём сейчас сфокусироваться, что сделать в первую очередь.")
    return "\n".join(lines)


def _fallback(data: dict) -> str:
    """Сухие цифры, если LLM недоступен."""
    lines = ["📊 Сводка (совет недоступен, вот цифры):", ""]
    lines.append(f"💰 Баланс: {data.get('баланс', 0):,} ₽")
    lines.append(f"💵 На жизнь до дохода: {data.get('на_жизнь', 0):,} ₽ ({data.get('дней_до_дохода','?')} дн)")
    if data.get("дефицит", 0) > 0:
        lines.append(f"⚠️ Не хватает: {data['дефицит']:,} ₽ — добери в такси/у родителей")
    lines.append(f"🔴 Общий долг: {data.get('общий_долг', 0):,} ₽")
    долги = data.get("долги_топ", [])
    if долги:
        lines.append("")
        lines.append("Гасить в первую очередь:")
        for d in долги[:4]:
            пометка = " (просрочка!)" if str(d.get("просрочка", "")).upper() == "ДА" else ""
            lines.append(f"• {d['название']}: {int(d['остаток']):,} ₽{пометка}")
    return "\n".join(lines)


async def get_advice(data: dict) -> str:
    """
    Запрашивает совет у LLM. data — словарь с готовыми цифрами.
    При любой ошибке/отсутствии ключа возвращает fallback.
    """
    if not config.LLM_API_KEY:
        logger.info("LLM_API_KEY пуст — используется fallback")
        return _fallback(data)

    url = f"{config.LLM_BASE_URL}/v1/messages"
    body = {
        "model": config.LLM_MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _build_user_message(data)}],
    }

    # Пробуем два варианта авторизации: сначала x-api-key (нативный Anthropic),
    # затем Authorization: Bearer. ProxyAPI принимает ключ — какой именно заголовок,
    # зависит от их настройки; код устойчив к обоим.
    auth_variants = [
        {"x-api-key": config.LLM_API_KEY, "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
        {"Authorization": f"Bearer {config.LLM_API_KEY}", "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        last_err = None
        for headers in auth_variants:
            try:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code in (401, 403):
                    last_err = f"auth {resp.status_code}"
                    logger.warning(f"LLM авторизация не прошла ({resp.status_code}), пробую другой заголовок")
                    continue
                resp.raise_for_status()
                data_resp = resp.json()
                # Anthropic формат: content[].text
                parts = data_resp.get("content", [])
                text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
                if text.strip():
                    return text.strip()
                last_err = "пустой ответ"
            except Exception as e:
                last_err = str(e)
                logger.warning(f"LLM ошибка: {e}")
                continue
        logger.error(f"LLM недоступен ({last_err}) — fallback")
        return _fallback(data)
