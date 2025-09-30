import os
import logging
from telegram.ext import Application, CommandHandler
from handlers.leech import get_enhanced_handler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_handler(update, context):
    """Handle /start command - FIXED"""
    welcome_msg = (
        "🚀 <b>Terabox Leech Pro Bot</b>\n\n"
        "📋 <b>Commands:</b>\n"
        "• /start - Show this help\n"
        "• /leech &lt;terabox_link&gt; - Download and send file\n\n"
        "📝 <b>Usage:</b>\n"
        "Send me a Terabox share link and I'll download it for you!\n\n"
        "⚡ <b>Example:</b>\n"
        "<code>/leech https://teraboxurl.com/s/1abc...</code>\n\n"
        "via @Terabox_leech_pro_bot"
    )
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode='HTML',  # Changed from Markdown to HTML
        disable_web_page_preview=True
    )

def main():
    """Main function"""
    # Get bot token
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN not found in environment variables")
        return
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(get_enhanced_handler())
    
    # Start the bot
    logger.info("Starting Terabox Leech Pro Bot...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
