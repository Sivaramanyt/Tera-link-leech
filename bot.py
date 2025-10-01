import asyncio
import logging
import os
from telegram.ext import Application
from handlers.start import start_handler
from handlers.leech import leech_handler
from handlers.set_commands import set_bot_commands

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set.")
        return

    logger.info("Starting Terabox Leech Bot...")

    app = Application.builder().token(bot_token).build()

    # Register only working handlers
    app.add_handler(start_handler)
    app.add_handler(leech_handler)

    # Set bot commands
    await set_bot_commands(app)

    # Start the bot
    await app.start()
    await app.updater.start_polling()
    await app.idle()

if __name__ == "__main__":
    asyncio.run(main())
    
