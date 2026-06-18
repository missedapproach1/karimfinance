"""Хендлеры помощника."""
import logging
import datetime
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config
import assistant
import debts as debts_mod
import finance as fin
import handlers as H

logger = logging.getLogger(__name__)
arouter = Router()
CONFIRM_THRESHOLD = assistant.CONFIRM_THRESHOLD


class AssistantFSM(StatesGroup):
    chatting = State()
    confirm = State()


def _kb_confirm():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, выполни", callback_data="asst_yes")
    b.button(text="❌ Отмена", callback_data="asst_no")
    b.adjust(2)
    return b.as_markup()


def _kb_exit():
    b = InlineKeyboardBuilder()
    b.button(text="🚪 Выйти из диалога", callback_data="home")
    return b.as_markup()


def _build_data():
    today = datetime.date.today()
    balance = H.SHEETS.get_last_balance()
    settings = H.SHEETS.get_settings()
    all_debts = H.SHEETS.get_debts()
    sd = debts_mod.get_debts_sorted(all_debts, today)
    obl = fin.remaining_obligations_this_period(settings, all_debts)
    d2i = H.days_to_income()
    free = balance - obl
    return {"баланс": balance, "дней_до_дохода": d2i, "на_жизнь": max(0, free),
            "общий_долг": debts_mod.total_debt(all_debts),
            "долг_людям": debts_mod.total_people_debt(all_debts), "долги_топ": sd}


@arouter.callback_query(F.data == "assistant")
async def cb_assistant(cq: CallbackQuery, state: FSMContext):
    if not H.is_owner(cq.from_user.id):
        return await H.deny(cq)
    await state.set_state(AssistantFSM.chatting)
    await state.update_data(history=[])
    await cq.message.edit_text(
        "💬 Помощник на связи.\n\nПиши или диктуй голосом: что хочешь сделать, спланировать, спроси совет. "
        "Например: «хочу послезавтра скинуть Наташе 20к, что думаешь?» или «запиши расход 800 на еду».",
        reply_markup=_kb_exit())
    await cq.answer()


@arouter.callback_query(AssistantFSM.confirm, F.data == "asst_yes")
async def cb_yes(cq: CallbackQuery, state: FSMContext):
    if not H.is_owner(cq.from_user.id):
        return await H.deny(cq)
    d = await state.get_data()
    action = d.get("pending_action")
    await state.set_state(AssistantFSM.chatting)
    await state.update_data(pending_action=None)
    if not action:
        await cq.message.edit_text("Нечего выполнять.", reply_markup=_kb_exit())
        return await cq.answer()
    res = await _execute(action)
    await cq.message.edit_text(res, reply_markup=_kb_exit())
    await cq.answer()


@arouter.callback_query(AssistantFSM.confirm, F.data == "asst_no")
async def cb_no(cq: CallbackQuery, state: FSMContext):
    if not H.is_owner(cq.from_user.id):
        return await H.deny(cq)
    await state.set_state(AssistantFSM.chatting)
    await state.update_data(pending_action=None)
    await cq.message.edit_text("Отменил. Что-нибудь ещё?", reply_markup=_kb_exit())
    await cq.answer()


@arouter.message(AssistantFSM.chatting, F.text)
async def a_text(message: Message, state: FSMContext):
    if not H.is_owner(message.from_user.id):
        return await H.deny(message)
    await _process(message, state, message.text.strip())


@arouter.message(AssistantFSM.chatting, F.voice)
async def a_voice(message: Message, state: FSMContext):
    if not H.is_owner(message.from_user.id):
        return await H.deny(message)
    try:
        bot = message.bot
        file = await bot.get_file(message.voice.file_id)
        buf = await bot.download_file(file.file_path)
        text = await assistant.transcribe_voice(buf.read())
    except Exception as e:
        logger.error(f"voice err: {e}")
        return await message.answer("Не смог распознать. Напиши текстом.", reply_markup=_kb_exit())
    if not text:
        return await message.answer("Не разобрал. Ещё раз или текстом.", reply_markup=_kb_exit())
    await _process(message, state, text)


async def _process(message: Message, state: FSMContext, text: str):
    try:
        data = _build_data()
    except Exception as e:
        logger.error(f"data err: {e}")
        return await message.answer("⚠️ Google недоступен.", reply_markup=_kb_exit())
    st = await state.get_data()
    history = st.get("history", [])
    res = await assistant.ask_assistant(text, data, history)
    reply = res.get("reply", "")
    action = res.get("action")
    history = history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    await state.update_data(history=history[-12:])
    if not action:
        return await message.answer(reply, reply_markup=_kb_exit())
    summary = _describe(action)
    amount = abs(int(action.get("amount", 0) or 0))
    needs = amount >= CONFIRM_THRESHOLD or action.get("type") in ("pay_debt", "set_setting")
    if needs:
        await state.set_state(AssistantFSM.confirm)
        await state.update_data(pending_action=action)
        await message.answer(f"{reply}\n\n🔸 {summary}\nВыполнить?", reply_markup=_kb_confirm())
    else:
        out = await _execute(action)
        await message.answer(f"{reply}\n\n{out}", reply_markup=_kb_exit())


def _describe(a):
    t = a.get("type")
    amt = int(a.get("amount", 0) or 0)
    if t == "add_income":
        return f"Записать ДОХОД {amt:,} ₽ ({a.get('category','Прочее')})"
    if t == "add_expense":
        return f"Записать РАСХОД {amt:,} ₽ ({a.get('category','Прочее')})"
    if t == "pay_debt":
        return f"Погасить «{a.get('debt_name','?')}» на {amt:,} ₽"
    if t == "set_balance":
        return f"Выставить баланс {amt:,} ₽"
    if t == "set_setting":
        return f"Изменить «{a.get('param','?')}» на {a.get('value','?')}"
    return "Действие"


async def _execute(a):
    t = a.get("type")
    try:
        if t == "add_income":
            amt = abs(int(a.get("amount", 0) or 0)); cat = a.get("category", "Прочее")
            bal = H.SHEETS.add_operation("Доход", cat, amt, "через помощника")
            return f"✅ Доход {amt:,} ₽ записан. Баланс: {bal:,} ₽"
        if t == "add_expense":
            amt = abs(int(a.get("amount", 0) or 0)); cat = a.get("category", "Прочее")
            bal = H.SHEETS.add_operation("Расход", cat, -amt, "через помощника")
            return f"✅ Расход {amt:,} ₽ ({cat}) записан. Баланс: {bal:,} ₽"
        if t == "pay_debt":
            amt = abs(int(a.get("amount", 0) or 0)); name = a.get("debt_name", "")
            bal = H.SHEETS.add_operation("Расход", "Долги/кредиты", -amt, f"погашение: {name}")
            rem = H.SHEETS.reduce_debt(name, amt)
            txt = f"✅ Погашено {amt:,} ₽ по «{name}». Остаток: {int(rem):,} ₽. Баланс: {bal:,} ₽"
            if rem == 0:
                txt += f"\n🎉 «{name}» закрыт!"
            return txt
        if t == "set_balance":
            amt = abs(int(a.get("amount", 0) or 0))
            r = H.SHEETS.set_balance(amt)
            if r["diff"] == 0:
                return f"✅ Баланс уже точный: {r['new']:,} ₽"
            return f"✅ Баланс: {r['new']:,} ₽ (корректировка {r['diff']:+,} ₽)"
        if t == "set_setting":
            H.SHEETS.update_setting(a.get("param",""), a.get("value",""))
            return f"✅ «{a.get('param','')}» = {a.get('value','')}"
        return "Неизвестное действие."
    except Exception as e:
        logger.error(f"exec err {t}: {e}")
        return "⚠️ Не удалось выполнить. Попробуй через кнопки меню."
