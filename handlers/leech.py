# handlers/leech.py
from telegram import Update
from telegram.ext import ContextTypes
from utils.validators import is_terabox_url
from services.terabox import TeraboxResolver
from services.downloader import fetch_to_temp, FileMeta
from services.uploader import send_file
from config import TELEGRAM_MAX_UPLOAD
from utils.text import TOO_LARGE_TEXT, INVALID_URL_TEXT, CAPTION_FMT

resolver = TeraboxResolver()

async def leech_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /leech <terabox_link>")
        return

    url = parts[1].strip()

    if not is_terabox_url(url):
        await update.message.reply_text(INVALID_URL_TEXT)
        return

    await update.message.reply_text("Resolving Terabox link...")

    try:
        meta: FileMeta = await resolver.resolve(url)
    except Exception as e:
        await update.message.reply_text(f"Failed to resolve link: {e}")
        return

    if meta.size and meta.size > TELEGRAM_MAX_UPLOAD:
        await update.message.reply_text(TOO_LARGE_TEXT.format(size=meta.human_size()))
        return

    await update.message.reply_text("Downloading...")

    try:
        tmp_path, meta = await fetch_to_temp(meta)
    except Exception as e:
        await update.message.reply_text(f"Download failed: {e}")
        return

    try:
        caption = CAPTION_FMT.format(name=meta.name, size=meta.human_size())
        await send_file(context.application, update.effective_chat.id, tmp_path, meta, caption)
    except Exception as e:
        await update.message.reply_text(f"Upload failed: {e}")
