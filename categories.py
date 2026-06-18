"""Двухуровневые категории расходов."""

CATEGORIES = {
    "Еда": {
        "subs": ["Доставка", "Чайхана/шаурма", "Продуктовый", "Кофейня", "Рестораны/кафе"],
        "llm": True,
    },
    "Курение": {"subs": [], "llm": False},
    "Транспорт": {
        "subs": ["Каршеринг", "Метро", "Такси", "Самокаты"],
        "llm": True,
    },
    "Платежи": {
        "subs": ["Аренда", "Связь", "Штрафы", "Долги/кредиты", "Подписки"],
        "llm": True,
    },
    "Покупки": {
        "subs": ["Озон", "Одежда", "Бытовые товары и услуги", "Здоровье/аптека"],
        "llm": True,
    },
    "Развлечения": {"subs": [], "llm": False},
}


def category_list():
    return list(CATEGORIES.keys())


def subs_of(category):
    return CATEGORIES.get(category, {}).get("subs", [])


def has_llm(category):
    return CATEGORIES.get(category, {}).get("llm", False)


def full_name(category, sub=None):
    if sub:
        return f"{category} / {sub}"
    return category
