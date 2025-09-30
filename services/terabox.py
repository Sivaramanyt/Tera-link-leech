# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from services.downloader import FileMeta

# Optional external helper (safe if absent)
try:
    from terabox_linker import get_direct_link # type: ignore
except Exception:
    get_direct_link = None

# Public API that returns direct links from Terabox shares
API_ENDPOINT = "https://wdzone-terabox-api.vercel.app/api"

# Regex to capture embedded JSON on official terabox share pages
_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)

# Enhanced headers with better browser emulation
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.terabox.com/",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://www.terabox.com/",
    "Origin": "https://www.terabox.com",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

class TeraboxResolver:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()  # Prevent concurrent API calls
    
    async def get_client(self):
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=API_HEADERS,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client
    
    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def resolve(self, share_url: str) -> FileMeta:
        """Main resolve method with proper error handling"""
        async with self._lock:  # Prevent concurrent access
            try:
                # Add small delay to avoid overwhelming APIs
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
                # Try methods sequentially, not concurrently
                url, name, size = await self._via_public_api(share_url)
                if url:
                    return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                
                # Fallback to library method
                if get_direct_link:
                    url, name, size = await self._with_lib(share_url)
                    if url:
                        return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                
                # Fallback to site flows
                url, name, size = await self._site_flows(share_url)
                if url:
                    return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                
                raise RuntimeError("Unable to resolve direct link from all methods")
                
            except Exception as e:
                await self.close()  # Clean up on error
                raise RuntimeError(f"Resolver error: {str(e)}")
    
    async def _via_public_api(self, share_url: str):
        """Public API method with proper retry logic"""
        try:
            client = await self.get_client()
            
            # Single API call with proper timeout
            response = await client.get(
                API_ENDPOINT, 
                params={"url": share_url},
                timeout=15
            )
            
            if response.status_code != 200:
                return None, None, None
            
            js = response.json()
            
            # Handle different API response formats
            items = js.get("📜 Extracted Info") or js.get("data") or []
            if isinstance(items, list) and items:
                item = items[0]
                dlink = item.get("🔽 Direct Download Link") or item.get("url")
                name = item.get("📂 Title") or item.get("name")
                size = item.get("size")
                if dlink:
                    return dlink, name, size
            
            # Flat format fallback
            direct = js.get("direct") or js.get("download") or js.get("url")
            if direct:
                return direct, js.get("name") or js.get("filename"), js.get("size")
                
            return None, None, None
            
        except Exception as e:
            print(f"Public API error: {e}")
            return None, None, None
    
    async def _with_lib(self, share_url: str):
        """Library method wrapper"""
        if not get_direct_link:
            return None, None, None
        
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, get_direct_link, share_url)
            return data.get("url"), data.get("name"), data.get("size")
        except Exception as e:
            print(f"Library method error: {e}")
            return None, None, None
    
    async def _site_flows(self, share_url: str):
        """Site scraping method with proper error handling"""
        try:
            client = await self.get_client()
            
            # Load the page
            response = await client.get(share_url, headers=HTML_HEADERS, timeout=15)
            response.raise_for_status()
            
            final_url = str(response.url)
            html = response.text
            host = urlparse(final_url).netloc.lower()
            q = parse_qs(urlparse(final_url).query)
            surl = (q.get("surl") or q.get("shorturl") or [None])[0]
            pwd = (q.get("pwd") or q.get("password") or [None])[0]
            
            # Try to extract from page data
            match = _PAGE_DATA_RE.search(html)
            if match:
                try:
                    data = json.loads(match.group(1))
                    files = (
                        data.get("shareInfo", {}).get("file_list")
                        or data.get("file_list")
                        or data.get("list")
                        or []
                    )
                    
                    if isinstance(files, list) and files:
                        file_info = files[0]
                        dlink = file_info.get("dlink")
                        name = file_info.get("server_filename") or file_info.get("filename")
                        size = file_info.get("size")
                        
                        if dlink:
                            return dlink.encode("utf-8").decode("unicode_escape"), name, size
                            
                except json.JSONDecodeError as e:
                    print(f"JSON parsing error: {e}")
                    pass
            
            # Try 1024tera API if applicable
            if any(k in host for k in ["1024tera", "1024terabox"]) and surl:
                return await self._try_1024tera_api(client, surl, pwd)
            
            return None, None, None
            
        except Exception as e:
            print(f"Site flows error: {e}")
            return None, None, None
    
    async def _try_1024tera_api(self, client, surl, pwd):
        """1024tera API method"""
        try:
            list_url = f"https://www.1024tera.com/share/list?surl={surl}&page=1&pageSize=50"
            if pwd:
                list_url += f"&pwd={pwd}"
            
            response = await client.get(list_url, headers=API_HEADERS, timeout=15)
            response.raise_for_status()
            
            payload = response.json()
            items = payload.get("list") or payload.get("data") or payload.get("files") or []
            
            if isinstance(items, list) and items:
                item = items[0]
                name = item.get("server_filename") or item.get("filename")
                size = item.get("size")
                
                # Check for existing dlink
                dlink = item.get("dlink") or item.get("url")
                if dlink:
                    return dlink, name, size
                
                # Request transfer
                fs_id = item.get("fs_id") or item.get("fsid") or item.get("id")
                if fs_id:
                    body = {"surl": surl, "fs_id": fs_id}
                    if pwd:
                        body["pwd"] = pwd
                    
                    transfer_response = await client.post(
                        "https://www.1024tera.com/share/transfer",
                        headers=API_HEADERS,
                        json=body,
                        timeout=15
                    )
                    
                    if transfer_response.status_code == 200:
                        transfer_data = transfer_response.json()
                        dlink = (
                            transfer_data.get("dlink")
                            or transfer_data.get("url")
                            or transfer_data.get("data", {}).get("dlink")
                        )
                        if dlink:
                            return dlink, name, size
            
            return None, None, None
            
        except Exception as e:
            print(f"1024tera API error: {e}")
            return None, None, None

# Global resolver instance
_resolver_instance = None

async def get_resolver():
    """Get global resolver instance"""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = TeraboxResolver()
    return _resolver_instance

async def cleanup_resolver():
    """Cleanup global resolver"""
    global _resolver_instance
    if _resolver_instance:
        await _resolver_instance.close()
        _resolver_instance = None
