# config.py
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
MONGODB_URI = os.getenv("MONGODB_URI", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Hard limits and simple constants
TELEGRAM_MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 2GB
HEALTH_HOST = os.getenv("HEALTH_HOST", "0.0.0.0")
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

# Basic validation to fail fast in local/dev runs
def validate():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not API_ID: missing.append("API_ID")
    if not API_HASH: missing.append("API_HASH")
    if not MONGODB_URI: missing.append("MONGODB_URI")
    if not OWNER_ID: missing.append("OWNER_ID")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
