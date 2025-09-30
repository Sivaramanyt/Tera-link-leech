#!/usr/bin/env python3
# bot.py

import asyncio
import logging
import os
import sys
import tempfile
import fcntl
from telegram.ext import Application, CommandHandler
from handlers.leech import leech_handler_v2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class SimpleHealthServer:
    """Simple health server for Koyeb"""
    
    async def handle_request(self, reader, writer):
        """Handle HTTP requests"""
        try:
            request = await reader.read(1024)
            
            # Simple health response
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
        """Start health server"""
        server = await asyncio.start_server(self.handle_request, '0.0.0.0', port)
        logger.info(f"🏥 Health server started on port {port}")
        
        async with server:
            await server.serve_forever()

def ensure_single_instance():
    """Simple single instance check"""
    try:
        lock_file = os.path.join(tempfile.gettempdir(), 'terabox_bot.lock')
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logger.info(f"🔒 Single instance lock acquired: PID {os.getpid()}")
        return lock_fd
    except (IOError, OSError):
        logger.error("❌ Another bot instance is already running!")
        sys.exit(1)

async def start_handler(update, context):
    """Simple start handler"""
    welcome_message = """
🔥 **Terabox Leech Pro Bot** 🔥

Send me a Terabox share link to download files.

**Usage:** `/leech <terabox_link>`

**Features:**
✅ Memory-optimized downloads
✅ Enhanced retry logic
✅ Progress tracking
✅ Files up to 80MB

**Example:**
`/leech https://terabox.com/s/1abc...`

Bot Status: 🟢 Online
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def debug_handler(update, context):
    """Debug handler"""
    await update.message.reply_text("🤖 Bot is working perfectly!")

async def error_handler(update, context):
    """Global error handler"""
    logger.error(f"❌ ERROR: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ An error occurred. Please try again.")
        except:
            pass

async def run_health_server():
    """Run health server in background"""
    port = int(os.getenv('PORT', 8000))
    health_server = SimpleHealthServer()
    await health_server.start(port)

async def run_bot():
    """Run the Telegram bot"""
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
    application.add_handler(CommandHandler("leech", leech_handler_v2))
    application.add_handler(CommandHandler("debug", debug_handler))
    application.add_error_handler(error_handler)
    
    logger.info("📝 Handlers added successfully")
    
    # Start bot with proper settings
    await application.initialize()
    await application.start()
    
    logger.info("🚀 Starting bot polling...")
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("✅ Bot started successfully!")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

async def main():
    """Main function"""
    try:
        # Ensure single instance
        lock_fd = ensure_single_instance()
        
        logger.info("🚀 Starting Terabox Leech Pro Bot...")
        
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
    
