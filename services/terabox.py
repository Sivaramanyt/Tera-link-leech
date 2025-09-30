# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
import logging
from urllib.parse import urlparse, parse_qs
from services.downloader import FileMeta

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
                    "Accept-Encoding": "gzip, deflate, br",
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
    
    async def _wdzone_api_method(self, url: str):
        """Use wdzone API with correct parsing for the actual response format"""
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
            
            if response.status_code != 200:
                logger.error(f"❌ API returned {response.status_code}")
                return None, None, None
            
            try:
                data = response.json()
                logger.info(f"📋 API Response Keys: {list(data.keys())}")
            except json.JSONDecodeError:
                logger.error(f"❌ Invalid JSON response")
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
                
