from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_message = """Welcome! Use this bot to leech Terabox links to Telegram.

Commands:
/start - Show this help message
/leech <link> - Leech Terabox link
"""
    await update.message.reply_text(start_message)

start_handler = CommandHandler("start", start)
