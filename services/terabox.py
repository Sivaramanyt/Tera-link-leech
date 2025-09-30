# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs, unquote
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Multiple API endpoints for better reliability
API_ENDPOINTS = [
    "https://wdzone-terabox-api.vercel.app/api",
    "https://terabox-dl.qtcloud.workers.dev/api/get-info",  # Alternative API
    "https://terabox-downloader.vercel.app/api/download"     # Another alternative
]

# Enhanced regex patterns
_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL | re.MULTILINE)
_YUNDATA_RE = re.compile(r"window\.yunData\s*=\s*(\{.*?\});", re.DOTALL | re.MULTILINE)
_SETDATA_RE = re.compile(r"locals\.mset\((\{.*?\})\)", re.DOTALL)

# Enhanced headers
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
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://www.terabox.com/",
}

class TeraboxResolver:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()
    
    async def get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=HTML_HEADERS,
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
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
                print(f"[resolver] Attempting to resolve: {share_url}")
                
                # Method 1: Try multiple public APIs
                for api_url in API_ENDPOINTS:
                    try:
                        url, name, size = await self._try_api(api_url, share_url)
                        if url:
                            print(f"[resolver] Success via API: {api_url}")
                            return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                    except Exception as e:
                        print(f"[resolver] API {api_url} failed: {e}")
                        continue
                
                # Method 2: Enhanced site scraping
                url, name, size = await self._enhanced_site_scraping(share_url)
                if url:
                    print(f"[resolver] Success via site scraping")
                    return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                
                # Method 3: Try different link formats
                url, name, size = await self._try_link_variations(share_url)
                if url:
                    print(f"[resolver] Success via link variations")
                    return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
                
                raise RuntimeError("Link may be expired, private, or in unsupported format")
                
            except Exception as e:
                await self.close()
                raise RuntimeError(f"Unable to resolve direct link from all methods: {str(e)}")
    
    async def _try_api(self, api_url: str, share_url: str):
        try:
            client = await self.get_client()
            
            # Different APIs have different parameter formats
            params = {"url": share_url}
            if "qtcloud" in api_url:
                params = {"url": share_url, "type": "download"}
            elif "vercel" in api_url and "download" in api_url:
                params = {"link": share_url}
            
            response = await client.get(api_url, params=params, headers=API_HEADERS, timeout=15)
            
            if response.status_code != 200:
                return None, None, None
            
            try:
                js = response.json()
            except json.JSONDecodeError:
                return None, None, None
            
            # Handle different API response formats
            # Format 1: wdzone-terabox-api
            items = js.get("📜 Extracted Info") or js.get("data") or []
            if isinstance(items, list) and items:
                item = items[0]
                dlink = item.get("🔽 Direct Download Link") or item.get("url")
                name = item.get("📂 Title") or item.get("name")
                size = item.get("size")
                if dlink:
                    return dlink, name, size
            
            # Format 2: Standard format
            dlink = js.get("direct") or js.get("download") or js.get("url") or js.get("downloadUrl")
            if dlink:
                name = js.get("name") or js.get("filename") or js.get("title")
                size = js.get("size") or js.get("fileSize")
                return dlink, name, size
            
            # Format 3: Nested data
            if "data" in js and isinstance(js["data"], dict):
                data = js["data"]
                dlink = data.get("url") or data.get("downloadUrl") or data.get("direct")
                if dlink:
                    name = data.get("name") or data.get("filename")
                    size = data.get("size")
                    return dlink, name, size
            
            return None, None, None
            
        except Exception as e:
            print(f"[resolver] API error for {api_url}: {e}")
            return None, None, None
    
    async def _enhanced_site_scraping(self, share_url: str):
        try:
            client = await self.get_client()
            
            # Handle different URL formats
            normalized_url = share_url.replace("teraboxurl.com", "www.terabox.com")
            normalized_url = normalized_url.replace("1024tera.com", "www.terabox.com") 
            
            response = await client.get(normalized_url, headers=HTML_HEADERS, timeout=15)
            response.raise_for_status()
            
            html = response.text
            final_url = str(response.url)
            
            # Try multiple regex patterns
            for pattern in [_PAGE_DATA_RE, _YUNDATA_RE, _SETDATA_RE]:
                match = pattern.search(html)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        result = self._extract_from_data(data)
                        if result[0]:  # If URL found
                            return result
                    except json.JSONDecodeError:
                        continue
            
            # Try direct extraction from HTML
            return await self._extract_from_html(html, final_url)
            
        except Exception as e:
            print(f"[resolver] Site scraping error: {e}")
            return None, None, None
    
    def _extract_from_data(self, data):
        """Extract file info from JSON data"""
        try:
            # Try different data structures
            files = (
                data.get("shareInfo", {}).get("file_list") or
                data.get("file_list") or
                data.get("list") or
                data.get("files") or
                []
            )
            
            if isinstance(files, list) and files:
                file_info = files[0]
                dlink = file_info.get("dlink")
                name = file_info.get("server_filename") or file_info.get("filename")
                size = file_info.get("size")
                
                if dlink:
                    # Decode any escaped characters
                    try:
                        dlink = dlink.encode("utf-8").decode("unicode_escape")
                    except:
                        pass
                    return dlink, name, size
            
            return None, None, None
            
        except Exception as e:
            print(f"[resolver] Data extraction error: {e}")
            return None, None, None
    
    async def _extract_from_html(self, html: str, url: str):
        """Extract download info directly from HTML"""
        try:
            # Look for direct download links in HTML
            patterns = [
                r'"dlink":"([^"]+)"',
                r'"url":"(https://[^"]*\.terabox\.com[^"]*)"',
                r'"downloadUrl":"([^"]+)"',
                r'data-url="([^"]+)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    dlink = match.group(1)
                    # Basic URL validation
                    if "terabox" in dlink or "teracdn" in dlink:
                        return dlink, "file", None
            
            return None, None, None
            
        except Exception as e:
            print(f"[resolver] HTML extraction error: {e}")
            return None, None, None
    
    async def _try_link_variations(self, share_url: str):
        """Try different variations of the link"""
        try:
            variations = [
                share_url.replace("teraboxurl.com", "www.terabox.com"),
                share_url.replace("1024tera.com", "www.terabox.com"),
                share_url.replace("dm.terabox.com", "www.terabox.com"),
                share_url.replace("/s/", "/sharing/link?surl=")
            ]
            
            for variation in variations:
                if variation != share_url:  # Don't retry the same URL
                    try:
                        result = await self._enhanced_site_scraping(variation)
                        if result[0]:
                            return result
                    except:
                        continue
            
            return None, None, None
            
        except Exception as e:
            print(f"[resolver] Link variations error: {e}")
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
                        
