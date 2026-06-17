"""
Обработчики бота: меню, доход, расход, баланс, долги, советы, настройки.
Вся арифметика — в модулях finance/debts/salary. Здесь только UI и оркестрация.
"""
import logging
import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

import config
import keyboards as kb
import debts as debts_mod
import finance as fin
import salary as sal
import llm

logger = logging.getLogger(__name__)
router = Router()

# Sheets-объект внедряется извне (из bot.py) через set_sheets()
SHEETS = None


def set_sheets(sheets_obj):
    global SHEETS
    SHEETS = sheets_obj


# ---------- FSM состояния ----------
class IncomeFSM(StatesGroup):
    amount = State()


class ExpenseFSM(StatesGroup):
    amount = State()
    note = State()
    which_debt = State()


class SettingFSM(StatesGroup):
    value = State()


class BalanceFSM(StatesGroup):
    amount = State()


class CatRemainFSM(StatesGroup):
    pass


# ---------- проверка владельца ----------
def is_owner(user_id: int) -> bool:
    return user_id == config.OWNER_TELEGRAM_ID


async def deny(event):
    if isinstance(event, Message):
        await event.answer("Это персональный бот.")
    elif isinstance(event, CallbackQuery):
        await event.answer("Это персональный бот.", show_alert=True)


# ---------- вспомогательное: дней до дохода ----------
def days_to_income(today=None) -> int:
    if today is None:
        today = datetime.date.today()
    settings = SHEETS.get_settings()
    d_av = int(settings.get("День аванса", 16))
    d_zp = int(settings.get("День зарплаты", 1))
    pay_date, _ = sal.next_payday_from(today, d_av, d_zp)
    if pay_date:
        return max(1, (pay_date - today).days)
    return 14


# ---------- /start ----------
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    await state.clear()
    await message.answer(
        "💼 Привет! Я твой финансовый помощник.\n\n"
        "Записываю доходы и расходы, слежу за долгами и подсказываю, "
        "что и куда платить. Жми кнопки.",
        reply_markup=kb.main_menu(),
    )


# ---------- возврат в меню ----------
@router.callback_query(F.data == "home")
async def cb_home(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await state.clear()
    await cq.message.edit_text("💼 Главное меню:", reply_markup=kb.main_menu())
    await cq.answer()


# ============================================================
# ДОХОД
# ============================================================
@router.callback_query(F.data == "income")
async def cb_income(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await cq.message.edit_text("💰 Какой доход?", reply_markup=kb.income_types())
    await cq.answer()


@router.callback_query(F.data.startswith("inc_type:"))
async def cb_income_type(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    inc_type = cq.data.split(":", 1)[1]
    await state.update_data(inc_type=inc_type)
    await state.set_state(IncomeFSM.amount)
    await cq.message.edit_text(f"💰 {inc_type}\n\nВведи сумму в рублях (только число):")
    await cq.answer()


@router.message(IncomeFSM.amount)
async def income_amount(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        return await message.answer("Не понял сумму. Введи положительное число, например 8000:")
    data = await state.get_data()
    inc_type = data.get("inc_type", "Прочее")
    await state.clear()

    # Запись операции
    try:
        new_balance = SHEETS.add_operation("Доход", inc_type, amount, "")
    except Exception as e:
        logger.error(f"Ошибка записи дохода: {e}")
        return await message.answer("⚠️ Google недоступен, доход НЕ записан. Попробуй ещё раз.",
                                    reply_markup=kb.back_home())

    # Распределение
    try:
        all_debts = SHEETS.get_debts()
        settings = SHEETS.get_settings()
        d2i = days_to_income()
        result = fin.distribute_income(
            amount, all_debts, settings,
            balance=new_balance - amount, today=datetime.date.today(),
            days_to_next_income=d2i, min_daily_life=1000)
        text = format_distribution(result)
    except Exception as e:
        logger.error(f"Ошибка распределения: {e}")
        text = f"✅ Доход {amount:,} ₽ записан.\nБаланс: {new_balance:,} ₽"

    await message.answer(text, reply_markup=kb.back_home())


def format_distribution(r: dict) -> str:
    lines = [f"💰 Пришло {r['пришло']:,} ₽", f"Баланс теперь: {r['баланс_после']:,} ₽", ""]
    if r["план"]:
        lines.append("Раскидываю по приоритету:")
        emoji = {"просрочка": "🔴", "фикс": "🏠", "долг": "🟠", "люди": "👤"}
        for p in r["план"]:
            e = emoji.get(p["тип"], "•")
            lines.append(f"{e} {p['кому']} — {p['сколько']:,} ₽ ({p['почему']})")
        lines.append("")
    lines.append(f"💵 На жизнь останется: {r['на_жизнь']:,} ₽")
    lines.append(f"📅 До дохода: {r['дней_до_дохода']} дн (~{r['в_день']:,} ₽/день)")
    if r["дефицит"] > 0:
        lines.append("")
        lines.append(f"⚠️ Не хватает {r['дефицит']:,} ₽ на обязательное.")
        lines.append("Добери в такси в выходные или попроси у родителей.")
    return "\n".join(lines)


# ============================================================
# РАСХОД
# ============================================================
@router.callback_query(F.data == "expense")
async def cb_expense(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await cq.message.edit_text("💸 На что потратил?", reply_markup=kb.expense_categories())
    await cq.answer()


@router.callback_query(F.data.startswith("exp_cat:"))
async def cb_expense_cat(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    cat = cq.data.split(":", 1)[1]
    await state.update_data(exp_cat=cat)
    await state.set_state(ExpenseFSM.amount)
    await cq.message.edit_text(f"💸 {cat}\n\nВведи сумму в рублях:")
    await cq.answer()


@router.message(ExpenseFSM.amount)
async def expense_amount(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        return await message.answer("Не понял сумму. Введи положительное число:")
    data = await state.get_data()
    cat = data.get("exp_cat", "Прочее")
    await state.update_data(exp_amount=amount)

    # Если это погашение долга — спросить какой именно
    if cat == "Долги/кредиты":
        try:
            all_debts = SHEETS.get_debts()
        except Exception as e:
            logger.error(f"Ошибка чтения долгов: {e}")
            return await message.answer("⚠️ Google недоступен. Попробуй позже.", reply_markup=kb.back_home())
        await state.set_state(ExpenseFSM.which_debt)
        return await message.answer(
            f"Гасим {amount:,} ₽. Какой долг?",
            reply_markup=kb.debts_to_pay(all_debts))

    # Обычный расход — спросить заметку
    await state.set_state(ExpenseFSM.note)
    await message.answer("Добавь заметку или пропусти:", reply_markup=kb.skip_or_back())


@router.callback_query(ExpenseFSM.which_debt, F.data.startswith("paydebt:"))
async def cb_paydebt(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    debt_name = cq.data.split(":", 1)[1]
    data = await state.get_data()
    amount = data.get("exp_amount", 0)
    await state.clear()

    try:
        # записываем расход
        new_balance = SHEETS.add_operation("Расход", "Долги/кредиты", -amount, f"погашение: {debt_name}")
        # уменьшаем остаток долга
        new_remaining = SHEETS.reduce_debt(debt_name, amount)
    except Exception as e:
        logger.error(f"Ошибка погашения долга: {e}")
        return await cq.message.edit_text("⚠️ Ошибка записи. Попробуй ещё раз.", reply_markup=kb.back_home())

    txt = (f"✅ Погашено {amount:,} ₽ по долгу «{debt_name}»\n"
           f"Остаток по нему: {int(new_remaining):,} ₽\n"
           f"Баланс: {new_balance:,} ₽")
    if new_remaining == 0:
        txt += f"\n\n🎉 Долг «{debt_name}» закрыт полностью!"
    await cq.message.edit_text(txt, reply_markup=kb.back_home())
    await cq.answer()


@router.callback_query(ExpenseFSM.note, F.data == "skip_note")
async def cb_skip_note(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await finalize_expense(cq.message, state, note="", edit=True)
    await cq.answer()


@router.message(ExpenseFSM.note)
async def expense_note(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    await finalize_expense(message, state, note=message.text.strip(), edit=False)


async def finalize_expense(message: Message, state: FSMContext, note: str, edit: bool):
    data = await state.get_data()
    cat = data.get("exp_cat", "Прочее")
    amount = data.get("exp_amount", 0)
    await state.clear()
    try:
        new_balance = SHEETS.add_operation("Расход", cat, -amount, note)
    except Exception as e:
        logger.error(f"Ошибка записи расхода: {e}")
        msg = "⚠️ Google недоступен, расход НЕ записан. Попробуй ещё раз."
        return await (message.edit_text(msg, reply_markup=kb.back_home()) if edit
                      else message.answer(msg, reply_markup=kb.back_home()))
    txt = f"✅ Расход {amount:,} ₽ ({cat}) записан.\nБаланс: {new_balance:,} ₽"
    await (message.edit_text(txt, reply_markup=kb.back_home()) if edit
           else message.answer(txt, reply_markup=kb.back_home()))


# ============================================================
# СКОЛЬКО ЕСТЬ
# ============================================================
@router.callback_query(F.data == "balance")
async def cb_balance(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    try:
        balance = SHEETS.get_last_balance()
        settings = SHEETS.get_settings()
        all_debts = SHEETS.get_debts()
        obligations = fin.remaining_obligations_this_period(settings, all_debts)
        free = balance - obligations
        d2i = days_to_income()
        per_day = round(free / d2i) if d2i > 0 and free > 0 else 0
    except Exception as e:
        logger.error(f"Ошибка баланса: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())

    txt = (f"📊 Сейчас на карте: {balance:,} ₽\n\n"
           f"📉 Обязательного до конца месяца: {obligations:,} ₽\n"
           f"💵 Свободно на жизнь: {free:,} ₽\n"
           f"📅 До дохода: {d2i} дн")
    if per_day > 0:
        txt += f" (~{per_day:,} ₽/день)"
    if free < 0:
        txt += "\n\n⚠️ Обязательных платежей больше, чем на балансе. Нужен доход (такси/родители)."
    await cq.message.edit_text(txt, reply_markup=kb.back_home())
    await cq.answer()


# ============================================================
# ОСТАТОК НА КАТЕГОРИЮ
# ============================================================
@router.callback_query(F.data == "cat_remain")
async def cb_cat_remain(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await cq.message.edit_text("🍔 По какой категории?", reply_markup=kb.category_for_remain())
    await cq.answer()


@router.callback_query(F.data.startswith("rem_cat:"))
async def cb_rem_cat(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    cat = cq.data.split(":", 1)[1]
    try:
        ops = SHEETS.get_operations()
        spent = fin.spent_by_category_this_month(ops, cat)
    except Exception as e:
        logger.error(f"Ошибка категории: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())
    now = datetime.date.today()
    txt = (f"🍔 {cat} за {now.strftime('%B %Y')}:\n\n"
           f"Потрачено с 1 числа: {spent:,} ₽")
    await cq.message.edit_text(txt, reply_markup=kb.back_home())
    await cq.answer()


# ============================================================
# ЧТО ГОРИТ
# ============================================================
@router.callback_query(F.data == "whatburns")
async def cb_whatburns(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    try:
        items = build_whatburns()
    except Exception as e:
        logger.error(f"Ошибка 'что горит': {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())
    await cq.message.edit_text(items, reply_markup=kb.back_home())
    await cq.answer()


def build_whatburns() -> str:
    today = datetime.date.today()
    settings = SHEETS.get_settings()
    all_debts = SHEETS.get_debts()
    lines = ["⚠️ Ближайшее:", ""]

    # просрочки
    overdue = [d for d in all_debts if str(d.get("просрочка", "")).upper() == "ДА" and d.get("остаток", 0) > 0]
    for d in overdue:
        платеж = int(d.get("платеж", 0)) or int(d.get("остаток", 0))
        lines.append(f"🔴 ПРОСРОЧКА {d['название']}: {платеж:,} ₽")

    # фикс платежи в горизонте 10 дней
    fixed = fin.upcoming_fixed_payments(settings, today, horizon_days=10)
    for f in fixed:
        when = "сегодня" if f["дней_до"] == 0 else f"через {f['дней_до']} дн"
        lines.append(f"🏠 {f['название']}: {f['сумма']:,} ₽ ({when})")

    # банковские платежи в горизонте 7 дней
    for d in all_debts:
        if str(d.get("категория", "")).lower() in ("кк", "мз") and d.get("остаток", 0) > 0:
            if str(d.get("просрочка", "")).upper() == "ДА":
                continue
            day = int(d.get("день", 0))
            платеж = int(d.get("платеж", 0))
            if day and платеж:
                dd = debts_mod.days_until_day(day, today)
                if dd <= 7:
                    when = "сегодня" if dd == 0 else f"через {dd} дн"
                    lines.append(f"🟠 {d['название']}: {платеж:,} ₽ ({when})")

    # долги людям с ближайшим графиком или просрочкой
    for d in all_debts:
        if str(d.get("категория", "")).lower() == "человек" and d.get("остаток", 0) > 0:
            if str(d.get("просрочка", "")).upper() == "ДА":
                lines.append(f"👤 {d['название']} ждёт: {int(d.get('платеж',0)) or int(d['остаток']):,} ₽")
            else:
                day = int(d.get("день", 0))
                if day and debts_mod.days_until_day(day, today) <= 5:
                    lines.append(f"👤 {d['название']} по графику: {int(d.get('платеж',0)):,} ₽")

    if len(lines) <= 2:
        lines.append("Ничего срочного в ближайшие дни ✅")
    return "\n".join(lines)


# ============================================================
# СОВЕТ
# ============================================================
@router.callback_query(F.data == "advice")
async def cb_advice(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await cq.answer("Думаю...")
    try:
        data = build_advice_data()
    except Exception as e:
        logger.error(f"Ошибка сбора данных для совета: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())
    advice = await llm.get_advice(data)
    await cq.message.edit_text(f"🤖 {advice}", reply_markup=kb.back_home())


def build_advice_data() -> dict:
    today = datetime.date.today()
    balance = SHEETS.get_last_balance()
    settings = SHEETS.get_settings()
    all_debts = SHEETS.get_debts()
    sorted_debts = debts_mod.get_debts_sorted(all_debts, today)
    obligations = fin.remaining_obligations_this_period(settings, all_debts)
    d2i = days_to_income()
    free = balance - obligations
    return {
        "баланс": balance,
        "дней_до_дохода": d2i,
        "на_жизнь": max(0, free),
        "дефицит": max(0, -free),
        "общий_долг": debts_mod.total_debt(all_debts),
        "долг_людям": debts_mod.total_people_debt(all_debts),
        "банк_в_мес": debts_mod.total_bank_monthly(all_debts),
        "долги_топ": sorted_debts,
        "что_горит": _whatburns_short(settings, all_debts, today),
    }


def _whatburns_short(settings, all_debts, today) -> list:
    out = []
    for d in all_debts:
        if str(d.get("просрочка", "")).upper() == "ДА" and d.get("остаток", 0) > 0:
            out.append(f"{d['название']} просрочка {int(d.get('платеж',0)) or int(d['остаток']):,}₽")
    for f in fin.upcoming_fixed_payments(settings, today, horizon_days=7):
        out.append(f"{f['название']} {f['сумма']:,}₽ через {f['дней_до']}дн")
    return out


# ============================================================
# МОИ ДОЛГИ
# ============================================================
@router.callback_query(F.data == "mydebts")
async def cb_mydebts(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    try:
        all_debts = SHEETS.get_debts()
        sorted_debts = debts_mod.get_debts_sorted(all_debts, datetime.date.today())
    except Exception as e:
        logger.error(f"Ошибка долгов: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())

    lines = ["📋 Долги (по приоритету погашения):", ""]
    for d in sorted_debts:
        пометка = " 🔴просрочка" if str(d.get("просрочка", "")).upper() == "ДА" else ""
        ставка = f" {int(d['ставка'])}%" if d.get("ставка", 0) else ""
        lines.append(f"• {d['название']}: {int(d['остаток']):,} ₽{ставка} "
                     f"(платёж {int(d.get('день',0))}-го){пометка}")
    lines.append("")
    lines.append(f"🔴 Всего долг: {debts_mod.total_debt(all_debts):,} ₽")
    lines.append(f"👤 Из них людям: {debts_mod.total_people_debt(all_debts):,} ₽")
    lines.append(f"🏦 Банкам/МФО в месяц: {debts_mod.total_bank_monthly(all_debts):,} ₽")
    await cq.message.edit_text("\n".join(lines), reply_markup=kb.back_home())
    await cq.answer()


# ============================================================
# НАСТРОЙКИ
# ============================================================
@router.callback_query(F.data == "settings")
async def cb_settings(cq: CallbackQuery):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    try:
        settings = SHEETS.get_settings()
    except Exception as e:
        logger.error(f"Ошибка настроек: {e}")
        return await cq.message.edit_text("⚠️ Google недоступен.", reply_markup=kb.back_home())
    lines = ["⚙️ Текущие настройки:", ""]
    for p in ["Оклад", "Премия по умолчанию", "Аренда часть 1", "Аренда часть 2", "Связь", "Зал"]:
        v = settings.get(p, "—")
        lines.append(f"• {p}: {v:,} ₽" if isinstance(v, int) else f"• {p}: {v}")
    lines.append("")
    lines.append("Что изменить?")
    await cq.message.edit_text("\n".join(lines), reply_markup=kb.settings_params())
    await cq.answer()


@router.callback_query(F.data.startswith("setparam:"))
async def cb_setparam(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    param = cq.data.split(":", 1)[1]
    await state.update_data(param=param)
    await state.set_state(SettingFSM.value)
    await cq.message.edit_text(f"⚙️ {param}\n\nВведи новое значение (число):")
    await cq.answer()


@router.message(SettingFSM.value)
async def setting_value(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    value = parse_amount(message.text)
    if value is None:
        return await message.answer("Не понял число. Введи ещё раз:")
    data = await state.get_data()
    param = data.get("param")
    await state.clear()
    try:
        SHEETS.update_setting(param, value)
    except Exception as e:
        logger.error(f"Ошибка настройки: {e}")
        return await message.answer("⚠️ Google недоступен, не сохранено.", reply_markup=kb.back_home())
    await message.answer(f"✅ {param} = {value:,} ₽", reply_markup=kb.back_home())


@router.callback_query(F.data == "setbalance")
async def cb_setbalance(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id):
        return await deny(cq)
    await state.set_state(BalanceFSM.amount)
    cur = SHEETS.get_last_balance()
    await cq.message.edit_text(
        f"🔄 Сейчас в системе: {cur:,} ₽\n\nВведи реальный остаток с карты (число):")
    await cq.answer()


@router.message(BalanceFSM.amount)
async def balance_amount(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return await deny(message)
    val = parse_amount(message.text)
    if val is None or val < 0:
        return await message.answer("Не понял сумму. Введи число, например 35000:")
    await state.clear()
    try:
        r = SHEETS.set_balance(val)
    except Exception as e:
        logger.error(f"Ошибка выставления баланса: {e}")
        return await message.answer("⚠️ Google недоступен, не записано.", reply_markup=kb.back_home())
    if r["diff"] == 0:
        txt = f"✅ Баланс уже точный: {r['new']:,} ₽"
    elif r["small"]:
        txt = (f"✅ Баланс выставлен: {r['new']:,} ₽\n"
               f"Расхождение {r['diff']:+,} ₽ списано в корректировку.")
    else:
        txt = (f"✅ Баланс выставлен: {r['new']:,} ₽\n"
               f"⚠️ Крупное расхождение {r['diff']:+,} ₽ — записал и пометил.")
    await message.answer(txt, reply_markup=kb.back_home())


# ---------- утилита парсинга суммы ----------
def parse_amount(text: str):
    if not text:
        return None
    cleaned = text.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".").replace("₽", "").replace("р", "")
    try:
        return int(round(float(cleaned)))
    except ValueError:
        return None


# ---------- глобальный обработчик прочих сообщений ----------
@router.message()
async def fallback_message(message: Message):
    if not is_owner(message.from_user.id):
        return await deny(message)
    await message.answer("Не понял. Нажми /start или используй кнопки.", reply_markup=kb.main_menu())
