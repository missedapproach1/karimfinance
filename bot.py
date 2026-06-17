"""
Точка входа финансового бота.
Запускает aiogram-поллинг + APScheduler (зарплата, напоминания, бэкап).
"""
import asyncio
import logging
import datetime
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

import config
import handlers
import assistant_handlers
import salary as sal
import finance as fin
import debts as debts_mod
import reports
from sheets import Sheets

# ---------- логирование ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")

bot: Bot = None
sheets: Sheets = None


# ============================================================
# ПЛАНИРОВЩИК
# ============================================================
async def auto_salary(period: str):
    """Авто-начисление аванса (period='avans') или зарплаты ('zarplata')."""
    try:
        today = datetime.date.today()
        settings = sheets.get_settings()
        oklad = int(settings.get("Оклад", 135000))
        premium = int(settings.get("Премия по умолчанию", 15000))
        cal = sheets.get_calendar()

        category = "Аванс" if period == "avans" else "Зарплата"

        # Идемпотентность: не дублируем если уже начислено сегодня
        if sheets.operation_exists_today(category):
            logger.info(f"{category} уже начислена сегодня — пропуск")
            return

        if period == "avans":
            # аванс за 1-15 текущего месяца
            amount = sal.calc_salary("avans", today.month, today.year, oklad, calendar_rows=cal)
        else:
            # зарплата за 16-конец ПРЕДЫДУЩЕГО месяца + премия
            prev_month = today.month - 1
            prev_year = today.year
            if prev_month < 1:
                prev_month = 12
                prev_year -= 1
            amount = sal.calc_salary("zarplata", prev_month, prev_year, oklad,
                                     premium=premium, calendar_rows=cal)

        if amount <= 0:
            logger.warning(f"Расчёт {category} дал 0 — пропуск")
            return

        new_balance = sheets.add_operation("Доход", category, amount, "авто-начисление")

        # распределение
        all_debts = sheets.get_debts()
        d2i = handlers.days_to_income(today)
        result = fin.distribute_income(amount, all_debts, settings,
                                       balance=new_balance - amount, today=today,
                                       days_to_next_income=max(1, d2i), min_daily_life=1000)
        text = f"🎉 Начислена {category.lower()}!\n\n" + handlers.format_distribution(result)
        await bot.send_message(config.OWNER_TELEGRAM_ID, text)
        logger.info(f"{category} начислена: {amount}")
    except Exception as e:
        logger.error(f"Ошибка авто-начисления {period}: {e}")
        try:
            await bot.send_message(config.OWNER_TELEGRAM_ID,
                                   f"⚠️ Не удалось авто-начислить {period}. Проверь бота.")
        except Exception:
            pass


async def daily_reminder():
    """Ежедневное напоминание о платежах на ближайшие 1-2 дня."""
    try:
        today = datetime.date.today()
        settings = sheets.get_settings()
        all_debts = sheets.get_debts()
        urgent = []

        # просрочки
        for d in all_debts:
            if str(d.get("просрочка", "")).upper() == "ДА" and d.get("остаток", 0) > 0:
                urgent.append(f"🔴 ПРОСРОЧКА {d['название']}: {int(d.get('платеж',0)) or int(d['остаток']):,} ₽")

        # фикс платежи на 1-2 дня
        for f in fin.upcoming_fixed_payments(settings, today, horizon_days=2):
            when = "сегодня" if f["дней_до"] == 0 else "завтра"
            urgent.append(f"🏠 {f['название']}: {f['сумма']:,} ₽ ({when})")

        # банковские платежи на 1-2 дня
        for d in all_debts:
            if str(d.get("категория", "")).lower() in ("кк", "мз") and d.get("остаток", 0) > 0:
                if str(d.get("просрочка", "")).upper() == "ДА":
                    continue
                day = int(d.get("день", 0))
                платеж = int(d.get("платеж", 0))
                if day and платеж and debts_mod.days_until_day(day, today) <= 2:
                    urgent.append(f"🟠 {d['название']}: {платеж:,} ₽")

        if urgent:
            text = "⏰ Напоминание о платежах:\n\n" + "\n".join(urgent)
            await bot.send_message(config.OWNER_TELEGRAM_ID, text)
            logger.info("Напоминание отправлено")
    except Exception as e:
        logger.error(f"Ошибка напоминания: {e}")


async def daily_backup():
    """Ежедневный бэкап операций + пересчёт приоритетов."""
    try:
        sheets.backup_operations()
        sheets.update_priorities()
    except Exception as e:
        logger.error(f"Ошибка бэкапа/приоритетов: {e}")



async def weekly_report():
    """Недельный текстовый отчёт (понедельник 12:00 за прошлую неделю)."""
    try:
        start, end = reports.last_week_range(datetime.date.today())
        ops = sheets.get_operations()
        agg = reports.aggregate_period(ops, {}, {}, start, end)
        # короткий ИИ-комментарий
        comment = ""
        try:
            import assistant
            data = {"баланс": sheets.get_last_balance(),
                    "общий_долг": debts_mod.total_debt(sheets.get_debts()),
                    "долги_топ": debts_mod.get_debts_sorted(sheets.get_debts())}
            txt = (f"Итоги недели: доход {agg['total_income']}, расход {agg['total_expense']}, "
                   f"на долги {agg['debt_payments']}. Дай ОДНО короткое предложение поддержки/совета.")
            r = await assistant.ask_assistant(txt, data, [])
            comment = r.get("reply", "")
        except Exception as e:
            logger.warning(f"weekly ai: {e}")
        text = reports.format_weekly_text(agg, comment)
        await bot.send_message(config.OWNER_TELEGRAM_ID, text)
        logger.info("Недельный отчёт отправлен")
    except Exception as e:
        logger.error(f"Ошибка недельного отчёта: {e}")


async def monthly_report():
    """Месячный PDF (последний день месяца 12:00)."""
    try:
        today = datetime.date.today()
        # проверка: сегодня последний день месяца?
        import calendar as _cal
        last_day = _cal.monthrange(today.year, today.month)[1]
        if today.day != last_day:
            return
        start, end = reports.current_month_range(today)
        ops = sheets.get_operations()
        agg = reports.aggregate_period(ops, {}, {}, start, end)
        all_debts = sheets.get_debts()
        debts_summary = {
            "total_after": debts_mod.total_debt(all_debts),
            "people_after": debts_mod.total_people_debt(all_debts),
            "closed": [],
        }
        # ИИ-комментарий
        comment = ""
        try:
            import assistant
            data = {"баланс": sheets.get_last_balance(),
                    "общий_долг": debts_mod.total_debt(all_debts),
                    "долг_людям": debts_mod.total_people_debt(all_debts),
                    "долги_топ": debts_mod.get_debts_sorted(all_debts)}
            txt = (f"Итоги месяца: доход {agg['total_income']}, расход {agg['total_expense']}, "
                   f"на долги {agg['debt_payments']}, остаток долга {debts_summary['total_after']}. "
                   f"Дай разбор месяца в 2-3 коротких абзацах: что хорошо, на чём сфокусироваться.")
            r = await assistant.ask_assistant(txt, data, [])
            comment = r.get("reply", "")
        except Exception as e:
            logger.warning(f"monthly ai: {e}")
        path = "/app/data/monthly_report.pdf"
        try:
            reports.build_monthly_pdf(agg, debts_summary, comment, path)
            from aiogram.types import FSInputFile
            await bot.send_document(config.OWNER_TELEGRAM_ID, FSInputFile(path),
                                    caption=f"📊 Финансовый отчёт за месяц")
        except Exception as e:
            logger.error(f"PDF ошибка: {e}")
            # fallback текстом
            await bot.send_message(config.OWNER_TELEGRAM_ID,
                                   reports.format_weekly_text(agg, comment))
        logger.info("Месячный отчёт отправлен")
    except Exception as e:
        logger.error(f"Ошибка месячного отчёта: {e}")


def setup_scheduler():
    tz = ZoneInfo(config.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)
    # Аванс 16 числа 12:00
    scheduler.add_job(auto_salary, CronTrigger(day=16, hour=12, minute=0, timezone=tz),
                      args=["avans"], id="avans", misfire_grace_time=3600)
    # Зарплата 1 числа 12:00
    scheduler.add_job(auto_salary, CronTrigger(day=1, hour=12, minute=0, timezone=tz),
                      args=["zarplata"], id="zarplata", misfire_grace_time=3600)
    # Напоминание каждый день 10:00
    scheduler.add_job(daily_reminder, CronTrigger(hour=10, minute=0, timezone=tz),
                      id="reminder", misfire_grace_time=3600)
    # Недельный отчёт: понедельник 12:00
    scheduler.add_job(weekly_report, CronTrigger(day_of_week="mon", hour=12, minute=0, timezone=tz),
                      id="weekly", misfire_grace_time=3600)
    # Месячный отчёт: проверка каждый день в 12:00 (внутри проверяет последний ли день)
    scheduler.add_job(monthly_report, CronTrigger(hour=12, minute=0, timezone=tz),
                      id="monthly", misfire_grace_time=3600)
    # Бэкап каждый день 03:00
    scheduler.add_job(daily_backup, CronTrigger(hour=3, minute=0, timezone=tz),
                      id="backup", misfire_grace_time=3600)
    scheduler.start()
    logger.info("Планировщик запущен (зарплата, напоминания, бэкап)")
    return scheduler


# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    global bot, sheets

    # проверка конфигурации
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"КОНФИГ: {e}")
        print("\n❌ Исправь ошибки в .env и перезапусти:")
        for e in errors:
            print(f"  - {e}")
        return

    # подключение к Google
    try:
        sheets = Sheets()
        sheets.init_sheets()
        logger.info("Google Sheets подключён, листы готовы")
    except Exception as e:
        logger.error(f"Не удалось подключиться к Google Sheets: {e}")
        print(f"\n❌ Ошибка Google Sheets: {e}")
        print("Проверь credentials.json и что робот добавлен в таблицу как редактор.")
        return

    # внедряем sheets в хендлеры
    handlers.set_sheets(sheets)

    # бот
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(assistant_handlers.arouter)
    dp.include_router(handlers.router)

    # планировщик
    setup_scheduler()

    # старт-уведомление владельцу
    try:
        await bot.send_message(config.OWNER_TELEGRAM_ID, "✅ Бот запущен и готов к работе. /start")
    except Exception as e:
        logger.warning(f"Не удалось отправить старт-уведомление: {e}")

    logger.info("Бот запущен, начинаю поллинг")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
