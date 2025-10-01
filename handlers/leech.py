import os
import time
import asyncio
import tempfile
import logging
import psutil

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services.terabox import get_resolver, cleanup_resolver
from services.downloader import fetch_to_temp
from services.uploader import stream_upload_media
from handlers.verification import (
    IS_VERIFY,
    increment_user_leech_count,
    get_user_verification_status,
    generate_verification_link,
    TUT_VID,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 120 * 1024 * 1024  # 120MB
MIN_MEMORY_MB = 150

# Your private channel ID as environment variable
PRIVATE_CHANNEL_ID = int(os.environ.get("PRIVATE_CHANNEL_ID", 0))

def _fmt_size(n: int = None) -> str:
    if n is None:
        return "unknown"
    f = float(n)
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if f < 1024:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{f:.2f} PB"

async def phase21_leech_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if IS_VERIFY:
            count = await increment_user_leech_count(user_id)
            if count > 3:
                verified = await get_user_verification_status(user_id)
                if not verified:
                    ver_link = generate_verification_link(user_id)
                    await update.message.reply_text(
                        f"⚠️ You have reached your free leech limit.\n"
                        f"Please verify to continue:\n{ver_link}\n\n"
                        f"Tutorial: https://www.youtube.com/watch?v={TUT_VID}\n\n"
                        "After verification, send /verify <token>"
                    )
                    return  # stop until verification is done

        text = update.effective_message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "**Usage:** `/leech <terabox_link>`\n"
                "Supports up to 120MB with progress tracking\n"
                "Redirect handling enabled"
            )
            return

        url = parts[1].strip()
        chat_id = update.effective_chat.id
        if not any(d in url.lower() for d in ["terabox", "1024tera"]):
            await update.message.reply_text("❌ Invalid Terabox link.")
            return

        status = await update.message.reply_text("Resolving Terabox link...")

        resolver = await get_resolver()
        try:
            download_url, filename, file_size = await resolver.resolve_url(url)
        finally:
            await cleanup_resolver(resolver)

        if not download_url:
            await status.edit_text("❌ Link resolution failed or expired link.")
            return

        if file_size and file_size > MAX_FILE_SIZE:
            await status.edit_text(f"⚠️ File too large ({_fmt_size(file_size)}). Limit is 120MB.")
            return

        mem_avail = psutil.virtual_memory().available / (1024 * 1024)
        if mem_avail < MIN_MEMORY_MB:
            await status.edit_text("⚠️ Server memory too low for safe operation.")
            return

        await status.edit_text(f"Downloading {filename} ({_fmt_size(file_size) if file_size else 'unknown size'})...")

        start_time = time.time()
        temp_path = await fetch_to_temp(download_url, filename, status, context, chat_id)
        if not temp_path:
            await status.edit_text("❌ Download failed or timed out.")
            return

        elapsed = time.time() - start_time
        actual_size = os.path.getsize(temp_path)
        avg_speed = actual_size / elapsed if elapsed > 0 else 0

        await status.edit_text(f"Download complete: {filename}\n{_fmt_size(actual_size)} in {elapsed:.1f}s\nSpeed: {_fmt_size(int(avg_speed))}/s\nUploading...")

        try:
            with open(temp_path, 'rb') as f:
                await stream_upload_media(context.bot, chat_id, f, filename, actual_size, avg_speed)
                # Forward uploaded file to private channel if configured
                if PRIVATE_CHANNEL_ID:
                    f.seek(0)
                    await context.bot.send_document(
                        chat_id=PRIVATE_CHANNEL_ID,
                        document=f,
                        caption=f"User {user_id} uploaded: {filename}"
                    )
            await status.delete()
        except Exception as e:
            await status.edit_text(f"❌ Upload failed: {str(e)[:100]}")

        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

    except Exception as e:
        logger.error(f"Leech handler error: {e}")
        try:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
        except:
            pass

# Export CommandHandler instance for bot registration
from telegram.ext import CommandHandler
leech_handler = CommandHandler("leech", phase21_leech_handler)
            
