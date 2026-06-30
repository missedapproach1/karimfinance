"""Хендлеры бота — только расходы и статистика."""
import logging
import re
import datetime
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

import config
import sheets
import keyboards as kb
import categories as cat_mod
import categorize as categorize_mod
import stats as stats_mod

logger = logging.getLogger(__name__)
router = Router()

# Единственное подключение к Google-таблице. Остальные модули берут handlers.SHEETS
SHEETS = sheets.Sheets()


# ---------- доступ ----------
def is_owner(uid: int) -> bool:
    return uid == config.OWNER_TELEGRAM_ID


async def deny(obj):
    if isinstance(obj, CallbackQuery):
        await obj.answer("Не для тебя 🙂", show_alert=True)
    else:
        await obj.answer("Этот бот личный.")


# ---------- парсинг суммы ----------
def parse_amount(text: str):
    if not text:
        return None
    t = text.strip().lower().replace(" ", "").replace(",", ".")
    mult = 1
    if t.endswith("к") or t.endswith("k"):
        mult = 1000
        t = t[:-1]
    m = re.match(r"^\d+(\.\d+)?$", t)
    if not m:
        return None
    try:
        return int(round(float(t) * mult))
    except Exception:
        return None


# ---------- состояния ----------
class ExpenseFSM(StatesGroup):
    amount = State()
    other_desc = State()


# ---------- старт / меню ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    await state.clear()
    await message.answer("💸 Учёт расходов. Выбирай:", reply_markup=kb.main_menu())


@router.callback_query(F.data == "home")
async def cb_home(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await state.clear()
    await cq.message.edit_text("💸 Учёт расходов. Выбирай:", reply_markup=kb.main_menu())
    await cq.answer()


# ---------- расход ----------
@router.callback_query(F.data == "expense")
async def cb_expense(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await state.clear()
    await cq.message.edit_text("💸 На что потратил?", reply_markup=kb.expense_categories())
    await cq.answer()


@router.callback_query(F.data.startswith("ecat:"))
async def cb_expense_cat(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    ci = int(cq.data.split(":", 1)[1])
    cats = cat_mod.category_list()
    if ci < 0 or ci >= len(cats):
        return await cq.answer()
    c = cats[ci]
    subs = cat_mod.subs_of(c)
    if not subs and not cat_mod.has_llm(c):
        await state.update_data(exp_cat=c, exp_sub=None)
        await state.set_state(ExpenseFSM.amount)
        await cq.message.edit_text(f"💸 {c}\n\nВведи сумму в рублях:")
        return await cq.answer()
    await cq.message.edit_text(f"💸 {c} — уточни:", reply_markup=kb.expense_subs(ci))
    await cq.answer()


@router.callback_query(F.data.startswith("esub:"))
async def cb_expense_sub(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    _, ci, si = cq.data.split(":")
    ci, si = int(ci), int(si)
    c = cat_mod.category_list()[ci]
    sub = cat_mod.subs_of(c)[si]
    await state.update_data(exp_cat=c, exp_sub=sub)
    await state.set_state(ExpenseFSM.amount)
    await cq.message.edit_text(f"💸 {c} / {sub}\n\nВведи сумму в рублях:")
    await cq.answer()


@router.callback_query(F.data.startswith("eoth:"))
async def cb_expense_other(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    ci = int(cq.data.split(":", 1)[1])
    c = cat_mod.category_list()[ci]
    await state.update_data(exp_cat=c, exp_sub="__OTHER__")
    await state.set_state(ExpenseFSM.amount)
    await cq.message.edit_text(f"💸 {c} / другое\n\nВведи сумму в рублях:")
    await cq.answer()


@router.message(ExpenseFSM.amount)
async def expense_amount(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        return await message.answer("Не понял сумму. Введи число, например 500:")
    data = await state.get_data()
    sub = data.get("exp_sub")
    await state.update_data(exp_amount=amount)
    if sub == "__OTHER__":
        await state.set_state(ExpenseFSM.other_desc)
        return await message.answer("На что именно? Напиши коротко (например: «зарядка для телефона»):")
    catn = data.get("exp_cat", "Прочее")
    await _finalize_expense(message, state, catn, sub, amount, note="")


@router.message(ExpenseFSM.other_desc)
async def expense_other_desc(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    desc = message.text.strip()
    data = await state.get_data()
    catn = data.get("exp_cat", "Прочее")
    amount = data.get("exp_amount", 0)
    try:
        ops = SHEETS.get_operations()
        existing = categorize_mod.existing_subs_from_operations(ops, catn)
    except Exception:
        existing = []
    sub = await categorize_mod.categorize_other(catn, desc, existing)
    await _finalize_expense(message, state, catn, sub, amount, note=desc)


async def _finalize_expense(message: Message, state: FSMContext, catn, sub, amount, note):
    await state.clear()
    real_sub = sub if (sub and sub != "__OTHER__") else None
    full_cat = cat_mod.full_name(catn, real_sub)
    try:
        SHEETS.add_operation("Расход", full_cat, -amount, note)
    except Exception as e:
        logger.error(f"exp err: {e}")
        await message.answer("⚠️ Google недоступен, расход НЕ записан.", reply_markup=kb.back_home())
        return
    await message.answer(f"✅ Записал: {amount:,} ₽ — {full_cat}")
    await message.answer("💸 Дальше:", reply_markup=kb.main_menu())


# ---------- статистика с начала месяца ----------
@router.callback_query(F.data == "stats")
async def cb_stats(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    try:
        ops = SHEETS.get_operations()
    except Exception as e:
        logger.error(f"stats err: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())
    agg = stats_mod.month_to_date(ops, datetime.date.today())
    await cq.message.edit_text(stats_mod.format_month_stats(agg), reply_markup=kb.back_home())
    await cq.answer()


# ---------- запасной хендлер свободного текста ----------
@router.message(F.text)
async def fallback_text(message: Message):
    if not is_owner(message.from_user.id):
        return await deny(message)
    await message.answer("Жми кнопку или зайди в 💬 Помощник, чтобы записать словами.",
                         reply_markup=kb.main_menu())
