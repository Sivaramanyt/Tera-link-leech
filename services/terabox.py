# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs
from services.downloader import FileMeta

# The API that anasty17's bot actually uses
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
                
                print(f"[TeraboxResolver] Resolving: {share_url}")
                
                # Use wdzone API like anasty17's bot
                download_url, filename, filesize = await self._wdzone_api_method(share_url)
                
                if download_url:
                    print(f"[TeraboxResolver] ✅ SUCCESS via wdzone API")
                    return FileMeta(
                        name=filename or "terabox_file.mp4",
                        size=int(filesize) if filesize else None,
                        url=download_url
                    )
                
                raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                
            except Exception as e:
                await self.close()
                error_msg = str(e).lower()
                if any(x in error_msg for x in ["expired", "invalid", "private"]):
                    raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                else:
                    raise RuntimeError(f"Resolver error: {str(e)}")
    
    async def _wdzone_api_method(self, url: str):
        """Use wdzone API like anasty17's implementation"""
        try:
            client = await self.get_client()
            
            # Clean URL format like your test
            clean_url = url.strip()
            
            print(f"[TeraboxResolver] 🌐 Calling wdzone API: {clean_url}")
            
            # Call wdzone API
            response = await client.get(
                WDZONE_API,
                params={"url": clean_url},
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"[TeraboxResolver] ❌ API returned {response.status_code}")
                return None, None, None
            
            try:
                data = response.json()
                print(f"[TeraboxResolver] 📋 API Response: {data}")
            except json.JSONDecodeError:
                print(f"[TeraboxResolver] ❌ Invalid JSON response")
                return None, None, None
            
            # Check if API succeeded
            status = data.get("✅ Status") or data.get("status")
            if status != "Success":
                print(f"[TeraboxResolver] ❌ API Status: {status}")
                return None, None, None
            
            # Extract file info
            extracted_info = data.get("📜 Extracted Info")
            
            if not extracted_info or extracted_info is None:
                print(f"[TeraboxResolver] ❌ No extracted info - link may be expired/invalid")
                return None, None, None
            
            # Handle different response formats
            if isinstance(extracted_info, list) and extracted_info:
                file_info = extracted_info[0]
            elif isinstance(extracted_info, dict):
                file_info = extracted_info
            else:
                print(f"[TeraboxResolver] ❌ Unexpected extracted_info format: {type(extracted_info)}")
                return None, None, None
            
            # Extract download data
            download_url = (
                file_info.get("🔽 Direct Download Link") or
                file_info.get("download_url") or
                file_info.get("downloadUrl") or 
                file_info.get("url") or
                file_info.get("dlink")
            )
            
            filename = (
                file_info.get("📂 Title") or
                file_info.get("title") or
                file_info.get("name") or
                file_info.get("filename") or
                "terabox_file"
            )
            
            filesize = (
                file_info.get("size") or
                file_info.get("filesize") or
                file_info.get("file_size")
            )
            
            if download_url:
                print(f"[TeraboxResolver] ✅ Extracted: {filename} ({filesize} bytes)")
                return download_url, filename, filesize
            else:
                print(f"[TeraboxResolver] ❌ No download URL in response")
                return None, None, None
                
        except Exception as e:
            print(f"[TeraboxResolver] ❌ wdzone API error: {e}")
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
                    
