#!/usr/bin/env python3
# bot.py - ENHANCED SAFE VERSION USING ONLY YOUR 3 PACKAGES

import asyncio
import logging
import os
import sys
import tempfile
import fcntl
import time
import httpx
import psutil
from telegram.ext import Application, CommandHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class SimpleHealthServer:
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
    await update.message.reply_text(
        "🔥 **Terabox Leech Pro Bot** 🔥\n\n"
        "Send: `/leech <terabox_link>`\n\n"
        "**Enhanced Features (Testing):**\n"
        "✅ HTTPx integration ready\n"
        "✅ Memory monitoring active\n"
        "✅ 120MB optimization planned\n\n"
        "**Status:** ✅ Online (Safe Enhanced)\n"
        "**Packages:** 3 core packages only"
    )

async def debug_handler(update, context):
    memory = psutil.virtual_memory()
    await update.message.reply_text(
        f"🤖 **Enhanced bot working!**\n\n"
        f"🧠 **Memory:** {memory.available/(1024*1024):.1f}MB available\n"
        f"📊 **CPU:** {psutil.cpu_percent()}%\n"
        f"🔧 **HTTPx:** {httpx.__version__} ready\n"
        f"📦 **Packages:** 3 core only"
    )

async def safe_enhanced_leech_handler(update, context):
    """Safe enhanced leech - tests URL validation only"""
    try:
        text = update.effective_message.text or ""
        parts = text.split(maxsplit=1)
        
        if len(parts) < 2:
            await update.message.reply_text(
                "**🔥 Safe Enhanced Leech Test 🔥**\n\n"
                "**Usage:** `/leech <terabox_link>`\n\n"
                "**Current Test Phase:**\n"
                "✅ URL validation\n"
                "✅ Memory monitoring\n"
                "✅ HTTPx connection test\n"
                "⏳ Full download (next phase)\n\n"
                "**Example:**\n"
                "`/leech https://terabox.com/test`"
            )
            return
        
        url = parts[1].strip()
        
        # Step 1: Validate URL
        if not any(domain in url.lower() for domain in ["terabox", "1024tera"]):
            await update.message.reply_text("❌ Please provide a valid Terabox link.")
            return
        
        status = await update.message.reply_text("🔍 **Testing enhanced validation...**")
        
        # Step 2: Test HTTPx connection (safe test)
        try:
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Test connection to a safe endpoint
                test_response = await client.get("https://httpbin.org/status/200")
                connection_status = "✅ HTTPx working" if test_response.status_code == 200 else "❌ HTTPx issue"
        except Exception as e:
            connection_status = f"⚠️ HTTPx test: {str(e)[:50]}"
        
        # Step 3: Memory check
        memory = psutil.virtual_memory()
        memory_status = f"🧠 {memory.available/(1024*1024):.0f}MB available"
        
        # Step 4: Show enhanced test results
        await status.edit_text(
            f"✅ **Enhanced Validation Complete**\n\n"
            f"🔗 **URL:** Valid Terabox detected\n"
            f"📡 **HTTPx:** {connection_status}\n"
            f"🧠 **Memory:** {memory_status}\n"
            f"📦 **Packages:** 3 core packages working\n\n"
            f"🎯 **Next Phase:** Full download functionality\n"
            f"💡 **Ready for:** Real terabox resolution"
        )
        
        logger.info(f"✅ Safe enhanced test completed for: {url[:50]}")
        
    except Exception as e:
        logger.error(f"❌ Safe enhanced error: {e}")
        try:
            await update.message.reply_text(f"❌ **Enhanced Test Error**\n\n``````")
        except:
            pass

async def error_handler(update, context):
    logger.error(f"❌ ERROR: {context.error}")

async def run_health_server():
    port = int(os.getenv('PORT', 8000))
    health_server = SimpleHealthServer()
    await health_server.start(port)

async def run_bot():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("❌ BOT_TOKEN not found!")
        sys.exit(1)
    
    logger.info(f"🔑 Safe enhanced bot token: {bot_token[:10]}...")
    
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("leech", safe_enhanced_leech_handler))
    application.add_handler(CommandHandler("debug", debug_handler))
    application.add_error_handler(error_handler)
    
    logger.info("📝 Safe enhanced handlers added")
    
    await application.initialize()
    await application.start()
    
    logger.info("🚀 Starting safe enhanced polling...")
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("✅ Safe enhanced bot started!")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Safe enhanced bot stopped")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

async def main():
    try:
        lock_fd = ensure_single_instance()
        logger.info("🚀 Starting SAFE ENHANCED Terabox Bot...")
        
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
        logger.info("🛑 Safe enhanced bot stopped")
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        sys.exit(1)
    
