"""
Логика долгов: расчёт приоритета погашения и сортировка.
Приоритет считается детерминированно. Чем больше число — тем срочнее гасить.
"""
import datetime


def days_until_day(target_day: int, today: datetime.date = None) -> int:
    """
    Сколько дней до ближайшего наступления числа месяца target_day.
    Например сегодня 17-е, target_day=5 -> вернёт дни до 5-го следующего месяца.
    """
    if today is None:
        today = datetime.date.today()
    if target_day <= 0:
        return 999
    # ближайшая дата с этим числом (в этом месяце или следующем)
    import calendar as _cal
    candidates = []
    for add_month in (0, 1):
        m = today.month + add_month
        y = today.year
        if m > 12:
            m -= 12
            y += 1
        days_in = _cal.monthrange(y, m)[1]
        day = min(target_day, days_in)
        d = datetime.date(y, m, day)
        if d >= today:
            candidates.append((d - today).days)
    return min(candidates) if candidates else 999


def calc_priority(debt: dict, today: datetime.date = None) -> float:
    """
    debt — словарь с ключами: остаток, ставка, день, просрочка.
    Возвращает число приоритета (больше = срочнее).
    """
    остаток = float(debt.get("остаток", 0) or 0)
    ставка = float(debt.get("ставка", 0) or 0)
    день = int(debt.get("день", 0) or 0)
    просрочка = str(debt.get("просрочка", "НЕТ")).strip().upper()

    if остаток <= 0:
        return 0.0

    priority = 0.0
    # 1) просрочки горят первыми — самый большой вес
    if просрочка == "ДА":
        priority += 1000
    # 2) месячная стоимость процентов в рублях (дорогие микрозаймы наверх)
    priority += ставка * остаток / 100 / 12
    # 3) любой процентный долг важнее беспроцентного
    if ставка > 0:
        priority += 200
    # 4) срочность по близости даты платежа
    дней = days_until_day(день, today)
    if дней <= 3:
        priority += 500
    elif дней <= 7:
        priority += 250

    return round(priority, 1)


def get_debts_sorted(debts: list, today: datetime.date = None) -> list:
    """
    Принимает список словарей долгов, возвращает отсортированные по убыванию
    приоритета, только с остатком > 0. Каждому добавляет ключ 'приоритет'.
    """
    active = []
    for d in debts:
        остаток = float(d.get("остаток", 0) or 0)
        if остаток > 0:
            d = dict(d)
            d["приоритет"] = calc_priority(d, today)
            active.append(d)
    active.sort(key=lambda x: x["приоритет"], reverse=True)
    return active


def total_debt(debts: list) -> int:
    """Общая сумма всех долгов."""
    return round(sum(float(d.get("остаток", 0) or 0) for d in debts))


def total_people_debt(debts: list) -> int:
    """Сумма долгов людям."""
    return round(sum(float(d.get("остаток", 0) or 0)
                     for d in debts
                     if str(d.get("категория", "")).strip().lower() == "человек"))


def total_bank_monthly(debts: list) -> int:
    """Сумма ежемесячных минимальных платежей по банкам/МФО (не людям, остаток>0)."""
    return round(sum(float(d.get("платеж", 0) or 0)
                     for d in debts
                     if str(d.get("категория", "")).strip().lower() in ("кк", "мз")
                     and float(d.get("остаток", 0) or 0) > 0))
