#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import re
import sys
import time
from datetime import datetime, timezone

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest, GetUsersRequest
from telethon.tl.functions.stories import GetStoriesRequest
from telethon.tl.types import (
    UserStatusOnline, UserStatusOffline, UserStatusRecently,
    UserStatusLastWeek, UserStatusLastMonth, UserStatusEmpty,
)
from telethon.errors import (
    FloodWaitError, UsernameNotOccupiedError, UsernameInvalidError,
)

import config
from notifier import notify

LOG_FILE = "telegram_monitor.log"
ONLINE_DEBOUNCE = 60
_last_online_notify = 0.0


def log(msg: str) -> None:
    line = f"[{datetime.now():%d.%m.%Y %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d.%m.%Y в %H:%M")


def describe_status(s) -> str:
    if isinstance(s, UserStatusOnline):    return "в сети"
    if isinstance(s, UserStatusOffline):   return f"оффлайн, последняя активность: {fmt_dt(s.was_online)}"
    if isinstance(s, UserStatusRecently):  return "был(а) недавно"
    if isinstance(s, UserStatusLastWeek):  return "был(а) на этой неделе"
    if isinstance(s, UserStatusLastMonth): return "был(а) в этом месяце"
    if isinstance(s, UserStatusEmpty):     return "статус скрыт"
    return f"неизвестно ({type(s).__name__})"


def display_name(u) -> str:
    parts = [getattr(u, "first_name", None), getattr(u, "last_name", None)]
    return (" ".join(p for p in parts if p)
            or getattr(u, "username", None)
            or str(u.id))


def normalize(raw: str):
    raw = raw.strip()
    m = re.match(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]+)/?$", raw)
    if m: return "@" + m.group(1)
    if re.fullmatch(r"-?\d+", raw): return int(raw)
    if re.fullmatch(r"\+?\d{7,15}", raw): return raw if raw.startswith("+") else "+" + raw
    if raw.startswith("@"): return raw
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw): return "@" + raw
    return raw


async def resolve(client, raw):
    target = normalize(raw)
    try:
        return await client.get_entity(target)
    except (UsernameNotOccupiedError, UsernameInvalidError, ValueError):
        pass
    if isinstance(target, int):
        async for d in client.iter_dialogs():
            if getattr(d.entity, "id", None) == target:
                return d.entity
    return None


async def check_status(client, input_user, state, name):
    global _last_online_notify
    users = await client(GetUsersRequest([input_user]))
    if not users:
        return
    st = users[0].status
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {name}: {describe_status(st)}", flush=True)

    cur = True if isinstance(st, UserStatusOnline) else \
          False if isinstance(st, UserStatusOffline) else None

    prev = state.get("online")
    if cur is not None and prev is not None and cur != prev:
        now = time.monotonic()
        if now - _last_online_notify < ONLINE_DEBOUNCE:
            state["online"] = cur
            return
        _last_online_notify = now

        if cur:
            log("🟢 ВЫШЕЛ В СЕТЬ")
            await notify(f"🟢 <b>{name}</b> зашёл(ла) в Telegram")
        else:
            log(f"🔴 УШЁЛ В ОФФЛАЙН — {describe_status(st)}")
            await notify(f"🔴 <b>{name}</b> вышел(ла) из Telegram — {describe_status(st)}")
    if cur is not None:
        state["online"] = cur


async def check_profile(client, entity, state):
    res = await client(GetFullUserRequest(entity))
    full = getattr(res, "full_user", None) or res
    user = getattr(full, "user", None) or entity

    cur = {
        "first_name": user.first_name or "",
        "last_name":  user.last_name or "",
        "username":   user.username or "",
        "phone":      getattr(full, "phone", "") or "",
        "bio":        getattr(full, "about", "") or "",
        "photo_id":   getattr(getattr(user, "photo", None), "photo_id", None),
        "premium":    bool(getattr(user, "premium", False)),
    }
    titles = {"first_name": "Имя", "last_name": "Фамилия",
              "username": "Username", "phone": "Телефон", "bio": "Био"}

    if state.get("_profile_init"):
        for k, title in titles.items():
            if state.get(k) != cur[k]:
                log(f"✏️  {title}: «{state.get(k) or '—'}» → «{cur[k] or '—'}»")
                await notify(f"✏️ <b>{title}</b>: «{state.get(k) or '—'}» → «{cur[k] or '—'}»")
        if state.get("photo_id") != cur["photo_id"]:
            log("🖼  Фото профиля изменено")
            await notify("🖼 Фото профиля изменено")
        if state.get("premium") != cur["premium"]:
            log("⭐ Premium изменён")
            await notify("⭐ Premium " + ("активирован" if cur["premium"] else "деактивирован"))

    state.update(cur)
    state["_profile_init"] = True


async def check_stories(client, entity, state):
    try:
        res = await client(GetStoriesRequest(peer=entity, hidden=False))
    except FloodWaitError:
        raise
    except Exception:
        return
    seen = state.setdefault("story_ids", set())
    init = state.get("_stories_init", False)
    for s in getattr(res, "stories", []) or []:
        sid = getattr(s, "id", None)
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        if init:
            log(f"📸 Новая сторис id={sid}")
            await notify(f"📸 Новая сторис (id={sid})")
    state["_stories_init"] = True


async def safe(fn, *a):
    try:
        await fn(*a)
    except FloodWaitError as e:
        log(f"⏳ FloodWait {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        log(f"⚠️  {fn.__name__}: {type(e).__name__}: {e}")


async def main():
    if not config.API_ID or not config.API_HASH:
        print("❌ API_ID/API_HASH не заданы", file=sys.stderr)
        return
    if not config.TG_STRING_SESSION:
        print("❌ TG_STRING_SESSION не задан (сгенерируй через gen_session.py)", file=sys.stderr)
        return

    raw = sys.argv[1] if len(sys.argv) > 1 else config.TELEGRAM_TARGET
    client = TelegramClient(StringSession(config.TG_STRING_SESSION),
                            config.API_ID, config.API_HASH)
    await client.start()

    entity = await resolve(client, raw)
    if not entity:
        print(f"❌ Не найден: {raw}", file=sys.stderr)
        await client.disconnect()
        return

    name = display_name(entity)
    input_user = utils.get_input_user(await client.get_input_entity(entity))

    log(f"▶️  Мониторинг: {name} (id={entity.id})")
    log("Каналы уведомлений: Telegram-бот + WhatsApp")

    state = {}
    await safe(check_profile, client, entity, state)
    await safe(check_stories, client, entity, state)

    next_s = next_p = next_st = time.monotonic()
    next_p += config.PROFILE_INTERVAL
    next_st += config.STORY_INTERVAL

    try:
        while True:
            n = time.monotonic()
            if n >= next_s:
                await safe(check_status, client, input_user, state, name)
                next_s = n + config.STATUS_INTERVAL
            if n >= next_p:
                await safe(check_profile, client, entity, state)
                next_p = n + config.PROFILE_INTERVAL
            if n >= next_st:
                await safe(check_stories, client, entity, state)
                next_st = n + config.STORY_INTERVAL
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        log("⏹  остановлено")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
