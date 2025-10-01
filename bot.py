import os
import sys
import logging
import asyncio
import signal

from telegram.ext import Application

# Import handlers from modular files
from handlers.start import start_handler
from handlers.leech import leech_handler  # Your main leech command handler
from handlers.health import SimpleHealthServer, run_health_server
from handlers.set_commands import set_bot_commands

logger = logging.getLogger(__name__)

def ensure_single_instance():
    import tempfile
    import fcntl
    try:
        lock_file = os.path.join(tempfile.gettempdir(), 'terabox_bot.lock')
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except Exception:
        logger.error("Another instance is already running.")
        sys.exit(1)

def setup_graceful_shutdown(app):

    def shutdown_signal_handler(signum, frame):
        logger.info(f"Received exit signal {signum}, shutting down...")
        loop = asyncio.get_event_loop()
        loop.create_task(graceful_shutdown(app))

    async def graceful_shutdown(app):
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            logger.info("Bot shutdown complete.")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            loop = asyncio.get_event_loop()
            loop.stop()

    signal.signal(signal.SIGINT, shutdown_signal_handler)
    signal.signal(signal.SIGTERM, shutdown_signal_handler)


async def run_bot():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("Missing BOT_TOKEN environment variable")
        sys.exit(1)

    global app
    app = Application.builder().token(bot_token).build()

    setup_graceful_shutdown(app)

    # Register handlers from modular files
    app.add_handler(start_handler)
    app.add_handler(leech_handler)
    app.add_error_handler(lambda update, context: logger.error(f"Update error: {context.error}"))

    # Setup bot commands shown in Telegram UI
    await set_bot_commands(app)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Bot stopping")


async def main():
    try:
        ensure_single_instance()
        logger.info("Starting Terabox Leech Bot...")
        await asyncio.gather(
            run_health_server(),  # Your health server coroutine
            run_bot()
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        sys.exit(1)
