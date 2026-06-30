"""Агрегация расходов: статистика с начала месяца + текстовые отчёты (неделя/месяц)."""
import datetime
import calendar
import categories as cat


def _as_date(d):
    if d is None:
        return None
    return d.date() if hasattr(d, "date") else d


def aggregate_expenses(operations, start, end):
    """Считает расходы за период [start, end]. Доходы игнорируются (сумма >= 0)."""
    total = 0
    by_cat = {}          # топ-уровень -> сумма
    by_sub = {}          # полная категория -> сумма
    items = []           # отдельные траты для топа
    for op in operations:
        d = _as_date(op.get("дата"))
        if d is None or d < start or d > end:
            continue
        amt = float(op.get("сумма", 0) or 0)
        if amt >= 0:
            continue
        spent = abs(amt)
        full = str(op.get("категория", "Прочее")).strip() or "Прочее"
        top = cat.top_level(full)
        total += spent
        by_cat[top] = by_cat.get(top, 0) + spent
        by_sub[full] = by_sub.get(full, 0) + spent
        items.append({"cat": full, "amount": round(spent), "note": str(op.get("заметка", "")).strip(), "date": d})
    return {
        "start": start, "end": end,
        "total": round(total),
        "by_cat": {k: round(v) for k, v in by_cat.items()},
        "by_sub": {k: round(v) for k, v in by_sub.items()},
        "items": items,
        "count": len(items),
    }


def month_to_date(operations, today=None):
    if today is None:
        today = datetime.date.today()
    start = today.replace(day=1)
    agg = aggregate_expenses(operations, start, today)
    agg["days"] = today.day
    agg["avg_per_day"] = round(agg["total"] / today.day) if today.day else 0
    return agg


def last_week_range(today=None):
    if today is None:
        today = datetime.date.today()
    this_monday = today - datetime.timedelta(days=today.weekday())
    last_monday = this_monday - datetime.timedelta(days=7)
    last_sunday = this_monday - datetime.timedelta(days=1)
    return last_monday, last_sunday


def current_month_range(today=None):
    if today is None:
        today = datetime.date.today()
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return start, today.replace(day=last_day)


_MONTHS_RU = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _cat_lines(by_cat):
    if not by_cat:
        return ["  (трат нет)"]
    return [f"  • {c}: {v:,} ₽" for c, v in sorted(by_cat.items(), key=lambda x: -x[1])]


def _top_items(items, n=3):
    top = sorted(items, key=lambda x: -x["amount"])[:n]
    out = []
    for it in top:
        label = it["cat"]
        if it["note"]:
            label += f" ({it['note']})"
        out.append(f"  • {it['amount']:,} ₽ — {label}")
    return out


def format_month_stats(agg):
    """Экран по кнопке 'Статистика с начала месяца'."""
    s = agg["start"].strftime("%d.%m")
    e = agg["end"].strftime("%d.%m")
    lines = [f"📊 С начала месяца ({s}–{e})", ""]
    lines.append(f"Всего потрачено: {agg['total']:,} ₽")
    lines.append(f"Трат: {agg['count']} · в среднем {agg['avg_per_day']:,} ₽/день ({agg['days']} дн.)")
    lines.append("")
    lines.append("По категориям:")
    lines += _cat_lines(agg["by_cat"])
    if agg["items"]:
        lines.append("")
        lines.append("Крупнейшие траты:")
        lines += _top_items(agg["items"], 3)
    return "\n".join(lines)


def format_weekly(agg):
    s = agg["start"].strftime("%d.%m")
    e = agg["end"].strftime("%d.%m")
    lines = [f"📅 Неделя {s}–{e}", ""]
    lines.append(f"Потрачено: {agg['total']:,} ₽ · трат: {agg['count']}")
    lines.append("")
    lines.append("По категориям:")
    lines += _cat_lines(agg["by_cat"])
    return "\n".join(lines)


def format_monthly(agg, ai_comment=""):
    m = _MONTHS_RU[agg["start"].month].capitalize()
    y = agg["start"].year
    avg = round(agg["total"] / agg["count"]) if agg["count"] else 0
    lines = [f"📊 Отчёт за {m} {y}", ""]
    lines.append(f"Всего потрачено: {agg['total']:,} ₽")
    lines.append(f"Трат: {agg['count']} · средний чек {avg:,} ₽")
    lines.append("")
    lines.append("По категориям:")
    lines += _cat_lines(agg["by_cat"])
    if agg["items"]:
        lines.append("")
        lines.append("Топ-5 трат:")
        lines += _top_items(agg["items"], 5)
    if ai_comment:
        lines.append("")
        lines.append(f"🤖 {ai_comment}")
    return "\n".join(lines)
