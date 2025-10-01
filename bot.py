#!/usr/bin/env python3
# bot.py - SIMPLE WORKING VERSION

import asyncio
import logging
import os
import sys
import tempfile
import fcntl
from telegram.ext import Application, CommandHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class SimpleHealthServer:
    """Simple health server"""
    
    async def handle_request(self, reader, writer):
        try:
            request = await reader.read(1024)
            response_body = '{"status": "healthy", "service": "terabox_bot"}'
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Connection: close\r\n\r\n"
                f"{response_body}"
            )
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()
        except Exception as e:
            logger.warning(f"Health server error: {e}")
    
    async def start(self, port):
        server = await asyncio.start_server(self.handle_request, '0.0.0.0', port)
        logger.info(f"🏥 Health server started on port {port}")
        async with server:
            await server.serve_forever()

def ensure_single_instance():
    try:
        lock_file = os.path.join(tempfile.gettempdir(), 'terabox_bot.lock')
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logger.info(f"🔒 Lock acquired: PID {os.getpid()}")
        return lock_fd
    except (IOError, OSError):
        logger.error("❌ Another instance running!")
        sys.exit(1)

async def start_handler(update, context):
    """Simple start handler"""
    await update.message.reply_text(
        "🔥 **Terabox Leech Pro Bot** 🔥\n\n"
        "Send: `/leech <terabox_link>`\n\n"
        "**Status:** ✅ Online\n"
        "**Version:** Simple Working"
    )

async def debug_handler(update, context):
    """Debug handler"""
    await update.message.reply_text("🤖 Bot is working perfectly!")

async def simple_leech_handler(update, context):
    """Simple leech handler - just for testing"""
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await update.message.reply_text("Usage: `/leech <terabox_link>`")
        return
    
    await update.message.reply_text("🔍 **Simple leech handler working!**\n\nEnhanced version will be added next.")

async def error_handler(update, context):
    """Global error handler"""
    logger.error(f"❌ ERROR: {context.error}")

async def run_health_server():
    port = int(os.getenv('PORT', 8000))
    health_server = SimpleHealthServer()
    await health_server.start(port)

async def run_bot():
    # Get bot token
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("❌ BOT_TOKEN not found!")
        sys.exit(1)
    
    logger.info(f"🔑 Bot token found: {bot_token[:10]}...")
    
    # Create application
    application = Application.builder().token(bot_token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("leech", simple_leech_handler))
    application.add_handler(CommandHandler("debug", debug_handler))
    application.add_error_handler(error_handler)
    
    logger.info("📝 Simple handlers added")
    
    # Start bot
    await application.initialize()
    await application.start()
    
    logger.info("🚀 Starting simple bot polling...")
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("✅ Simple bot started successfully!")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

async def main():
    try:
        # Ensure single instance
        lock_fd = ensure_single_instance()
        
        logger.info("🚀 Starting SIMPLE Terabox Bot...")
        
        # Run both health server and bot
        await asyncio.gather(
            run_health_server(),
            run_bot()
        )
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped")
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        sys.exit(1)
        
