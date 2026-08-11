# ── Job Hunter — Makefile ─────────────────────────────────────────────────────
# Requirements: uv (pip install uv)

.PHONY: install run test lint clean db-reset

# Create venv and install dependencies
install:
	@if [ !d .venv ]; then uv venv .venv; fi
	uv pip install -r requirements.txt

# Start everything (FastAPI + Telegram bot + scheduler)
run:
	@./start.sh

# Start web only (no Telegram bot)
web:
	@source .venv/bin/activate && python main.py --web-only

# Database shell
db:
	@source .venv/bin/activate && python -c "
	import asyncio, aiosqlite
	from config.settings import DB_PATH
	async def shell():
		async with aiosqlite.connect(DB_PATH) as db:
			return
	asyncio.run(shell())
	"
	@sqlite3 jobs.db

# Run static checks
check:
	@python -m py_compile main.py core/database.py core/collector.py core/scorer.py core/hunter.py
	@python -m py_compile sources/remotive.py sources/remoteok.py sources/arbeitnow.py
	@python -m py_compile sources/greenhouse.py sources/lever.py sources/ashby.py sources/jsearch.py
	@python -m py_compile bot/handlers.py scripts/cron_collect.py scripts/cron_daily_digest.py
	@echo "All syntax checks passed"
