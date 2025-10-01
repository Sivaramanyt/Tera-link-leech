import logging
import os
import asyncio
from telegram.ext import Application
from handlers.start import start_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def dummy_set_commands(app):
    # Minimal placeholder, no commands set yet
    pass

def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set.")
        return

    logger.info("Starting minimal Terabox Leech Bot...")
    app = Application.builder().token(bot_token).build()

    # Register only the start handler for now
    app.add_handler(start_handler)

    # Run minimal async setup if needed
    asyncio.run(dummy_set_commands(app))

    # Run the bot synchronously (event loop managed internally)
    app.run_polling()

if __name__ == "__main__":
    main()
    
