#!/usr/bin/env python3
"""Cron script: job collection (every 8h).
JSearch is hard-capped at 3 queries inside run_collection."""
import asyncio, sys, os, json
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TOPIC_DAILY_DIGEST
from core.database import init_db, get_active_profile
from core.collector import run_collection


async def main():
    from telegram import Bot
    db_path = DB_PATH

    db = await init_db() if False else None  # init happens in run_collection

    # Re-open DB properly
    import aiosqlite
    db = await aiosqlite.connect(db_path)
    await init_db()

    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        print("[CRON] No active profile — skipping collection")
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text="[CRON] Collection skipped: no active profile. Create one via the web UI.",
                message_thread_id=int(TELEGRAM_TOPIC_DAILY_DIGEST) if TELEGRAM_TOPIC_DAILY_DIGEST else None,
            )
        return

    print(f"[CRON] Starting collection with profile: {profile['name']}")
    stats = await run_collection(profile["config"], include_companies=True)

    msg = (
        f"[CRON] Collection done — "
        f"fetched:{stats['fetched']} new:{stats['new']} "
        f"updated:{stats['updated']} filtered:{stats['filtered_out']} "
        f"jsearch:{stats.get('jsearch_used', 0)}"
    )
    print(msg)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            message_thread_id=int(TELEGRAM_TOPIC_DAILY_DIGEST) if TELEGRAM_TOPIC_DAILY_DIGEST else None,
        )


if __name__ == "__main__":
    asyncio.run(main())
