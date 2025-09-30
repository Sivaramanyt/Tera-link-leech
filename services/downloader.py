# services/downloader.py

import asyncio
import tempfile
import os
import time
import httpx
import logging
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class FileMeta:
    def __init__(self, name: str, size: Optional[int] = None, url: str = ""):
        self.name = name
        self.size = size
        self.url = url

class DownloadError(Exception):
    """Custom exception for download errors"""
    pass

def calculate_optimal_chunk_size(file_size: Optional[int], attempt: int) -> int:
    """Calculate optimal chunk size for speed based on file size and retry attempt"""
    # Start with much larger chunks for speed
    if not file_size:
        base_size = 262144  # 256KB default
    elif file_size < 5 * 1024 * 1024:  # < 5MB
        base_size = 131072  # 128KB for small files
    elif file_size < 50 * 1024 * 1024:  # < 50MB  
        base_size = 524288  # 512KB for medium files
    else:  # Large files
        base_size = 1048576  # 1MB for large files
    
    # Reduce chunk size on retries for stability (like your original logic)
    if attempt > 3:
        base_size = base_size // 2
    if attempt > 6:
        base_size = max(base_size // 2, 32768)  # Min 32KB (your original size)
    
    return base_size

def format_speed(bytes_per_sec: float) -> str:
    """Format speed to human readable string"""
    if bytes_per_sec == 0:
        return "0 B/s"
    
    for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
        if bytes_per_sec < 1024.0:
            return f"{bytes_per_sec:.1f} {unit}"
        bytes_per_sec /= 1024.0
    return f"{bytes_per_sec:.1f} TB/s"

async def fetch_to_temp(
    meta: FileMeta,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    max_retries: int = 8,  # Reduced for faster failure while keeping reliability
    base_chunk_size: int = None  # Dynamic chunk sizing
) -> tuple[str, FileMeta]:
    """
    SPEED-OPTIMIZED download with enhanced retry logic and your existing robust error handling
    """
    logger.info(f"🚀 Starting SPEED-OPTIMIZED download: {meta.name} ({meta.size} bytes)")
    
    # Create temp file
    fd, temp_path = tempfile.mkstemp(
        prefix="terabox_",
        suffix=f"_{meta.name}",
        dir=None
    )
    os.close(fd)
    
    downloaded = 0
    retry_count = 0
    consecutive_failures = 0  # Track consecutive failures (keeping your logic)
    download_start_time = time.time()
    
    while retry_count < max_retries:
        try:
            # Calculate optimal chunk size for this attempt
            chunk_size = calculate_optimal_chunk_size(meta.size, retry_count + 1)
            logger.info(f"🚀 SPEED attempt #{retry_count + 1}/{max_retries} - Chunk: {chunk_size//1024}KB from: {meta.url[:100]}...")
            
            # Enhanced HTTP client with SPEED optimizations
            timeout = httpx.Timeout(
                timeout=90.0,     # Reduced from 120s for faster failure
                connect=20.0,     # Faster connection timeout
                read=45.0,        # Faster read timeout  
                write=20.0,       # Faster write timeout
                pool=20.0         # Faster pool timeout
            )
            
            # Speed-optimized connection settings
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_keepalive_connections=3,  # Allow more connections for speed
                    max_connections=5,            # Multiple connections
                    keepalive_expiry=60.0         # Longer keepalive for speed
                ),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip, deflate, br",  # Enable compression for speed
                    "Connection": "keep-alive",   # Keep connections alive for speed
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
            ) as client:
                
                headers = {}
                if downloaded > 0:
                    headers["Range"] = f"bytes={downloaded}-"
                    logger.info(f"📊 RESUMING download from byte {downloaded:,}")
                
                # Start streaming request
                async with client.stream("GET", meta.url, headers=headers) as response:
                    logger.info(f"📡 Response status: {response.status_code}")
                    
                    # Handle different status codes (keeping your robust error handling)
                    if response.status_code == 400:
                        logger.error(f"❌ 400 Bad Request - Link may be expired")
                        raise DownloadError("Download link expired or invalid")
                    elif response.status_code == 404:
                        logger.error(f"❌ 404 Not Found - File not available")
                        raise DownloadError("File not found on server")
                    elif response.status_code == 403:
                        logger.error(f"❌ 403 Forbidden - Access denied")
                        raise DownloadError("Access denied to file")
                    elif response.status_code not in [200, 206]:
                        logger.error(f"❌ Unexpected status code: {response.status_code}")
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            raise DownloadError(f"Server consistently returning {response.status_code}")
                        continue
                    
                    # Reset consecutive failures on successful response
                    consecutive_failures = 0
                    
                    # Get content length
                    content_length = response.headers.get("content-length")
                    if content_length:
                        total_size = int(content_length)
                        if downloaded == 0 and not meta.size:
                            meta.size = total_size
                        expected_total = downloaded + total_size
                        logger.info(f"📏 Content length: {total_size:,} bytes, Expected total: {expected_total:,}")
                    else:
                        total_size = meta.size or 0
                        expected_total = total_size
                        logger.warning(f"⚠️ No content-length header, using meta size: {total_size:,}")
                    
                    # Open file for writing
                    mode = "ab" if downloaded > 0 else "wb"
                    bytes_in_chunk = 0
                    bytes_this_attempt = 0
                    last_progress_time = time.time()
                    last_speed_log = time.time()
                    attempt_start_time = time.time()
                    
                    try:
                        with open(temp_path, mode) as f:
                            logger.info(f"📝 Writing to: {temp_path}")
                            
                            async for chunk in response.aiter_bytes(chunk_size):
                                if not chunk:
                                    continue
                                
                                f.write(chunk)
                                downloaded += len(chunk)
                                bytes_in_chunk += len(chunk)
                                bytes_this_attempt += len(chunk)
                                
                                # SPEED-OPTIMIZED progress reporting (every 1MB instead of 3 seconds)
                                current_time = time.time()
                                if on_progress and (downloaded - (downloaded % (1024 * 1024))) % (1024 * 1024) == 0:
                                    try:
                                        on_progress(downloaded, expected_total)
                                        last_progress_time = current_time
                                    except Exception as e:
                                        logger.warning(f"⚠️ Progress callback error: {e}")
                                
                                # Log speed every 5MB for monitoring
                                if bytes_this_attempt > 0 and bytes_this_attempt % (5 * 1024 * 1024) == 0:
                                    attempt_elapsed = current_time - attempt_start_time
                                    if attempt_elapsed > 0:
                                        speed = bytes_this_attempt / attempt_elapsed
                                        total_elapsed = current_time - download_start_time
                                        avg_speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                                        logger.info(f"🚀 Current speed: {format_speed(speed)}, Avg: {format_speed(avg_speed)}, Downloaded: {downloaded:,}/{expected_total:,}")
                            
                            # Final progress update
                            if on_progress:
                                try:
                                    on_progress(downloaded, expected_total)
                                except Exception:
                                    pass
                            
                    except Exception as chunk_error:
                        logger.error(f"💥 Chunk processing error: {chunk_error}")
                        raise chunk_error
                    
                    # Check if download completed successfully
                    if expected_total and downloaded >= expected_total:
                        total_elapsed = time.time() - download_start_time
                        avg_speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                        logger.info(f"✅ SPEED download completed: {downloaded:,}/{expected_total:,} bytes in {total_elapsed:.1f}s")
                        logger.info(f"🚀 Average speed: {format_speed(avg_speed)}")
                        break
                    elif not expected_total and bytes_in_chunk > 0:
                        total_elapsed = time.time() - download_start_time
                        avg_speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                        logger.info(f"✅ SPEED download completed: {downloaded:,} bytes (no size info) in {total_elapsed:.1f}s")
                        logger.info(f"🚀 Average speed: {format_speed(avg_speed)}")
                        break
                    else:
                        # Incomplete download - will retry
                        logger.warning(f"⚠️ Download incomplete: {downloaded:,}/{expected_total:,} bytes, will retry")
                        raise DownloadError(f"Incomplete download: got {downloaded:,}, expected {expected_total:,}")
                        
        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            retry_count += 1
            consecutive_failures += 1
            logger.error(f"⏰ Timeout error (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                # FASTER backoff for speed: 1s, 2s, 4s, 8s, 15s (max)
                wait_time = min(2 ** (retry_count - 1), 15)
                logger.info(f"⚡ FAST retry in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue
                
        except (httpx.HTTPError, DownloadError) as e:
            retry_count += 1
            consecutive_failures += 1
            logger.error(f"🌐 HTTP/Download error (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                # FASTER backoff with shorter waits: 2s, 4s, 8s, 15s, 30s (max)
                wait_time = min(2 ** retry_count, 30)
                logger.info(f"⚡ FAST retry in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue
                
        except Exception as e:
            retry_count += 1
            consecutive_failures += 1
            logger.error(f"❌ Unexpected error (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                # FASTER backoff: 3s, 6s, 12s, 24s, 45s (max)
                wait_time = min(3 * (2 ** (retry_count - 1)), 45)
                logger.info(f"⚡ FAST retry in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue
    
    # Check if we exhausted all retries
    if retry_count >= max_retries:
        logger.error(f"❌ SPEED download failed after {max_retries} attempts")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        
        # Better error message based on what actually happened (keeping your logic)
        if consecutive_failures >= 5:
            raise DownloadError("Server connection unstable. Terabox servers may be overloaded. Try again later.")
        else:
            raise DownloadError(f"Download failed after {max_retries} attempts. Connection issues with Terabox servers.")
    
    # Verify file exists and has content (keeping your verification logic)
    if not os.path.exists(temp_path):
        logger.error(f"❌ Downloaded file does not exist: {temp_path}")
        raise DownloadError("Downloaded file missing")
    
    file_size = os.path.getsize(temp_path)
    if file_size == 0:
        logger.error(f"❌ Downloaded file is empty")
        try:
            os.remove(temp_path)
        except:
            pass
        raise DownloadError("Downloaded file is empty")
    
    # Final speed report
    total_elapsed = time.time() - download_start_time
    avg_speed = file_size / total_elapsed if total_elapsed > 0 else 0
    logger.info(f"✅ SPEED download successful: {temp_path} ({file_size:,} bytes)")
    logger.info(f"🚀 Final average speed: {format_speed(avg_speed)} over {total_elapsed:.1f}s")
    
    # Update meta with actual file size
    meta.size = file_size
    return temp_path, meta
    
