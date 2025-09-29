# handlers/leech.py
import os
import asyncio
from mimetypes import guess_type
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services.terabox import TeraboxResolver
from services.downloader import fetch_to_temp

resolver = TeraboxResolver()

def _extract_arg(text: str) -> str | None:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip()

async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str, filename: str):
    mime, _ = guess_type(filename)
    ext = (os.path.splitext(filename)[1] or "").lower()

    # Prefer video endpoint for MP4/MOV
    if (mime and mime.startswith("video/")) or ext in (".mp4", ".mov", ".m4v"):
        await context.bot.send_video(
            chat_id=chat_id,
            video=open(path, "rb"),
            caption=f"File: {filename}",
            supports_streaming=True,
        )
        return

    # Audio endpoint
    if (mime and mime.startswith("audio/")) or ext in (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=open(path, "rb"),
            caption=f"File: {filename}",
        )
        return

    # Image endpoint
    if (mime and mime.startswith("image/")) or ext in (".jpg", ".jpeg", ".png", ".webp"):
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=open(path, "rb"),
            caption=f"File: {filename}",
        )
        return

    # Fallback: document
    await context.bot.send_document(
        chat_id=chat_id,
        document=open(path, "rb"),
        caption=f"File: {filename}",
    )

async def leech_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.effective_message.text or ""
    url = _extract_arg(text)

    if not url:
        await context.bot.send_message(chat_id, "Usage: /leech <terabox_share_url>")
        return

    # Normalize backslashes that some keyboards insert
    url = url.replace("\\", "/").strip()

    status = await context.bot.send_message(chat_id, "Resolving Terabox link...")
    try:
        meta = await resolver.resolve(url)
    except Exception as e:
        await status.edit_text(f"Failed to resolve link: {e}")
        return

    await status.edit_text("Downloading...")
    path = None
    try:
        path, meta = await fetch_to_temp(meta)
        # Choose the best Telegram endpoint for the file type
        await _send_media(context, chat_id, path, meta.name)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"Download failed: {e}")
    finally:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

# register helper to be used by your application builder
def get_handler():
    return CommandHandler("leech", leech_handler)
    
