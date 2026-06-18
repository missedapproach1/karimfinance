"""Умная категоризация 'прочих' расходов через LLM."""
import json
import logging
import httpx
import config

logger = logging.getLogger(__name__)

SYS = """Ты классифицируешь расход по смыслу. Дано: категория, описание траты от пользователя, и список уже существующих подкатегорий-граф внутри этой категории.

Задача: определить, к какой подкатегории отнести трату.
- Если трата по смыслу подходит к одной из существующих граф — верни её.
- Если похожей нет — придумай КОРОТКОЕ название новой графы (1-3 слова), обобщающее, чтобы под него попадали похожие будущие траты.

Примеры обобщения:
- "сшить диплом", "распечатать диплом", "букет преподавателю" -> "Университет"
- "зарядка для телефона", "наушники" -> "Электроника"
- "заплатил за парковку" -> "Парковка"

Отвечай СТРОГО JSON без markdown:
{"sub": "Название графы"}
"""


async def categorize_other(category, description, existing_subs):
    if not config.LLM_API_KEY:
        return "Прочее"
    existing = ", ".join(existing_subs) if existing_subs else "(пока нет)"
    user = (f"Категория: {category}\n"
            f"Существующие графы: {existing}\n"
            f"Описание траты: {description}\n\n"
            f"К какой графе отнести? Верни JSON.")
    url = f"{config.LLM_BASE_URL}/v1/messages"
    body = {"model": config.LLM_MODEL, "max_tokens": 100, "system": SYS,
            "messages": [{"role": "user", "content": user}]}
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}",
               "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            parts = r.json().get("content", [])
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            t = text.strip()
            if t.startswith("```"):
                t = t.strip("`")
                if t.lower().startswith("json"):
                    t = t[4:]
                t = t.strip()
            obj = json.loads(t)
            sub = str(obj.get("sub", "")).strip()
            return sub or "Прочее"
    except Exception as e:
        logger.warning(f"categorize err: {e}")
        return "Прочее"


def existing_subs_from_operations(operations, category):
    found = set()
    prefix = category + " / "
    for op in operations:
        c = str(op.get("категория", ""))
        if c.startswith(prefix):
            sub = c[len(prefix):].strip()
            if sub:
                found.add(sub)
    return sorted(found)
