#!/usr/bin/env python3
# bot.py

import asyncio
import logging
import os
import sys
import signal
import tempfile
import fcntl
from pathlib import Path

# Import bot components
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import TelegramError, NetworkError
from handlers.leech import leech_handler_v2
from handlers.start import start_handler
from services.health import create_health_server

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class SingleInstanceBot:
    """Enhanced Telegram bot with single instance protection and health monitoring"""
    
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.port = int(os.getenv('PORT', 8000))
        self.application = None
        self.health_server = None
        self.lock_fd = None
        
        if not self.bot_token:
            logger.error("❌ BOT_TOKEN environment variable not found!")
            sys.exit(1)
        
        logger.info(f"🔑 Bot token found: {self.bot_token[:10]}...")
        logger.info(f"🚀 Starting Terabox Leech Pro Bot with enhanced single instance protection...")
    
    def ensure_single_instance(self):
        """Ensure only one bot instance runs at a time"""
        try:
            # Create a lock file in temp directory
            lock_file = os.path.join(tempfile.gettempdir(), 'terabox_leech_bot.lock')
            self.lock_fd = open(lock_file, 'w')
            
            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Write current process ID
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
            
            logger.info(f"🔒 Single instance lock acquired: PID {os.getpid()}")
            return True
            
        except (IOError, OSError) as e:
            logger.error(f"❌ Another bot instance is already running!")
            logger.error(f"❌ Lock error: {e}")
            return False
    
    def release_lock(self):
        """Release the instance lock"""
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
                logger.info("🔓 Instance lock released")
            except Exception as e:
                logger.warning(f"⚠️ Lock release error: {e}")
    
    def setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers"""
        def signal_handler(sig, frame):
            logger.info(f"🛑 Received signal {sig}, initiating graceful shutdown...")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def setup_handlers(self):
        """Setup bot command and message handlers"""
        logger.info("📝 Adding handlers...")
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", start_handler))
        logger.info("✅ START handler added")
        
        self.application.add_handler(CommandHandler("leech", leech_handler_v2))
        logger.info("✅ LEECH handler added")
        
        # Add debug message handler for testing
        async def debug_handler(update, context):
            logger.info(f"🐛 Debug message from {update.effective_user.id}: {update.message.text}")
            await update.message.reply_text("🤖 Bot is alive and responding!")
        
        self.application.add_handler(CommandHandler("debug", debug_handler))
        logger.info("✅ DEBUG handler added")
        
        # Global error handler
        async def error_handler(update, context):
            logger.error(f"❌ ERROR occurred: {context.error}")
            logger.error(f"❌ Update that caused error: {update}")
            
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "❌ An error occurred while processing your request. Please try again."
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to send error message: {e}")
        
        self.application.add_error_handler(error_handler)
        logger.info("✅ ERROR handler added")
    
    async def start_health_server(self):
        """Start the health check server"""
        try:
            logger.info("🏥 Starting health check server...")
            self.health_server = await create_health_server(self.port)
            logger.info(f"🏥 Health check server started on port {self.port}")
        except Exception as e:
            logger.error(f"❌ Failed to start health server: {e}")
            raise
    
    async def initialize_bot(self):
        """Initialize the Telegram bot application"""
        try:
            # Create application with enhanced settings
            self.application = (
                Application.builder()
                .token(self.bot_token)
                .concurrent_updates(1)  # Process updates one at a time
                .build()
            )
            
            # Setup handlers
            self.setup_handlers()
            
            # Initialize application
            await self.application.initialize()
            logger.info("✅ Bot application initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Bot initialization failed: {e}")
            return False
    
    async def start_polling(self):
        """Start bot polling with enhanced error handling"""
        try:
            # Clear any pending updates and start polling
            await self.application.start()
            logger.info("📡 Starting bot polling...")
            
            # Start polling with drop_pending_updates to avoid conflicts
            await self.application.updater.start_polling(
                drop_pending_updates=True,  # Important: Drop old updates
                allowed_updates=None
            )
            
            logger.info("✅ Bot polling started successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start polling: {e}")
            return False
    
    async def shutdown(self):
        """Graceful shutdown of all services"""
        logger.info("🛑 Starting graceful shutdown...")
        
        try:
            # Stop bot polling
            if self.application and self.application.updater:
                logger.info("📡 Stopping bot polling...")
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                logger.info("✅ Bot stopped successfully")
            
            # Stop health server
            if self.health_server:
                logger.info("🏥 Stopping health server...")
                self.health_server.should_exit = True
                logger.info("✅ Health server stopped")
            
            # Release instance lock
            self.release_lock()
            
            logger.info("✅ Graceful shutdown completed")
            
        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")
        
        finally:
            # Force exit if needed
            sys.exit(0)
    
    async def run(self):
        """Main run method"""
        try:
            # Check single instance
            if not self.ensure_single_instance():
                logger.error("❌ Exiting due to multiple instance conflict")
                sys.exit(1)
            
            # Setup signal handlers
            self.setup_signal_handlers()
            
            # Start health server
            await self.start_health_server()
            
            # Initialize and start bot
            if not await self.initialize_bot():
                logger.error("❌ Bot initialization failed")
                sys.exit(1)
            
            if not await self.start_polling():
                logger.error("❌ Bot polling failed to start")
                sys.exit(1)
            
            # Keep running
            logger.info("🎯 Bot is fully operational and ready!")
            
            # Run indefinitely
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard interrupt received")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
        finally:
            await self.shutdown()

# Enhanced start handler
async def start_handler(update, context):
    """Enhanced start handler with bot status"""
    welcome_message = f"""
🔥 **Terabox Leech Pro Bot** 🔥

Welcome! I can download files from Terabox and upload them to Telegram.

**Commands:**
• `/start` - Show this help message
• `/leech <terabox_link>` - Download and upload file
• `/debug` - Test bot responsiveness

**Features:**
✅ Memory-optimized for free tier hosting
✅ Enhanced retry logic for unstable servers  
✅ Progress tracking with speed indicators
✅ Support for files up to 80MB
✅ Automatic error recovery
✅ Single instance protection

**Example:**
`/leech https://terabox.com/s/1abc...`

**Bot Status:** 🟢 Online and Ready
**Instance ID:** `{os.getpid()}`
"""
    
    try:
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        logger.info(f"✅ Start message sent to user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"❌ Failed to send start message: {e}")

async def main():
    """Main entry point"""
    bot = SingleInstanceBot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal startup error: {e}")
        sys.exit(1)
