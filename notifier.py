import asyncio
import httpx
import config


async def _telegram(text: str) -> None:
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TG_CHAT_ID, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
            )
    except Exception as e:
        print(f"[notifier] TG: {e}")


async def _whatsapp(text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(config.WA_NOTIFY_URL, json={"text": text})
    except Exception as e:
        print(f"[notifier] WA: {e}")


async def notify(text: str) -> None:
    await asyncio.gather(_telegram(text), _whatsapp(text))
