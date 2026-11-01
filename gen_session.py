# Сгенерировать TG_STRING_SESSION (запусти на своём ПК, не на хостинге).
#   pip install telethon
#   python gen_session.py
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os

API_ID = int(input("API_ID: ").strip())
API_HASH = input("API_HASH: ").strip()

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n=== TG_STRING_SESSION (сохрани в env) ===")
    print(client.session.save())
    print("=========================================\n")
