# services/uploader.py
import os
from telegram.ext import Application
from telegram.constants import ChatAction
from telegram import InputFile
from services.downloader import FileMeta

async def send_file(app: Application, chat_id: int, path: str, meta: FileMeta, caption: str):
    await app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
    size = os.path.getsize(path)
    # Stream as document
    with open(path, "rb") as f:
        await app.bot.send_document(
            chat_id=chat_id,
            document=InputFile(f, filename=meta.name),
            caption=caption,
            disable_content_type_detection=True,
        )
    try:
        os.remove(path)
    except Exception:
        pass
