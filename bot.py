import logging
import os
import sys
from telegram.ext import Application

# Handlers import (example)
from handlers.start import start_handler
from handlers.leech import leech_handler
from handlers.set_commands import set_bot_commands

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set.")
        return

    logger.info("Starting Terabox Leech Bot...")

    app = Application.builder().token(bot_token).build()

    # Register handlers
    app.add_handler(start_handler)
    app.add_handler(leech_handler)

    await set_bot_commands(app)

    await app.run_polling()

if __name__ == "__main__":
    # Handle existing event loop scenarios like Jupyter or some cloud platforms:
    try:
        import asyncio
        asyncio.run(main())
    except RuntimeError as e:
        if "event loop is running" in str(e):
            import nest_asyncio
            nest_asyncio.apply()
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(main())
            loop.run_forever()
        else:
            raise
            
