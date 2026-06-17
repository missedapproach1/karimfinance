"""
Доступ к Google Sheets — единственный источник правды.
Все данные читаются и пишутся сюда. Никакой локальной БД.
"""
import time
import logging
import datetime
import gspread
from google.oauth2.service_account import Credentials

import config
import salary

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Имена листов
SH_OPS = "Операции"
SH_DEBTS = "Долги"
SH_SETTINGS = "Настройки"
SH_CALENDAR = "Календарь2026"
SH_BACKUP = "Операции_backup"

# Заголовки
OPS_HEADER = ["Дата", "Тип", "Категория", "Сумма", "Заметка", "Баланс после"]
DEBTS_HEADER = ["Название", "Категория", "Остаток", "Ставка", "Платёж/мес", "День", "Просрочка", "Приоритет"]
SETTINGS_HEADER = ["Параметр", "Значение"]
CALENDAR_HEADER = ["Месяц", "Раб.дней всего", "Раб.дней 1-15", "Раб.дней 16-конец"]

# Начальные данные долгов
INITIAL_DEBTS = [
    ["ТБАНК", "КК", 61840, 60, 7900, 5, "ДА"],
    ["Сбербанк", "КК", 61638, 40, 2874, 27, "НЕТ"],
    ["Быстроденьги", "МЗ", 15000, 365, 18600, 16, "НЕТ"],
    ["СМСФинанс", "МЗ", 25200, 292, 11547, 28, "НЕТ"],
    ["ДЗП-Единый", "МЗ", 22176, 292, 13816, 27, "НЕТ"],
    ["Займер", "МЗ", 0, 292, 0, 17, "НЕТ"],
    ["Эквазайм", "МЗ", 0, 292, 0, 30, "НЕТ"],
    ["Турбозайм", "МЗ", 0, 292, 0, 22, "НЕТ"],
    ["МТС-Банк", "КК", 0, 0, 0, 15, "НЕТ"],
    ["Аслан", "Человек", 103000, 0, 17000, 16, "НЕТ"],
    ["Наташа", "Человек", 50000, 0, 15000, 30, "ДА"],
    ["Стас", "Человек", 8000, 0, 8000, 30, "НЕТ"],
    ["Мама", "Человек", 8000, 0, 8000, 24, "НЕТ"],
    ["Алина", "Человек", 7000, 0, 7000, 30, "НЕТ"],
]

# Начальные настройки
INITIAL_SETTINGS = [
    ["Оклад", 135000],
    ["Премия по умолчанию", 15000],
    ["Аренда часть 1", 25000],
    ["Аренда часть 2", 20000],
    ["Связь", 500],
    ["Зал", 0],
    ["День аванса", 16],
    ["День зарплаты", 1],
    ["День аренды 1", 1],
    ["День аренды 2", 16],
    ["День связи", 20],
    ["День зала", 0],
]


class Sheets:
    def __init__(self):
        import os, json as _json, base64 as _b64
        cb = os.getenv("GOOGLE_CREDENTIALS_B64", "").strip()
        cj = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        if cb:
            creds = Credentials.from_service_account_info(_json.loads(_b64.b64decode(cb)), scopes=SCOPES)
        elif cj:
            creds = Credentials.from_service_account_info(_json.loads(cj), scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        self.ss = self.gc.open_by_key(config.GOOGLE_SHEET_ID)
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 30  # секунд

    # ---------- retry-обёртка ----------
    def _retry(self, func, *args, **kwargs):
        last = None
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last = e
                logger.warning(f"Google API ошибка (попытка {attempt+1}/3): {e}")
                time.sleep(1.5 * (attempt + 1))
        raise last

    def _ws(self, title):
        try:
            return self.ss.worksheet(title)
        except gspread.WorksheetNotFound:
            return None

    # ---------- инициализация ----------
    def init_sheets(self):
        """Создаёт листы и заполняет начальными данными, если их нет."""
        existing = [ws.title for ws in self.ss.worksheets()]
        logger.info(f"Существующие листы: {existing}")

        # Операции
        if SH_OPS not in existing:
            ws = self.ss.add_worksheet(SH_OPS, rows=1000, cols=6)
            ws.append_row(OPS_HEADER, value_input_option="USER_ENTERED")
            logger.info("Создан лист Операции")

        # Долги
        if SH_DEBTS not in existing:
            ws = self.ss.add_worksheet(SH_DEBTS, rows=100, cols=8)
            ws.append_row(DEBTS_HEADER, value_input_option="USER_ENTERED")
            for row in INITIAL_DEBTS:
                ws.append_row(row, value_input_option="USER_ENTERED")
            logger.info("Создан лист Долги с данными")

        # Настройки
        if SH_SETTINGS not in existing:
            ws = self.ss.add_worksheet(SH_SETTINGS, rows=50, cols=2)
            ws.append_row(SETTINGS_HEADER, value_input_option="USER_ENTERED")
            for row in INITIAL_SETTINGS:
                ws.append_row(row, value_input_option="USER_ENTERED")
            logger.info("Создан лист Настройки")

        # Календарь
        if SH_CALENDAR not in existing:
            ws = self.ss.add_worksheet(SH_CALENDAR, rows=20, cols=4)
            ws.append_row(CALENDAR_HEADER, value_input_option="USER_ENTERED")
            for row in salary.build_calendar_2026():
                ws.append_row(row, value_input_option="USER_ENTERED")
            logger.info("Создан лист Календарь2026")

        # Удалим дефолтный пустой "Лист1"/"Sheet1" если он есть и пуст
        for junk in ("Лист1", "Sheet1"):
            if junk in [ws.title for ws in self.ss.worksheets()]:
                try:
                    w = self.ss.worksheet(junk)
                    vals = w.get_all_values()
                    if not vals or all(not any(r) for r in vals):
                        self.ss.del_worksheet(w)
                        logger.info(f"Удалён пустой лист {junk}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить {junk}: {e}")

    def _cache_get(self, key):
        if key in self._cache and (time.time() - self._cache_time.get(key, 0)) < self._cache_ttl:
            return self._cache[key]
        return None

    def _cache_set(self, key, value):
        self._cache[key] = value
        self._cache_time[key] = time.time()

    def _cache_clear(self):
        self._cache.clear()
        self._cache_time.clear()

    # ---------- чтение ----------
    def get_settings(self) -> dict:
        cached = self._cache_get("settings")
        if cached is not None:
            return cached
        ws = self._ws(SH_SETTINGS)
        rows = self._retry(ws.get_all_values)[1:]  # без заголовка
        d = {}
        for r in rows:
            if len(r) >= 2 and r[0]:
                key = r[0].strip()
                val = r[1].strip()
                try:
                    d[key] = int(float(val.replace(" ", "").replace("\u00a0", "")))
                except (ValueError, AttributeError):
                    d[key] = val
        self._cache_set("settings", d)
        return d

    def get_debts(self) -> list:
        cached = self._cache_get("debts")
        if cached is not None:
            return cached
        ws = self._ws(SH_DEBTS)
        rows = self._retry(ws.get_all_values)[1:]
        debts = []
        for i, r in enumerate(rows):
            if len(r) >= 7 and r[0].strip():
                def num(x):
                    try:
                        return float(str(x).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                    except (ValueError, AttributeError):
                        return 0
                debts.append({
                    "row": i + 2,  # номер строки в таблице (с учётом заголовка)
                    "название": r[0].strip(),
                    "категория": r[1].strip() if len(r) > 1 else "",
                    "остаток": num(r[2]) if len(r) > 2 else 0,
                    "ставка": num(r[3]) if len(r) > 3 else 0,
                    "платеж": num(r[4]) if len(r) > 4 else 0,
                    "день": int(num(r[5])) if len(r) > 5 else 0,
                    "просрочка": r[6].strip() if len(r) > 6 else "НЕТ",
                })
        self._cache_set("debts", debts)
        return debts

    def get_calendar(self) -> list:
        cached = self._cache_get("calendar")
        if cached is not None:
            return cached
        ws = self._ws(SH_CALENDAR)
        rows = self._retry(ws.get_all_values)[1:]
        cal = []
        for r in rows:
            if len(r) >= 4 and r[0]:
                try:
                    cal.append([int(r[0]), int(r[1]), int(r[2]), int(r[3])])
                except ValueError:
                    pass
        self._cache_set("calendar", cal)
        return cal

    def get_last_balance(self) -> int:
        """Текущий баланс = значение в последней заполненной строке колонки F (Баланс после)."""
        ws = self._ws(SH_OPS)
        col = self._retry(ws.col_values, 6)  # колонка F
        # col[0] — заголовок; ищем последнее непустое числовое значение
        for val in reversed(col[1:]):
            if val and str(val).strip():
                try:
                    return int(float(str(val).replace(" ", "").replace("\u00a0", "").replace(",", ".")))
                except ValueError:
                    continue
        return 0

    def get_operations(self) -> list:
        """Все операции как список dict с распарсенной датой."""
        ws = self._ws(SH_OPS)
        rows = self._retry(ws.get_all_values)[1:]
        ops = []
        for r in rows:
            if len(r) >= 4 and r[0].strip():
                d = None
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        d = datetime.datetime.strptime(r[0].strip(), fmt)
                        break
                    except ValueError:
                        continue
                def num(x):
                    try:
                        return float(str(x).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                    except (ValueError, AttributeError):
                        return 0
                ops.append({
                    "дата": d,
                    "тип": r[1].strip() if len(r) > 1 else "",
                    "категория": r[2].strip() if len(r) > 2 else "",
                    "сумма": num(r[3]) if len(r) > 3 else 0,
                    "заметка": r[4].strip() if len(r) > 4 else "",
                })
        return ops

    # ---------- запись ----------
    def add_operation(self, op_type: str, category: str, amount: int, note: str = "") -> int:
        """
        Добавляет операцию. amount: доход +, расход −.
        Возвращает новый баланс. Бросает исключение при неудаче.
        """
        balance_before = self.get_last_balance()
        new_balance = balance_before + amount
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        row = [now, op_type, category, amount, note, new_balance]
        ws = self._ws(SH_OPS)
        self._retry(ws.append_row, row, value_input_option="USER_ENTERED")
        self._cache_clear()
        logger.info(f"Записана операция: {row}")
        return new_balance

    def reduce_debt(self, debt_name: str, amount: int) -> float:
        """Уменьшает остаток долга на amount. Возвращает новый остаток."""
        debts = self.get_debts()
        target = next((d for d in debts if d["название"].strip().lower() == debt_name.strip().lower()), None)
        if not target:
            raise ValueError(f"Долг не найден: {debt_name}")
        new_remaining = max(0, target["остаток"] - amount)
        ws = self._ws(SH_DEBTS)
        # колонка C (3) = остаток
        self._retry(ws.update_cell, target["row"], 3, int(new_remaining))
        # если остаток 0 — снимаем просрочку
        if new_remaining == 0:
            self._retry(ws.update_cell, target["row"], 7, "НЕТ")
        self._cache_clear()
        logger.info(f"Долг {debt_name}: {target['остаток']} -> {new_remaining}")
        return new_remaining

    def update_setting(self, param: str, value) -> None:
        """Обновляет параметр в Настройках (или добавляет если нет)."""
        ws = self._ws(SH_SETTINGS)
        rows = self._retry(ws.get_all_values)
        found_row = None
        for i, r in enumerate(rows):
            if r and r[0].strip().lower() == param.strip().lower():
                found_row = i + 1
                break
        if found_row:
            self._retry(ws.update_cell, found_row, 2, value)
        else:
            self._retry(ws.append_row, [param, value], value_input_option="USER_ENTERED")
        self._cache_clear()
        logger.info(f"Настройка {param} = {value}")

    def update_priorities(self):
        """Пересчитывает и записывает приоритеты долгов в колонку H."""
        from debts import calc_priority
        debts = self.get_debts()
        ws = self._ws(SH_DEBTS)
        for d in debts:
            p = calc_priority(d)
            try:
                self._retry(ws.update_cell, d["row"], 8, p)
            except Exception as e:
                logger.warning(f"Не удалось записать приоритет для {d['название']}: {e}")
        self._cache_clear()

    def backup_operations(self):
        """Копирует лист Операции в Операции_backup (перезапись)."""
        ops_ws = self._ws(SH_OPS)
        data = self._retry(ops_ws.get_all_values)
        backup_ws = self._ws(SH_BACKUP)
        if backup_ws is None:
            backup_ws = self.ss.add_worksheet(SH_BACKUP, rows=max(1000, len(data) + 10), cols=6)
        else:
            self._retry(backup_ws.clear)
        if data:
            self._retry(backup_ws.update, data, value_input_option="USER_ENTERED")
        logger.info("Бэкап операций выполнен")

    def set_balance(self, real_balance: int) -> dict:
        """Выставляет реальный баланс: пишет операцию-корректировку на разницу."""
        current = self.get_last_balance()
        diff = real_balance - current
        if diff == 0:
            return {"diff": 0, "current": current, "new": real_balance, "small": True}
        small = abs(diff) <= 500
        note = f"корректировка (расхождение {diff:+d} руб)"
        if not small:
            note = f"КОРРЕКТИРОВКА КРУПНАЯ {diff:+d} руб"
        self.add_operation("Корректировка", "Корректировка", diff, note)
        return {"diff": diff, "current": current, "new": real_balance, "small": small}

    def operation_exists_today(self, category: str) -> bool:
        """Есть ли сегодня операция с данной категорией (для идемпотентности начислений)."""
        today = datetime.date.today()
        for op in self.get_operations():
            d = op.get("дата")
            if d and d.date() == today and op.get("категория", "").strip().lower() == category.strip().lower():
                return True
        return False
