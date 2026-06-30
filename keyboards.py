"""Клавиатуры бота (inline) — только расходы."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import categories as cat


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💸 Расход", callback_data="expense")
    b.button(text="📊 Статистика с начала месяца", callback_data="stats")
    b.button(text="💬 Помощник", callback_data="assistant")
    b.adjust(1)
    return b.as_markup()


def expense_categories() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ci, c in enumerate(cat.category_list()):
        b.button(text=c, callback_data=f"ecat:{ci}")
    b.button(text="« Назад", callback_data="home")
    b.adjust(2, 2, 1, 1)
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


def back_home() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="« В меню", callback_data="home")
    return b.as_markup()
