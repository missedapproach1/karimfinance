"""Хендлеры помощника — только запись расходов и вопросы по тратам."""
import logging
import datetime
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import assistant
import categories as cat_mod
import stats as stats_mod
import handlers as H

logger = logging.getLogger(__name__)
arouter = Router()
CONFIRM_THRESHOLD = 5000  # расход крупнее — переспросить (защита от опечатки/недослыша)


class AssistantFSM(StatesGroup):
    chatting = State()
    confirm = State()


def _kb_confirm():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, запиши", callback_data="asst_yes")
    b.button(text="❌ Отмена", callback_data="asst_no")
    b.adjust(2)
    return b.as_markup()


def _kb_exit():
    b = InlineKeyboardBuilder()
    b.button(text="🚪 Выйти в меню", callback_data="home")
    return b.as_markup()


def _build_data():
    ops = H.SHEETS.get_operations()
    return stats_mod.month_to_date(ops, datetime.date.today())


@arouter.callback_query(F.data == "assistant")
async def cb_assistant(cq: CallbackQuery, state: FSMContext):
    if not H.is_owner(cq.from_user.id):
        return await H.deny(cq)
    await state.set_state(AssistantFSM.chatting)
    await state.update_data(history=[])
    await cq.message.edit_text(
        "💬 Помощник на связи.\n\nПиши или диктуй: записать трату или спросить по расходам. "
        "Например: «потратил 800 на доставку» или «сколько ушло на еду в этом месяце?»",
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
        await cq.message.edit_text("Нечего записывать.", reply_markup=_kb_exit())
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
    if not action or action.get("type") != "add_expense":
        return await message.answer(reply or "Готово.", reply_markup=_kb_exit())
    amount = abs(int(action.get("amount", 0) or 0))
    if amount >= CONFIRM_THRESHOLD:
        await state.set_state(AssistantFSM.confirm)
        await state.update_data(pending_action=action)
        await message.answer(f"{reply}\n\n🔸 {_describe(action)}\nЗаписать?", reply_markup=_kb_confirm())
    else:
        out = await _execute(action)
        await message.answer(f"{reply}\n\n{out}", reply_markup=_kb_exit())


def _describe(a):
    amt = abs(int(a.get("amount", 0) or 0))
    full = cat_mod.full_name(a.get("category", "Покупки"), a.get("sub"))
    return f"Расход {amt:,} ₽ ({full})"


async def _execute(a):
    try:
        amt = abs(int(a.get("amount", 0) or 0))
        catn = a.get("category", "Покупки")
        sub = a.get("sub")
        note = a.get("note", "") or ""
        full = cat_mod.full_name(catn, sub if sub else None)
        H.SHEETS.add_operation("Расход", full, -amt, note)
        return f"✅ Записал: {amt:,} ₽ — {full}"
    except Exception as e:
        logger.error(f"exec err: {e}")
        return "⚠️ Не удалось записать. Попробуй через кнопку «Расход»."
