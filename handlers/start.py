# handlers/start.py
from telegram import Update
from telegram.ext import ContextTypes
from utils.text import HELP_TEXT

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)
