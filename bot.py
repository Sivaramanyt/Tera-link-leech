# bot.py
from config import BOT_TOKEN, API_ID, API_HASH, MONGODB_URI, OWNER_ID
from handlers.start import start_handler
from handlers.leech import leech_handler
from utils.logging import setup_logger
from telegram.ext import Application, CommandHandler

def main():
    setup_logger()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("leech", leech_handler))
    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
