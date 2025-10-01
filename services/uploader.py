# services/uploader.py - STREAMING UPLOAD TECHNOLOGY

import os
import asyncio
import logging
import tempfile
import subprocess
from typing import BinaryIO, Optional
from mimetypes import guess_type
import psutil

logger = logging.getLogger(__name__)

class StreamingFileReader:
    """Memory-efficient streaming file reader for large uploads"""
    
    def __init__(self, file_path: str, chunk_size: int = 512 * 1024):  # 512KB chunks
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.file_size = os.path.getsize(file_path)
        self._file_handle = None
        self._position = 0
        self.name = os.path.basename(file_path)  # Required by python-telegram-bot
        logger.info(f"📤 StreamingFileReader initialized: {self.name} ({self.file_size:,} bytes)")

    def __enter__(self):
        self._file_handle = open(self.file_path, 'rb')
        logger.info(f"📂 File handle opened for streaming upload")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file_handle:
            self._file_handle.close()
            logger.info(f"📂 File handle closed after streaming upload")

    def read(self, size=None):
        if not self._file_handle:
            return b''
        return self._file_handle.read(size or self.chunk_size)

    def seek(self, position):
        if self._file_handle:
            self._file_handle.seek(position)
            self._position = position


def _format_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"
    size_names = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"


def probe_video_info(file_path: str) -> dict:
    """Extract video metadata using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.warning(f"⚠️ ffprobe failed: {result.stderr}")
            return {}
            
        import json
        data = json.loads(result.stdout)
        
        video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
        
        if video_stream:
            return {
                'has_video': True,
                'duration': int(float(data.get('format', {}).get('duration', 0))),
                'width': video_stream.get('width', 0),
                'height': video_stream.get('height', 0)
            }
    except Exception as e:
        logger.warning(f"⚠️ Video probe failed: {e}")
    
    return {'has_video': False}


def create_video_thumbnail(file_path: str) -> Optional[str]:
    """Generate video thumbnail using ffmpeg"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as thumb_file:
            thumb_path = thumb_file.name
        
        cmd = [
            'ffmpeg', '-i', file_path, '-ss', '00:00:01.000', '-vframes', '1',
            '-y', thumb_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        
        if result.returncode == 0 and os.path.exists(thumb_path):
            logger.info(f"🖼️ Thumbnail created: {thumb_path}")
            return thumb_path
        else:
            logger.warning(f"⚠️ Thumbnail creation failed")
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
    except Exception as e:
        logger.warning(f"⚠️ Thumbnail creation error: {e}")
    
    return None


async def stream_upload_media(context, chat_id: int, file_path: str, filename: str) -> bool:
    """Advanced streaming upload with intelligent media type detection"""
    
    file_size = os.path.getsize(file_path)
    
    logger.info(f"🚀 Starting streaming upload: {filename} ({_format_size(file_size)})")
    
    # Pre-upload memory check
    memory = psutil.virtual_memory()
    available_mb = memory.available / (1024 * 1024)
    logger.info(f"🧠 Pre-upload memory: {available_mb:.1f}MB available")
    
    if available_mb < 150:  # Need minimum 150MB for safe upload
        raise Exception(f"❌ Insufficient memory for upload: {available_mb:.1f}MB available, 150MB minimum required")
    
    # Detect file type
    mime_type, _ = guess_type(filename)
    file_ext = os.path.splitext(filename)[1].lower()
    
    is_video = (mime_type and mime_type.startswith('video/')) or file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm']
    is_audio = (mime_type and mime_type.startswith('audio/')) or file_ext in ['.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wav']
    is_photo = (mime_type and mime_type.startswith('image/')) or file_ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']
    
    logger.info(f"📋 File type detection: Video={is_video}, Audio={is_audio}, Photo={is_photo}")
    
    # Prepare caption
    caption = f"📁 **{filename}**\n📏 **Size:** {_format_size(file_size)}\n\n💎 via @Terabox_leech_pro_bot"
    
    # Get video info if it's a video
    video_info = None
    thumbnail_path = None
    
    if is_video:
        video_info = probe_video_info(file_path)
        if video_info.get('has_video'):
            thumbnail_path = create_video_thumbnail(file_path)
        logger.info(f"🎬 Video info: {video_info}")
    
    try:
        with StreamingFileReader(file_path, chunk_size=512*1024) as stream:
            
            # Enhanced timeout settings for large files
            upload_timeout = min(600, max(120, file_size // (1024 * 1024) * 10))  # 10s per MB, max 10min
            logger.info(f"⏰ Upload timeout set to {upload_timeout}s")
            
            if is_video and video_info and video_info.get('has_video'):
                logger.info("🎬 Streaming as video with metadata...")
                
                thumb_file = None
                if thumbnail_path:
                    thumb_file = open(thumbnail_path, 'rb')
                
                try:
                    await context.bot.send_video(
                        chat_id,
                        video=stream,
                        duration=video_info.get('duration'),
                        width=video_info.get('width'),
                        height=video_info.get('height'),
                        caption=caption,
                        supports_streaming=True,
                        thumbnail=thumb_file,
                        read_timeout=upload_timeout,
                        write_timeout=upload_timeout,
                        connect_timeout=60
                    )
                finally:
                    if thumb_file:
                        thumb_file.close()
                        
            elif is_audio:
                logger.info("🎵 Streaming as audio...")
                await context.bot.send_audio(
                    chat_id,
                    audio=stream,
                    duration=video_info.get('duration') if video_info else None,
                    caption=caption,
                    read_timeout=upload_timeout,
                    write_timeout=upload_timeout,
                    connect_timeout=60
                )
                
            elif is_photo and file_size < 10 * 1024 * 1024:  # Photos under 10MB
                logger.info("🖼️ Streaming as photo...")
                await context.bot.send_photo(
                    chat_id,
                    photo=stream,
                    caption=caption,
                    read_timeout=upload_timeout,
                    write_timeout=upload_timeout,
                    connect_timeout=60
                )
                
            else:
                logger.info("📄 Streaming as document...")
                await context.bot.send_document(
                    chat_id,
                    document=stream,
                    caption=caption,
                    read_timeout=upload_timeout,
                    write_timeout=upload_timeout,
                    connect_timeout=60
                )
    
    finally:
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                os.remove(thumbnail_path)
            except Exception as e:
                logger.warning(f"Thumbnail cleanup error: {e}")
    
    logger.info("✅ Streaming upload completed successfully!")
    return True
        
