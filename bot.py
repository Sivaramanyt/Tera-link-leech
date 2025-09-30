import os
import logging
import asyncio
import signal
import sys
from telegram.ext import Application, CommandHandler
from handlers.leech import get_enhanced_handler
import httpx

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.application = None
        self.shutting_down = False
    
    async def cleanup_webhook(self):
        """Clean up any existing webhook before starting polling"""
        try:
            token = os.getenv("BOT_TOKEN")
            if not token:
                return
            
            async with httpx.AsyncClient(timeout=30) as client:
                # Delete webhook to prevent conflicts
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/deleteWebhook",
                    json={"drop_pending_updates": True}
                )
                logger.info("Webhook cleanup completed")
                
                # Wait for Telegram to process
                await asyncio.sleep(3)
                
        except Exception as e:
            logger.warning(f"Webhook cleanup failed: {e}")
    
    async def start_bot(self):
        """Start the Telegram bot with conflict handling"""
        token = os.getenv("BOT_TOKEN")
        if not token:
            logger.error("BOT_TOKEN not found in environment")
            return
        
        try:
            # Clean up any existing webhook first
            await self.cleanup_webhook()
            
            # Create application with enhanced configuration
            self.application = (
                Application.builder()
                .token(token)
                .concurrent_updates(True)
                .read_timeout(30)
                .write_timeout(30)
                .connect_timeout(30)
                .pool_timeout(30)
                .get_updates_read_timeout(42)  # Slightly longer timeout
                .get_updates_write_timeout(30)
                .get_updates_connect_timeout(30)
                .get_updates_pool_timeout(30)
                .build()
            )
            
            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_handler))
            self.application.add_handler(get_enhanced_handler())
            
            # Add error handler for conflicts
            self.application.add_error_handler(self.error_handler)
            
            # Initialize the application
            await self.application.initialize()
            await self.application.start()
            
            logger.info("Bot initialized successfully")
            
            # Start polling with retry logic for conflicts
            await self.start_polling_with_retry()
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            await self.shutdown()
    
    async def start_polling_with_retry(self):
        """Start polling with automatic retry on 409 conflicts"""
        max_retries = 10
        retry_count = 0
        
        while retry_count < max_retries and not self.shutting_down:
            try:
                logger.info(f"Starting polling (attempt {retry_count + 1})")
                
                # Start polling with conflict handling
                await self.application.updater.start_polling(
                    drop_pending_updates=True,  # Clear any pending updates
                    allowed_updates=["message", "callback_query"],
                    timeout=40,  # Slightly longer timeout
                    bootstrap_retries=5  # Retry bootstrap on failure
                )
                
                logger.info("✅ Bot polling started successfully")
                break
                
            except Exception as e:
                retry_count += 1
                error_msg = str(e).lower()
                
                if "409" in error_msg or "conflict" in error_msg:
                    logger.warning(f"⚠️ Conflict detected (attempt {retry_count}): {e}")
                    
                    if retry_count < max_retries:
                        # Exponential backoff with randomization
                        wait_time = min(120, 15 * retry_count)
                        logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                        
                        # Try cleanup again
                        await self.cleanup_webhook()
                        continue
                else:
                    logger.error(f"❌ Non-conflict error: {e}")
                    break
        
        if retry_count >= max_retries:
            logger.error("❌ Max retries reached for polling, shutting down")
            await self.shutdown()
    
    async def start_handler(self, update, context):
        """Handle /start command"""
        welcome_msg = (
            "🚀 **Terabox Leech Pro Bot**\n\n"
            "📋 **Commands:**\n"
            "• `/start` - Show this help\n"
            "• `/leech <terabox_link>` - Download and send file\n\n"
            "📝 **Usage:**\n"
            "Send me a Terabox share link and I'll download it for you!\n\n"
            "⚡ **Example:**\n"
            "`/leech https://teraboxurl.com/s/1abc...`\n\n"
            "via @Terabox_leech_pro_bot"
        )
        
        await update.message.reply_text(
            welcome_msg,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    async def error_handler(self, update, context):
        """Handle telegram errors, especially conflicts"""
        error_msg = str(context.error).lower()
        
        if "409" in error_msg or "conflict" in error_msg:
            logger.warning(f"⚠️ Conflict error in handler: {context.error}")
            # Don't restart immediately, let the retry logic in polling handle it
            return
        else:
            logger.error(f"❌ Error in handler: Update {update} caused error {context.error}")
    
    async def shutdown(self):
        """Graceful shutdown"""
        if self.shutting_down:
            return
            
        self.shutting_down = True
        logger.info("🛑 Shutting down bot...")
        
        try:
            if self.application:
                if hasattr(self.application, 'updater') and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                
            logger.info("✅ Bot shutdown complete")
            
        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")

# Global bot manager instance
bot_manager = BotManager()

async def main():
    """Main function with signal handling"""
    logger.info("🚀 Starting Terabox Leech Pro Bot...")
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}")
        asyncio.create_task(bot_manager.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the bot
        await bot_manager.start_bot()
        
        # Keep running until shutdown
        while not bot_manager.shutting_down:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("⌨️ Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
    finally:
        await bot_manager.shutdown()
        logger.info("🏁 Application terminated")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⌨️ Application interrupted by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
            
