# Enhanced services/downloader.py - ULTRA-EXTREME VERSION

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

async def fetch_to_temp(
    meta: FileMeta,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    max_retries: int = 25,  # EXTREME: 25 attempts
    base_chunk_size: int = None
) -> tuple[str, FileMeta]:
    """
    ULTRA-EXTREME downloader for maximally unstable Terabox servers
    """
    logger.info(f"🚀 Starting ULTRA-EXTREME download: {meta.name} ({meta.size} bytes)")
    
    # Create temp file
    fd, temp_path = tempfile.mkstemp(
        prefix="terabox_",
        suffix=f"_{meta.name}",
        dir=None
    )
    os.close(fd)
    
    downloaded = 0
    retry_count = 0
    download_start_time = time.time()
    successful_chunks = 0
    
    while retry_count < max_retries:
        try:
            # ULTRA-EXTREME: Even smaller chunks on more retries
            if retry_count < 5:
                chunk_size = 32768   # 32KB - very small
            elif retry_count < 10:
                chunk_size = 16384   # 16KB - extremely small
            elif retry_count < 15:
                chunk_size = 8192    # 8KB - ultra small
            else:
                chunk_size = 4096    # 4KB - minimal chunks
            
            logger.info(f"🚀 ULTRA-EXTREME attempt #{retry_count + 1}/{max_retries} - Chunk: {chunk_size//1024 if chunk_size >= 1024 else chunk_size}{'KB' if chunk_size >= 1024 else 'B'}")
            
            # ULTRA-EXTREME HTTP settings - fastest possible failure
            timeout = httpx.Timeout(
                timeout=20.0,      # Even faster total timeout
                connect=3.0,       # Ultra-fast connection
                read=8.0,          # Ultra-fast read
                write=3.0,         # Ultra-fast write
                pool=3.0           # Ultra-fast pool
            )
            
            # Rotating user agents for each attempt
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            ]
            
            headers = {
                "User-Agent": user_agents[retry_count % len(user_agents)],
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "identity",  # No compression for speed
                "Connection": "close",          # Force fresh connection
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "DNT": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site"
            }
            
            # Add resume header if we have partial data
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"
                logger.info(f"📊 RESUMING from byte {downloaded:,}")
            
            # ULTRA-EXTREME: Fresh client every time with no connection reuse
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_keepalive_connections=0,  # No keepalive
                    max_connections=1,            # Single connection
                    keepalive_expiry=0            # No reuse
                ),
                headers=headers,
                http2=False  # Force HTTP/1.1 for better compatibility
            ) as client:
                
                logger.info(f"🌐 Connecting (attempt {retry_count + 1})...")
                
                # Start streaming request
                async with client.stream("GET", meta.url) as response:
                    logger.info(f"📡 Response: {response.status_code}")
                    
                    # Handle status codes
                    if response.status_code not in [200, 206]:
                        if response.status_code in [404, 403, 410]:
                            raise DownloadError(f"File not accessible (HTTP {response.status_code})")
                        else:
                            logger.warning(f"⚠️ Status {response.status_code}, will retry...")
                            retry_count += 1
                            await asyncio.sleep(0.2)  # Very brief delay
                            continue
                    
                    # Get content info
                    content_length = response.headers.get("content-length")
                    if content_length:
                        if response.status_code == 206:  # Partial content
                            remaining_size = int(content_length)
                            expected_total = downloaded + remaining_size
                        else:  # Full content
                            expected_total = int(content_length)
                            if not meta.size:
                                meta.size = expected_total
                    else:
                        expected_total = meta.size or 0
                    
                    logger.info(f"📏 Target: {expected_total:,} bytes total, from: {downloaded:,}")
                    
                    # Open file for writing
                    mode = "ab" if downloaded > 0 else "wb"
                    bytes_this_attempt = 0
                    last_data_time = time.time()
                    stall_timeout = 3.0  # 3 second stall timeout (reduced)
                    
                    try:
                        with open(temp_path, mode) as f:
                            logger.info(f"📝 Writing (attempt {retry_count + 1})...")
                            
                            chunk_count = 0
                            async for chunk in response.aiter_bytes(chunk_size):
                                current_time = time.time()
                                
                                if not chunk:
                                    continue
                                
                                f.write(chunk)
                                f.flush()  # Force write to disk
                                downloaded += len(chunk)
                                bytes_this_attempt += len(chunk)
                                chunk_count += 1
                                successful_chunks += 1
                                last_data_time = current_time
                                
                                # Progress reporting every 256KB or every 64 chunks
                                if downloaded % (256 * 1024) == 0 or chunk_count % 64 == 0:
                                    if on_progress:
                                        try:
                                            on_progress(downloaded, expected_total)
                                        except Exception:
                                            pass
                                
                                # Check for stalls
                                if current_time - last_data_time > stall_timeout:
                                    logger.warning(f"⚠️ Stalled for {stall_timeout}s, breaking...")
                                    break
                                
                                # Speed logging every 1MB
                                if bytes_this_attempt > 0 and bytes_this_attempt % (1024 * 1024) == 0:
                                    attempt_elapsed = current_time - (download_start_time + (retry_count * 0.5))
                                    if attempt_elapsed > 0:
                                        speed = bytes_this_attempt / attempt_elapsed
                                        logger.info(f"🚀 Speed: {format_speed(speed)}, Progress: {downloaded:,}/{expected_total:,}")
                            
                            # Check completion
                            if expected_total and downloaded >= expected_total:
                                total_elapsed = time.time() - download_start_time
                                avg_speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                                logger.info(f"✅ ULTRA-EXTREME download SUCCESS: {downloaded:,} bytes in {total_elapsed:.1f}s")
                                logger.info(f"🚀 Final speed: {format_speed(avg_speed)} ({successful_chunks} successful chunks)")
                                break
                            elif bytes_this_attempt > 0:
                                # Made progress, quick retry
                                logger.info(f"📊 Progress: {downloaded:,}/{expected_total:,} bytes ({(downloaded/expected_total)*100:.1f}%)")
                                retry_count += 1
                                await asyncio.sleep(0.1)  # Minimal delay
                                continue
                            else:
                                # No progress made
                                logger.warning(f"⚠️ No data on attempt {retry_count + 1}")
                                retry_count += 1
                                await asyncio.sleep(0.3)
                                continue
                    
                    except Exception as write_error:
                        logger.warning(f"⚠️ Write error: {write_error}")
                        retry_count += 1
                        await asyncio.sleep(0.2)
                        continue
                        
        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            retry_count += 1
            logger.warning(f"⏰ Timeout #{retry_count}: {e}")
            
            # ULTRA-FAST retry for timeouts
            await asyncio.sleep(0.05)  # 50ms delay
            continue
                
        except (httpx.HTTPError, httpx.RemoteProtocolError) as e:
            retry_count += 1
            error_msg = str(e).lower()
            
            if "peer closed connection" in error_msg:
                logger.info(f"🔄 Server drop #{retry_count} - INSTANT retry")
                await asyncio.sleep(0.02)  # 20ms delay
                continue
            else:
                logger.warning(f"🌐 HTTP error #{retry_count}: {e}")
                await asyncio.sleep(0.1)
                continue
                
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Error #{retry_count}: {e}")
            await asyncio.sleep(0.5)
            continue
    
    # Final result check
    if retry_count >= max_retries:
        logger.error(f"❌ ULTRA-EXTREME download failed after {max_retries} attempts")
        logger.info(f"📊 Achieved {successful_chunks} successful chunks, {downloaded:,} bytes partial progress")
        
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        
        raise DownloadError(f"Download failed after {max_retries} attempts - Terabox servers extremely unstable. Try a different link or wait for servers to stabilize.")
    
    # Verify file
    if not os.path.exists(temp_path):
        raise DownloadError("Downloaded file missing")
    
    file_size = os.path.getsize(temp_path)
    if file_size == 0:
        try:
            os.remove(temp_path)
        except:
            pass
        raise DownloadError("Downloaded file is empty")
    
    # Success
    total_elapsed = time.time() - download_start_time
    avg_speed = file_size / total_elapsed if total_elapsed > 0 else 0
    logger.info(f"✅ ULTRA-EXTREME SUCCESS: {temp_path} ({file_size:,} bytes)")
    logger.info(f"🚀 Final stats: {format_speed(avg_speed)}, {retry_count} attempts, {successful_chunks} chunks")
    
    meta.size = file_size
    return temp_path, meta

def format_speed(bytes_per_sec: float) -> str:
    """Format speed to human readable string"""
    if bytes_per_sec == 0:
        return "0 B/s"
    
    for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
        if bytes_per_sec < 1024.0:
            return f"{bytes_per_sec:.1f} {unit}"
        bytes_per_sec /= 1024.0
    return f"{bytes_per_sec:.1f} TB/s"
                    
