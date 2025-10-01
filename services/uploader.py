
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
    
    def read(self, size: int = -1) -> bytes:
        """Memory-monitored read with adaptive chunk sizing"""
        if size == -1:
            size = self.chunk_size
        
        # Dynamic memory monitoring
        memory = psutil.virtual_memory()
        available_mb = memory.available / (1024 * 1024)
        
        if available_mb < 100:  # Critical memory level
            size = min(size, 64 * 1024)  # 64KB emergency chunks
            logger.warning(f"🚨 Critical memory: {available_mb:.1f}MB, using 64KB chunks")
        elif available_mb < 200:  # Low memory
            size = min(size, 256 * 1024)  # 256KB reduced chunks
            logger.info(f"⚠️ Low memory: {available_mb:.1f}MB, using 256KB chunks")
        
        # Read data
        data = self._file_handle.read(size)
        self._position += len(data)
        
        # Progress logging every 2MB
        if len(data) > 0 and self._position % (2 * 1024 * 1024) == 0:
            progress = (self._position / self.file_size) * 100
            logger.info(f"📤 Streaming progress: {progress:.1f}% ({self._position:,}/{self.file_size:,} bytes)")
        
        return data
    
    def seek(self, position: int):
        """Seek to position in file"""
        if self._file_handle:
            self._file_handle.seek(position)
            self._position = position
    
    def tell(self) -> int:
        """Get current position"""
        return self._position
    
    def close(self):
        """Close file handle"""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

def _format_size(bytes_count: int) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"

def probe_video_info(file_path: str) -> dict:
    """Get video information using ffprobe"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", file_path
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            
            # Extract video info
            video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
            format_info = data.get('format', {})
            
            return {
                'duration': int(float(format_info.get('duration', 0))),
                'width': int(video_stream.get('width', 0)) if video_stream else 0,
                'height': int(video_stream.get('height', 0)) if video_stream else 0,
                'has_video': video_stream is not None
            }
    except Exception as e:
        logger.warning(f"⚠️ Video probe failed: {e}")
    
    return {'duration': None, 'width': None, 'height': None, 'has_video': False}

def create_video_thumbnail(file_path: str) -> Optional[str]:
    """Create video thumbnail"""
    try:
        fd, thumb_path = tempfile.mkstemp(prefix="thumb_", suffix=".jpg")
        os.close(fd)
        
        # Create thumbnail at 3 second mark
        subprocess.run([
            "ffmpeg", "-y", "-ss", "3", "-i", file_path,
            "-vframes", "1", "-vf", "scale=320:240:force_original_aspect_ratio=increase",
            "-q:v", "5", thumb_path
        ], capture_output=True, timeout=30)
        
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            logger.info(f"🖼️ Thumbnail created: {thumb_path}")
            return thumb_path
        else:
            logger.warning(f"⚠️ Thumbnail creation failed")
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            
    except Exception as e:
        logger.warning(f"⚠️ Thumbnail error: {e}")
    
    return None

async def stream_upload_media(context, chat_id: int, file_path: str, filename: str) -> bool:
    """Advanced streaming upload with intelligent media type detection"""
    
    logger.info(f"DEBUG: Type of context: {type(context)}")
    logger.info(f"DEBUG: Type of context.bot: {type(context.bot)}") # CRUCIAL DEBUGGING LINE
    
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
    
    # Enhanced file type detection
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
                logger.info(f"🎬 Streaming as video with metadata...")
                
                # Prepare thumbnail
                thumb_file = None
                if thumbnail_path:
                    thumb_file = open(thumbnail_path, 'rb')
                
                try:
                    await context.bot.send_video(
                        chat_id=chat_id,
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
                logger.info(f"🎵 Streaming as audio...")
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=stream,
                    duration=video_info.get('duration') if video_info else None,
                    caption=caption,
                    read_timeout=upload_timeout,
                    write_timeout=upload_timeout,
                    connect_timeout=60
                )
                
            elif is_photo and file_size < 10 * 1024 * 1024:  # Photos under 10MB
                logger.info(f"🖼️ Streaming as photo...")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=stream,
                    caption=caption,
                    read_timeout=upload_timeout,
                    write_timeout=upload_timeout,
                    connect_timeout=60
                )
                
            else:
                logger.info(f"📄 Streaming as document...")
                
                # Prepare thumbnail for document if available
                thumb_file = None
                if thumbnail_path:
                    thumb_file = open(thumbnail_path, 'rb')
                
                try:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=stream,
                        caption=caption,
                        thumbnail=thumb_file,
                        read_timeout=upload_timeout,
                        write_timeout=upload_timeout,
                        connect_timeout=60
                    )
                finally:
                    if thumb_file:
                        thumb_file.close()
        
        logger.info(f"✅ Streaming upload completed successfully!")
        return True
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Streaming upload failed: {error_msg}")
        
        # Enhanced error handling
        if "timeout" in error_msg.lower():
            raise Exception(f"❌ Upload timeout - File too large or connection too slow. Try again later.")
        elif "file too large" in error_msg.lower():
            raise Exception(f"❌ File exceeds Telegram's limits. Max size: 2GB for videos, 50MB for other files.")
        elif "memory" in error_msg.lower() or "oom" in error_msg.lower():
            raise Exception(f"❌ Insufficient memory for upload. Server resources exhausted.")
        else:
            raise Exception(f"❌ Upload failed: {error_msg}")
            
    finally:
        # Cleanup thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                os.remove(thumbnail_path)
                logger.info(f"🧹 Thumbnail cleaned up")
            except Exception as e:
                logger.warning(f"⚠️ Thumbnail cleanup error: {e}")

# Legacy compatibility functions
async def upload_media(context, chat_id: int, file_path: str, filename: str):
    """Legacy wrapper for streaming upload"""
    return await stream_upload_media(context, chat_id, file_path, filename)
