"""
Расчёт зарплаты и производственный календарь 2026.
Вся математика детерминированная — никаких приблизительных значений.
"""
import calendar
import datetime

# Госпраздники РФ 2026 (нерабочие дни). (месяц, день)
HOLIDAYS_2026 = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),  # новогодние каникулы
    (2, 23),   # День защитника Отечества
    (3, 8),    # Международный женский день
    (5, 1),    # Праздник весны и труда
    (5, 9),    # День Победы
    (6, 12),   # День России
    (11, 4),   # День народного единства
}


def is_workday(d: datetime.date) -> bool:
    """True если день рабочий (будни и не праздник)."""
    if d.weekday() >= 5:  # суббота=5, воскресенье=6
        return False
    if (d.month, d.day) in HOLIDAYS_2026:
        return False
    return True


def workdays_in_month(year: int, month: int):
    """Возвращает (всего рабочих, рабочих 1-15, рабочих 16-конец)."""
    days_in = calendar.monthrange(year, month)[1]
    total = sum(1 for d in range(1, days_in + 1) if is_workday(datetime.date(year, month, d)))
    first = sum(1 for d in range(1, 16) if is_workday(datetime.date(year, month, d)))
    second = sum(1 for d in range(16, days_in + 1) if is_workday(datetime.date(year, month, d)))
    return total, first, second


def build_calendar_2026():
    """
    Генерирует данные календаря для всех 12 месяцев 2026.
    Возвращает список строк: [месяц, всего, 1-15, 16-конец].
    """
    rows = []
    for m in range(1, 13):
        total, first, second = workdays_in_month(2026, m)
        rows.append([m, total, first, second])
    return rows


def payday_date(target_day: int, month: int, year: int) -> datetime.date:
    """
    Фактическая дата выплаты. Если target_day выпадает на выходной/праздник —
    сдвигается на БЛИЖАЙШИЙ ПРЕДЫДУЩИЙ рабочий день (раньше, не позже).
    """
    # Защита от некорректного дня (например 31 в коротком месяце)
    days_in = calendar.monthrange(year, month)[1]
    day = min(target_day, days_in)
    d = datetime.date(year, month, day)
    while not is_workday(d):
        d -= datetime.timedelta(days=1)
    return d


def calc_salary(period: str, month: int, year: int, oklad: int,
                premium: int = 0, calendar_rows=None) -> int:
    """
    Расчёт суммы выплаты.
    period: "avans" (за 1-15, выплата 16) или "zarplata" (за 16-конец + премия, выплата 1).
    month/year — РАСЧЁТНЫЙ месяц (за который считаем).
    oklad — месячный оклад.
    premium — премия (только для zarplata).
    calendar_rows — данные календаря [[месяц, всего, 1-15, 16-конец], ...]; если None, считается на лету.
    """
    if calendar_rows:
        row = next((r for r in calendar_rows if int(r[0]) == month), None)
        if row:
            total, first, second = int(row[1]), int(row[2]), int(row[3])
        else:
            total, first, second = workdays_in_month(year, month)
    else:
        total, first, second = workdays_in_month(year, month)

    if total == 0:
        return 0
    day_rate = oklad / total

    if period == "avans":
        return round(day_rate * first)
    elif period == "zarplata":
        return round(day_rate * second) + premium
    else:
        raise ValueError(f"Неизвестный period: {period}")


def next_payday_from(today: datetime.date, day_avans: int = 16, day_zp: int = 1):
    """
    Возвращает (дата_ближайшей_выплаты, тип) от today.
    тип = "avans" или "zarplata".
    Учитывает перенос на предыдущий рабочий день.
    """
    candidates = []
    # аванс текущего месяца
    candidates.append((payday_date(day_avans, today.month, today.year), "avans"))
    # зарплата текущего месяца (за прошлый период)
    candidates.append((payday_date(day_zp, today.month, today.year), "zarplata"))
    # на следующий месяц тоже (вдруг текущие уже прошли)
    nm = today.month + 1
    ny = today.year
    if nm > 12:
        nm = 1
        ny += 1
    candidates.append((payday_date(day_avans, nm, ny), "avans"))
    candidates.append((payday_date(day_zp, nm, ny), "zarplata"))

    future = sorted([(d, t) for d, t in candidates if d >= today])
    return future[0] if future else (None, None)
