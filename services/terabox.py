# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
import logging
import gzip
import io
from urllib.parse import urlparse, parse_qs
from services.downloader import FileMeta

# Try to import brotli
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False
    print("⚠️ WARNING: brotli not installed. Brotli decompression will not work.")

logger = logging.getLogger(__name__)

# The API that works
WDZONE_API = "https://wdzone-terabox-api.vercel.app/api"

class TeraboxResolver:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()
    
    async def get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",  # Accept compressed response
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Referer": "https://www.terabox.com/",
                },
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def resolve(self, share_url: str) -> FileMeta:
        async with self._lock:
            try:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                
                logger.info(f"🌐 TeraboxResolver: Processing {share_url}")
                
                # Use wdzone API
                download_url, filename, filesize = await self._wdzone_api_method(share_url)
                
                if download_url:
                    logger.info(f"✅ TeraboxResolver: SUCCESS - {filename} ({filesize} bytes)")
                    return FileMeta(
                        name=filename or "terabox_file.mp4",
                        size=int(filesize) if filesize else None,
                        url=download_url
                    )
                
                logger.error(f"❌ TeraboxResolver: No download URL found")
                raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                
            except Exception as e:
                await self.close()
                error_msg = str(e).lower()
                logger.error(f"❌ TeraboxResolver: Error - {e}")
                if any(x in error_msg for x in ["expired", "invalid", "private"]):
                    raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                else:
                    raise RuntimeError(f"Resolver error: {str(e)}")
    
    def _parse_size_string(self, size_str):
        """Parse size strings like '6.34 MB' into bytes"""
        if not size_str or not isinstance(size_str, str):
            return None
        
        try:
            size_str = size_str.strip().upper()
            
            # Extract number and unit
            import re
            match = re.match(r'([0-9.]+)\s*([KMGT]?B)', size_str)
            if not match:
                return None
            
            number = float(match.group(1))
            unit = match.group(2)
            
            # Convert to bytes
            multipliers = {
                'B': 1,
                'KB': 1024,
                'MB': 1024**2,
                'GB': 1024**3,
                'TB': 1024**4
            }
            
            return int(number * multipliers.get(unit, 1))
            
        except Exception as e:
            logger.warning(f"⚠️ Size parsing error: {e}")
            return None
    
    def _decode_response_content(self, response):
        """Safely decode response content handling different encodings including Brotli"""
        try:
            # Check content encoding
            content_encoding = response.headers.get('content-encoding', '').lower()
            logger.info(f"📦 Content-Encoding: {content_encoding}")
            logger.info(f"📦 Content-Type: {response.headers.get('content-type', 'unknown')}")
            
            raw_content = response.content
            logger.info(f"📦 Raw content length: {len(raw_content)} bytes")
            logger.info(f"📦 First 20 bytes: {raw_content[:20]}")
            
            # Handle Brotli compression (this is what we need!)
            if content_encoding == 'br':
                logger.info(f"🗜️ Decompressing Brotli content...")
                if HAS_BROTLI:
                    try:
                        decompressed = brotli.decompress(raw_content)
                        logger.info(f"✅ Brotli decompressed: {len(decompressed)} bytes")
                        decoded = decompressed.decode('utf-8')
                        logger.info(f"✅ Brotli->UTF-8 decoded: {len(decoded)} chars")
                        return decoded
                    except Exception as e:
                        logger.error(f"❌ Brotli decompression failed: {e}")
                else:
                    logger.error(f"❌ Brotli compression detected but brotli package not installed!")
                    return None
            
            # Handle Gzip compression
            elif content_encoding == 'gzip' or raw_content.startswith(b'\x1f\x8b'):
                logger.info(f"🗜️ Decompressing gzip content...")
                try:
                    decompressed = gzip.decompress(raw_content)
                    logger.info(f"✅ Gzip decompressed: {len(decompressed)} bytes")
                    return decompressed.decode('utf-8')
                except Exception as e:
                    logger.warning(f"⚠️ Gzip decompression failed: {e}")
            
            # Try direct text decoding with different encodings
            for encoding in ['utf-8', 'latin-1', 'ascii']:
                try:
                    decoded = raw_content.decode(encoding)
                    logger.info(f"✅ Decoded with {encoding}: {len(decoded)} chars")
                    # Only return if it looks like valid JSON
                    if decoded.strip().startswith('{'):
                        return decoded
                    else:
                        logger.warning(f"⚠️ {encoding} decoded but doesn't look like JSON")
                        continue
                except UnicodeDecodeError as e:
                    logger.warning(f"⚠️ {encoding} decoding failed: {e}")
                    continue
            
            # Try using httpx's built-in text property as last resort
            try:
                text = response.text
                logger.info(f"✅ Using response.text: {len(text)} chars")
                if text.strip().startswith('{'):
                    return text
                else:
                    logger.warning(f"⚠️ response.text doesn't look like JSON")
            except Exception as e:
                logger.warning(f"⚠️ response.text failed: {e}")
            
            # Last resort failed
            logger.error(f"❌ All decoding methods failed")
            return None
            
        except Exception as e:
            logger.error(f"❌ Content decoding error: {e}")
            return None
    
    async def _wdzone_api_method(self, url: str):
        """Use wdzone API with proper Brotli response handling"""
        try:
            client = await self.get_client()
            
            clean_url = url.strip()
            logger.info(f"🌐 Calling wdzone API with: {clean_url}")
            
            # Call wdzone API
            response = await client.get(
                WDZONE_API,
                params={"url": clean_url},
                timeout=30
            )
            
            logger.info(f"📡 API Response Status: {response.status_code}")
            logger.info(f"📡 Response Headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                logger.error(f"❌ API returned {response.status_code}")
                return None, None, None
            
            # Decode the response content properly (including Brotli!)
            text_content = self._decode_response_content(response)
            if not text_content:
                logger.error(f"❌ Could not decode response content")
                return None, None, None
            
            logger.info(f"📄 Decoded content length: {len(text_content)} chars")
            logger.info(f"📄 First 200 chars: {text_content[:200]}")
            
            # Parse JSON
            try:
                data = json.loads(text_content)
                logger.info(f"📋 JSON parsed successfully, keys: {list(data.keys())}")
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parsing failed: {e}")
                logger.error(f"❌ Content that failed to parse: {text_content[:500]}")
                return None, None, None
            
            # Check API status
            status = data.get("✅ Status") or data.get("status")
            logger.info(f"📊 API Status: {status}")
            
            if status != "Success":
                logger.error(f"❌ API Status not Success: {status}")
                return None, None, None
            
            # Extract file info - FIXED PARSING LOGIC
            extracted_info = data.get("📜 Extracted Info")
            logger.info(f"📝 Extracted Info Type: {type(extracted_info)}")
            
            if not extracted_info:
                logger.error(f"❌ No extracted info in response")
                return None, None, None
            
            # Handle the actual format from your screenshot
            if isinstance(extracted_info, list) and len(extracted_info) > 0:
                file_info = extracted_info[0]  # Get first file
                logger.info(f"📁 Processing file from list, keys: {list(file_info.keys())}")
            elif isinstance(extracted_info, dict):
                file_info = extracted_info
                logger.info(f"📁 Processing dict file, keys: {list(file_info.keys())}")
            else:
                logger.error(f"❌ Unexpected extracted_info format: {type(extracted_info)}")
                return None, None, None
            
            # Extract data using the EXACT keys from your screenshot
            download_url = file_info.get("🔽 Direct Download Link")
            filename = file_info.get("📂 Title")
            file_size_str = file_info.get("📏 Size") or file_info.get("size")  # Try both possible keys
            
            logger.info(f"📄 Raw extracted - URL exists: {download_url is not None}")
            logger.info(f"📄 Raw extracted - Name: {filename}")
            logger.info(f"📄 Raw extracted - Size string: {file_size_str}")
            
            # Parse size from string to bytes
            filesize_bytes = self._parse_size_string(file_size_str)
            
            logger.info(f"📄 Final - URL: {download_url is not None}")
            logger.info(f"📄 Final - Name: {filename}")  
            logger.info(f"📄 Final - Size bytes: {filesize_bytes}")
            
            if download_url and filename:
                return download_url, filename, filesize_bytes
            else:
                logger.error(f"❌ Missing required fields - URL: {download_url is not None}, Name: {filename is not None}")
                return None, None, None
                
        except Exception as e:
            logger.error(f"❌ wdzone API exception: {e}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return None, None, None

# Global resolver instance
_resolver_instance = None

async def get_resolver():
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = TeraboxResolver()
    return _resolver_instance

async def cleanup_resolver():
    global _resolver_instance
    if _resolver_instance:
        await _resolver_instance.close()
        _resolver_instance = None
            
