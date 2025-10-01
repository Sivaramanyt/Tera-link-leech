
import os
import logging
import psutil
from mimetypes import guess_type

logger = logging.getLogger(__name__)

class StreamingFileReader:
    """Efficient streaming file reader"""

    def __init__(self, file_path: str, chunk_size: int = 512 * 1024):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.file_size = os.path.getsize(file_path)
        self._file_handle = None
        self.name = os.path.basename(file_path)
        logger.info(f"📤 StreamingFileReader initialized: {self.name} ({self.file_size} bytes)")

    def __enter__(self):
        self._file_handle = open(self.file_path, 'rb')
        logger.info("📂 File handle opened for streaming upload")
        return self

    def read(self, size=None):
        return self._file_handle.read(size or self.chunk_size)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file_handle:
            self._file_handle.close()
            logger.info("📂 File handle closed after streaming upload")


def _format_size(size: int) -> str:
    """Format size in human-readable format"""
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size_float = float(size)
    i = 0
    while size_float >= 1024 and i < len(units) - 1:
        size_float /= 1024
        i += 1
    return f"{size_float:.2f} {units[i]}"


async def stream_upload_media(context, chat_id: int, file_path: str, filename: str) -> bool:
    file_size = os.path.getsize(file_path)
    available_mb = psutil.virtual_memory().available / (1024 * 1024)
    logger.info(f"🚀 Starting upload: {filename} ({_format_size(file_size)})")
    logger.info(f"🧠 Available memory: {available_mb:.2f} MB")

    if available_mb < 150:
        raise Exception(f"❌ Insufficient memory for upload: {available_mb:.2f} MB")

    mime_type, _ = guess_type(filename)
    file_ext = os.path.splitext(filename)[1].lower()

    is_video = (mime_type and mime_type.startswith("video/")) or file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm']
    is_audio = (mime_type and mime_type.startswith("audio/")) or file_ext in ['.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wav']
    is_photo = (mime_type and mime_type.startswith("image/")) or file_ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']

    caption = f"📁 **{filename}**\n📏 **Size:** {_format_size(file_size)}\n\n💎 via @Terabox_leech_pro_bot"

    with StreamingFileReader(file_path) as stream:
        try:
            if is_video:
                # Modified this line to explicitly use keyword arguments for all parameters
                await context.bot.send_video(chat_id=chat_id, video=stream, caption=caption, supports_streaming=True)
            elif is_audio:
                await context.bot.send_audio(chat_id=chat_id, audio=stream, caption=caption)
            elif is_photo and file_size < 10 * 1024 * 1024:
                await context.bot.send_photo(chat_id=chat_id, photo=stream, caption=caption)
            else:
                await context.bot.send_document(chat_id=chat_id, document=stream, caption=caption)

            logger.info("✅ Upload successful")
            return True
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            raise
```
