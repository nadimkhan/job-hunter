import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths — use Path so / operator works downstream
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "jobs.db"))
RESUME_DIR = Path(os.getenv("RESUME_DIR", BASE_DIR / "resumes"))

# API Keys
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_TOPIC_DAILY_DIGEST = os.getenv("TELEGRAM_TOPIC_DAILY_DIGEST", "")
TELEGRAM_TOPIC_UPDATES = os.getenv("TELEGRAM_TOPIC_UPDATES", "")

# Email
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

# Daily settings
DAILY_EMAIL_HOUR = int(os.getenv("DAILY_EMAIL_HOUR", "9"))
DAILY_JOBS_COUNT = int(os.getenv("DAILY_JOBS_COUNT", "15"))
JSEARCH_MAX_REQ_PER_RUN = int(os.getenv("JSEARCH_MAX_REQ_PER_RUN", "3"))
JSEARCH_MAX_RUNS_PER_DAY = int(os.getenv("JSEARCH_MAX_RUNS_PER_DAY", "6"))

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# Ensure dirs exist
os.makedirs(RESUME_DIR, exist_ok=True)
os.makedirs(RESUME_DIR / "default", exist_ok=True)
