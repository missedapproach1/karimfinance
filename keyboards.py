"""Клавиатуры бота (inline)."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import categories as cat


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 Доход", callback_data="income")
    b.button(text="💸 Расход", callback_data="expense")
    b.button(text="📊 Сколько есть", callback_data="balance")
    b.button(text="🍔 Остаток на категорию", callback_data="cat_remain")
    b.button(text="⚠️ Что горит", callback_data="whatburns")
    b.button(text="🤖 Совет", callback_data="advice")
    b.button(text="📋 Мои долги", callback_data="mydebts")
    b.button(text="⚙️ Настройки", callback_data="settings")
    b.button(text="🔄 Выставить баланс", callback_data="setbalance")
    b.button(text="💬 Помощник", callback_data="assistant")
    b.adjust(2, 2, 2, 2, 1, 1)
    return b.as_markup()


INCOME_TYPES = ["Такси", "Зарплата (вручную)", "Родители", "Прочее"]


def income_types() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in INCOME_TYPES:
        b.button(text=t, callback_data=f"inc_type:{t}")
    b.button(text="« Назад", callback_data="home")
    b.adjust(2, 2, 1)
    return b.as_markup()


def expense_categories() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ci, c in enumerate(cat.category_list()):
        b.button(text=c, callback_data=f"ecat:{ci}")
    b.button(text="« Назад", callback_data="home")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def expense_subs(ci: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    cats = cat.category_list()
    if ci < 0 or ci >= len(cats):
        b.button(text="« Назад", callback_data="expense")
        return b.as_markup()
    c = cats[ci]
    subs = cat.subs_of(c)
    for si, s in enumerate(subs):
        b.button(text=s, callback_data=f"esub:{ci}:{si}")
    if cat.has_llm(c):
        b.button(text="✏️ Другое (написать)", callback_data=f"eoth:{ci}")
    b.button(text="« Назад", callback_data="expense")
    n = len(subs) + (1 if cat.has_llm(c) else 0)
    rows = [2] * (n // 2)
    if n % 2:
        rows.append(1)
    rows.append(1)
    b.adjust(*rows)
    return b.as_markup()


def category_for_remain() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ci, c in enumerate(cat.category_list()):
        b.button(text=c, callback_data=f"rem_cat:{ci}")
    b.button(text="« Назад", callback_data="home")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def debts_to_pay(debts: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in debts:
        if d.get("остаток", 0) > 0:
            b.button(text=f"{d['название']} ({int(d['остаток']):,}₽)",
                     callback_data=f"paydebt:{d['название']}")
    b.button(text="« Отмена", callback_data="home")
    b.adjust(1)
    return b.as_markup()


def settings_params() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    params = ["Оклад", "Премия по умолчанию", "Аренда часть 1",
              "Аренда часть 2", "Связь", "Зал"]
    for p in params:
        b.button(text=p, callback_data=f"setparam:{p}")
    b.button(text="« Назад", callback_data="home")
    b.adjust(1)
    return b.as_markup()


def back_home() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="« В меню", callback_data="home")
    return b.as_markup()
