"""Конфигурация бота"""
import os
from dotenv import load_dotenv

load_dotenv()
import os as _os
print("=== ДИАГНОСТИКА ОКРУЖЕНИЯ ===", flush=True)
print("B64 есть:", bool(_os.getenv("GOOGLE_CREDENTIALS_B64", "").strip()), flush=True)
print("B64 длина:", len(_os.getenv("GOOGLE_CREDENTIALS_B64", "")), flush=True)
print("BOT_TOKEN есть:", bool(_os.getenv("BOT_TOKEN", "").strip()), flush=True)
print("OWNER есть:", _os.getenv("OWNER_TELEGRAM_ID", "ПУСТО"), flush=True)
print("=== КОНЕЦ ДИАГНОСТИКИ ===", flush=True)


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0").strip() or 0)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.proxyapi.ru/anthropic").strip().rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-3-5-haiku-20241022").strip()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow").strip()


def validate():
    import os
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не задан")
    if not OWNER_TELEGRAM_ID:
        errors.append("OWNER_TELEGRAM_ID не задан")
    if not GOOGLE_SHEET_ID:
        errors.append("GOOGLE_SHEET_ID не задан")
    has_b64 = bool(os.getenv("GOOGLE_CREDENTIALS_B64", "").strip())
    has_json = bool(os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip())
    has_file = os.path.exists(GOOGLE_CREDENTIALS_FILE)
    if not has_b64 and not has_json and not has_file:
        errors.append("Нет ключа Google")
    return errors
