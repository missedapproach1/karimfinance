import os
from dotenv import load_dotenv
import urllib.request, json
load_dotenv()
t = os.getenv("BOT_TOKEN")
print("Токен из .env:", t[:15], "..." if t else "ПУСТО")
try:
    r = urllib.request.urlopen(f"https://api.telegram.org/bot{t}/getMe", timeout=15)
    print("Ответ Telegram:", json.load(r))
except Exception as e:
    print("ОШИБКА:", e)
