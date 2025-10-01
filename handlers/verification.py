import os
import logging
import httpx
import motor.motor_asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

logger = logging.getLogger(__name__)

SHORTLINK_URL = os.environ.get("SHORTLINK_URL", "arolinks.com")
SHORTLINK_API = os.environ.get("SHORTLINK_API", "139ebf8c6591acc6a69db83f200f2285874dbdbf")
VERIFY_EXPIRE = int(os.environ.get('VERIFY_EXPIRE', 21600))
IS_VERIFY = os.environ.get("IS_VERIFY", "True").lower() == "true"
TUT_VID = os.environ.get("TUT_VID", "gojfsi/2")
MONGO_URI = os.environ.get("MONGO_URI")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client['terabox_bot']
users_col = db['users_verification']

async def get_user_verification_status(user_id: int) -> bool:
    if not IS_VERIFY:
        return True
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return False
    verified_at = user.get("verified_at")
    if not verified_at:
        return False
    expiration = verified_at + timedelta(seconds=VERIFY_EXPIRE)
    return datetime.utcnow() <= expiration

async def record_user_verification(user_id: int):
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"verified_at": datetime.utcnow()}, "$setOnInsert": {"leech_count": 0}},
        upsert=True
    )

async def increment_user_leech_count(user_id: int) -> int:
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        await users_col.insert_one({"user_id": user_id, "leech_count": 1})
        return 1
    new_count = user.get("leech_count", 0) + 1
    await users_col.update_one({"user_id": user_id}, {"$set": {"leech_count": new_count}})
    return new_count

async def reset_user_leech_count(user_id: int):
    await users_col.update_one({"user_id": user_id}, {"$set": {"leech_count": 0}})

def generate_verification_link(user_id: int) -> str:
    return f"https://{SHORTLINK_URL}/verify?api_key={SHORTLINK_API}&user={user_id}"

async def verify_user_token(token: str) -> bool:
    url = f"https://{SHORTLINK_URL}/api/verify"
    params = {"api_key": SHORTLINK_API, "token": token}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            data = response.json()
            return data.get("success", False)
    except Exception as e:
        logger.error(f"Shortlink verification API failed: {e}")
        return False

async def verify_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Please provide the verification token.\nUsage: /verify <token>")
        return
    token = args[0]
    success = await verify_user_token(token)
    if not success:
        await update.message.reply_text("Verification failed. Please check your token and try again.")
        return
    await record_user_verification(user_id)
    await reset_user_leech_count(user_id)
    await update.message.reply_text("Verification successful! You can now continue to use the bot.")
