"""Точка входа: учёт расходов. Планировщик — текстовые отчёты."""
import asyncio
import logging
import sys
import datetime
import calendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

import config

# Сначала проверяем конфиг, и только потом импортируем модули, которые лезут в Google
_errs = config.validate()
if _errs:
    for e in _errs:
        logger.error(f"КОНФИГ: {e}")
    print("❌ Исправь переменные окружения и перезапусти:")
    for e in _errs:
        print(f"  - {e}")
    sys.exit(1)

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import handlers
import assistant_handlers
import assistant
import stats

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(config.TIMEZONE)
except Exception:
    TZ = None

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


# ---------- отчёты ----------
async def weekly_report():
    try:
        start, end = stats.last_week_range(datetime.date.today())
        ops = handlers.SHEETS.get_operations()
        agg = stats.aggregate_expenses(ops, start, end)
        await bot.send_message(config.OWNER_TELEGRAM_ID, stats.format_weekly(agg))
        logger.info("Недельный отчёт отправлен")
    except Exception as e:
        logger.error(f"Ошибка недельного отчёта: {e}")


async def monthly_report():
    try:
        today = datetime.date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        if today.day != last_day:
            return
        start, end = stats.current_month_range(today)
        ops = handlers.SHEETS.get_operations()
        agg = stats.aggregate_expenses(ops, start, end)
        comment = ""
        try:
            data = stats.month_to_date(ops, today)
            prompt = (f"Итоги месяца по расходам: всего потрачено {agg['total']} руб, "
                      f"трат {agg['count']}. Дай короткий разбор в 2-3 предложениях: "
                      f"на что ушло больше всего и где реально поджаться. Без воды, по делу.")
            r = await assistant.ask_assistant(prompt, data, [])
            comment = r.get("reply", "")
        except Exception as e:
            logger.warning(f"monthly ai: {e}")
        await bot.send_message(config.OWNER_TELEGRAM_ID, stats.format_monthly(agg, comment))
        logger.info("Месячный отчёт отправлен")
    except Exception as e:
        logger.error(f"Ошибка месячного отчёта: {e}")


def setup_scheduler():
    scheduler = AsyncIOScheduler()
    # Недельный: понедельник 12:00 за прошлую неделю
    scheduler.add_job(weekly_report, CronTrigger(day_of_week="mon", hour=12, minute=0, timezone=TZ),
                      id="weekly", misfire_grace_time=3600)
    # Месячный: каждый день в 12:00 (внутри проверяет, последний ли день месяца)
    scheduler.add_job(monthly_report, CronTrigger(hour=12, minute=0, timezone=TZ),
                      id="monthly", misfire_grace_time=3600)
    scheduler.start()
    logger.info("Планировщик запущен (недельный + месячный отчёты)")


async def main():
    dp.include_router(assistant_handlers.arouter)
    dp.include_router(handlers.router)
    setup_scheduler()
    try:
        await bot.send_message(config.OWNER_TELEGRAM_ID, "✅ Бот запущен (учёт расходов)")
    except Exception as e:
        logger.warning(f"Не удалось отправить старт-уведомление: {e}")
    logger.info("Бот запущен, начинаю поллинг")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
