"""
Финансовая логика: распределение дохода, баланс, остаток на жизнь, дефицит.
Все расчёты детерминированные.
"""
import datetime
from debts import get_debts_sorted, days_until_day


def upcoming_fixed_payments(settings: dict, today: datetime.date = None, horizon_days: int = 12):
    """
    Ближайшие обязательные фиксированные платежи (аренда, связь) в пределах horizon_days.
    Возвращает список dict: {название, сумма, день, дней_до}.
    """
    if today is None:
        today = datetime.date.today()
    result = []
    fixed = [
        ("Аренда (1-я часть)", settings.get("Аренда часть 1", 0), settings.get("День аренды 1", 1)),
        ("Аренда (2-я часть)", settings.get("Аренда часть 2", 0), settings.get("День аренды 2", 16)),
        ("Связь", settings.get("Связь", 0), settings.get("День связи", 20)),
        ("Зал", settings.get("Зал", 0), settings.get("День зала", 0)),
    ]
    for name, amount, day in fixed:
        amount = float(amount or 0)
        day = int(day or 0)
        if amount <= 0 or day <= 0:
            continue
        d = days_until_day(day, today)
        if d <= horizon_days:
            result.append({"название": name, "сумма": round(amount), "день": day, "дней_до": d})
    result.sort(key=lambda x: x["дней_до"])
    return result


def distribute_income(amount: int, debts: list, settings: dict,
                      balance: int = 0, today: datetime.date = None,
                      days_to_next_income: int = 14,
                      min_daily_life: int = 1000) -> dict:
    """
    Рекомендованное распределение пришедшего дохода.
    Логика (по убыванию критичности):
      1) Просрочки по БАНКАМ/МФО (пени + кредитная история) — гасим всегда.
      2) Ближайшие обязательные фикс.платежи (аренда/связь в горизонте 10 дней).
      3) Минимальные платежи по дорогим процентным долгам (микрозаймы).
      -- РЕЗЕРВ НА ЖИЗНЬ: откладываем min_daily_life * дней_до_дохода, чтобы не остаться без денег.
      4) Только ОСТАТОК сверх резерва -> на срочные долги людям (просрочка/обещание) и тело.
    min_daily_life — сколько рублей в день минимально оставить на жизнь.
    """
    if today is None:
        today = datetime.date.today()

    remaining = amount
    plan = []  # [{кому, сколько, почему, тип}]

    sorted_debts = get_debts_sorted(debts, today)

    def cat(d):
        return str(d.get("категория", "")).strip().lower()

    # 1) Просрочки по банкам/МФО — критично всегда
    for d in sorted_debts:
        if remaining <= 0:
            break
        if str(d.get("просрочка", "")).strip().upper() == "ДА" and cat(d) in ("кк", "мз"):
            платеж = float(d.get("платеж", 0) or 0)
            need = round(min(платеж or float(d["остаток"]), float(d["остаток"]), remaining))
            if need > 0:
                plan.append({"кому": d["название"], "сколько": need,
                             "почему": "просрочка, пени капают", "тип": "просрочка"})
                remaining -= need

    # 2) Ближайшие обязательные фиксированные платежи
    fixed = upcoming_fixed_payments(settings, today, horizon_days=10)
    for f in fixed:
        if remaining <= 0:
            break
        need = round(min(f["сумма"], remaining))
        plan.append({"кому": f["название"], "сколько": need,
                     "почему": (f"платёж через {f['дней_до']} дн." if f["дней_до"] > 0 else "платёж сегодня"),
                     "тип": "фикс"})
        remaining -= need

    # 3) Минимальные платежи по дорогим процентным долгам (микрозаймы, не просрочка)
    for d in sorted_debts:
        if remaining <= 0:
            break
        if str(d.get("просрочка", "")).strip().upper() == "ДА":
            continue
        if cat(d) not in ("кк", "мз"):
            continue
        ставка = float(d.get("ставка", 0) or 0)
        платеж = float(d.get("платеж", 0) or 0)
        if ставка > 0 and платеж > 0:
            need = round(min(платеж, float(d["остаток"]), remaining))
            if need > 0:
                plan.append({"кому": d["название"], "сколько": need,
                             "почему": f"ставка {int(ставка)}%, платёж {int(d.get('день',0))}-го",
                             "тип": "долг"})
                remaining -= need

    # РЕЗЕРВ НА ЖИЗНЬ: защищаем сумму на каждодневные траты до следующего дохода
    резерв = min_daily_life * max(days_to_next_income, 1)
    свободно_на_долги_людям = max(0, remaining - резерв)

    # 4) Срочные долги людям (просрочка/обещание) — из остатка сверх резерва, частями
    for d in sorted_debts:
        if свободно_на_долги_людям <= 0:
            break
        if cat(d) != "человек":
            continue
        срочно = str(d.get("просрочка", "")).strip().upper() == "ДА"
        # ближайший платёж по графику (напр. Аслан) тоже считаем срочным
        день = int(d.get("день", 0) or 0)
        близко = days_until_day(день, today) <= 5 if день else False
        if срочно or близко:
            # рекомендуем платёж (или часть остатка), но не больше свободного
            рек = float(d.get("платеж", 0) or 0) or float(d["остаток"])
            need = round(min(рек, float(d["остаток"]), свободно_на_долги_людям))
            if need > 0:
                почему = "обещал, ждёт" if срочно else f"платёж по графику {день}-го"
                plan.append({"кому": d["название"], "сколько": need, "почему": почему, "тип": "люди"})
                свободно_на_долги_людям -= need
                remaining -= need

    # Остаток на жизнь = то что осталось после всех платежей
    на_жизнь = round(remaining)

    # Дефицит: сколько НЕ хватило на критичное (просрочки банков + ближайшая аренда/связь)
    требовалось = 0
    for d in sorted_debts:
        if str(d.get("просрочка", "")).strip().upper() == "ДА" and cat(d) in ("кк", "мз"):
            платеж = float(d.get("платеж", 0) or 0)
            требовалось += round(min(платеж or float(d["остаток"]), float(d["остаток"])))
    for f in fixed:
        требовалось += f["сумма"]
    дефицит = max(0, требовалось - amount)

    per_day = round(на_жизнь / days_to_next_income) if days_to_next_income > 0 else на_жизнь

    return {
        "пришло": amount,
        "баланс_после": round(balance + amount),
        "план": plan,
        "на_жизнь": на_жизнь,
        "дефицит": дефицит,
        "дней_до_дохода": days_to_next_income,
        "в_день": per_day,
    }


def spent_by_category_this_month(operations: list, category: str, today: datetime.date = None) -> int:
    """
    Сумма расходов по категории с 1 числа текущего месяца.
    operations — список dict с ключами: дата (datetime), категория, сумма.
    """
    if today is None:
        today = datetime.date.today()
    start = today.replace(day=1)
    total = 0
    for op in operations:
        d = op.get("дата")
        if d is None:
            continue
        if isinstance(d, datetime.datetime):
            d = d.date()
        if d >= start and str(op.get("категория", "")).strip().lower() == category.strip().lower():
            s = float(op.get("сумма", 0) or 0)
            if s < 0:  # расход
                total += abs(s)
    return round(total)


def remaining_obligations_this_period(settings: dict, debts: list,
                                      today: datetime.date = None) -> int:
    """
    Сколько обязательного ещё предстоит до конца текущего периода (грубо — до конца месяца):
    непрошедшие фикс.платежи + минимальные платежи банков с непрошедшей датой.
    """
    if today is None:
        today = datetime.date.today()
    import calendar as _cal
    days_in = _cal.monthrange(today.year, today.month)[1]
    total = 0
    # фикс платежи, дата которых ещё впереди в этом месяце
    fixed = [
        (settings.get("Аренда часть 1", 0), settings.get("День аренды 1", 1)),
        (settings.get("Аренда часть 2", 0), settings.get("День аренды 2", 16)),
        (settings.get("Связь", 0), settings.get("День связи", 20)),
        (settings.get("Зал", 0), settings.get("День зала", 0)),
    ]
    for amount, day in fixed:
        amount = float(amount or 0)
        day = int(day or 0)
        if amount > 0 and 0 < day >= today.day:  # дата ещё не прошла
            total += amount
    # минимальные платежи банков/МФО с непрошедшей датой
    for d in debts:
        if str(d.get("категория", "")).strip().lower() in ("кк", "мз"):
            if float(d.get("остаток", 0) or 0) > 0:
                day = int(d.get("день", 0) or 0)
                платеж = float(d.get("платеж", 0) or 0)
                if платеж > 0 and 0 < day >= today.day:
                    total += платеж
    return round(total)
