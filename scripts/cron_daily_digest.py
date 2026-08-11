#!/usr/bin/env python3
"""Cron script: daily job digest to Telegram (every morning 8am UTC).
Gets top new/relevant jobs from last 24h and posts to Daily Updates thread."""
import asyncio, sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TOPIC_DAILY_DIGEST
from core.database import init_db, get_active_profile, get_jobs, get_stats
from telegram import Bot


async def main():
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    profile = await get_active_profile(db)
    if not profile:
        print("[CRON DIGEST] No active profile — skipping")
        await db.close()
        return

    yesterday = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    jobs = await get_jobs(db, min_score=40, seen_after=yesterday, limit=15)
    await db.close()

    if not jobs:
        msg = (
            "Good morning! No new highly-relevant jobs in the last 24h.\n"
            "Run /collect in Telegram to refresh."
        )
    else:
        lines = [f"Good morning! *{len(jobs)} new/relevant jobs* found:\n"]
        for i, job in enumerate(jobs, 1):
            score = job.get("relevance_score", 0)
            india = job.get("india_friendly", "?")
            url = (job.get("url") or "")[:80]
            lines.append(
                f"{i}. *{job['title']}* @ {job['company']}\n"
                f"   Score:{score} | India:{india} | {job.get('location','Remote')}\n"
                f"   {url}"
            )
        msg = "\n".join(lines)

    print(f"[CRON DIGEST] Sending {len(jobs)} jobs to Telegram")
    print(msg[:500])

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown",
            message_thread_id=int(TELEGRAM_TOPIC_DAILY_DIGEST) if TELEGRAM_TOPIC_DAILY_DIGEST else None,
        )
        print("[CRON DIGEST] Telegram message sent")


if __name__ == "__main__":
    import aiosqlite
    asyncio.run(main())
