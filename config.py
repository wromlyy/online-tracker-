import os


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


API_ID = _int("API_ID", 0)
API_HASH = os.environ.get("API_HASH", "")

# Строковая сессия Telethon (генерация — gen_session.py)
TG_STRING_SESSION = os.environ.get("TG_STRING_SESSION", "")

TELEGRAM_TARGET = os.environ.get("TELEGRAM_TARGET", "@username")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "")

WA_NOTIFY_URL    = os.environ.get("WA_NOTIFY_URL", "http://127.0.0.1:8787/notify")
WA_TARGET_NUMBER = os.environ.get("WA_TARGET_NUMBER", "")

STATUS_INTERVAL  = float(os.environ.get("STATUS_INTERVAL", "1.0"))
PROFILE_INTERVAL = float(os.environ.get("PROFILE_INTERVAL", "15.0"))
STORY_INTERVAL   = float(os.environ.get("STORY_INTERVAL", "10.0"))
