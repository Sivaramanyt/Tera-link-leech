# handlers/start.py

import logging
import os
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start handler with comprehensive bot information"""
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"
    
    logger.info(f"👤 Start command from user: {user_id} ({user_name})")
    
    welcome_message = f"""
🔥 **Terabox Leech Pro Bot v2.0** 🔥

Hello **{user_name}**! Welcome to the enhanced Terabox file downloader.

**🎯 Commands:**
• `/start` - Show this help message
• `/leech <terabox_link>` - Download and upload file  
• `/debug` - Test bot responsiveness

**⚡ Enhanced Features:**
✅ **Memory-optimized** for free tier hosting
✅ **Ultra-fast downloads** with aggressive retry logic
✅ **Smart upload strategy** (document/video detection)
✅ **Progress tracking** with real-time speed indicators
✅ **Resume capability** for interrupted downloads
✅ **Single instance protection** (no conflicts)
✅ **80MB file limit** optimized for Koyeb free tier

**📋 Supported Links:**
• `terabox.com/s/...`
• `1024terabox.com/s/...`
• `teraboxapp.com/s/...`

**💡 Usage Example:**
/leech https://terabox.com/s/1abc...
**🔧 Technical Info:**
• **Bot Status:** 🟢 Online and Ready
• **Instance PID:** `{os.getpid()}`
• **Memory Management:** ✅ Active
• **Health Monitoring:** ✅ Active

**⚠️ Important Notes:**
• Files larger than 80MB will be rejected
• Bot processes one request at a time
• Download speeds depend on Terabox server stability
• Uploads are memory-optimized for reliability

🚀 **Ready to leech files!** Send `/leech` with your Terabox link.
"""
    
    try:
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        logger.info(f"✅ Enhanced start message sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to send start message to {user_id}: {e}")
        
        # Fallback simple message
        try:
            await update.message.reply_text(
                "🤖 Terabox Leech Bot is online!\n\n"
                "Send /leech <terabox_link> to download files."
            )
        except Exception as fallback_error:
            logger.error(f"❌ Fallback message also failed: {fallback_error}")
            
