# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs, unquote
from services.downloader import FileMeta

# Working APIs found in successful implementations
WORKING_APIs = [
    {
        "url": "https://terabox-dl.qtcloud.workers.dev/api/get-info", 
        "format": "qtcloud"
    },
    {
        "url": "https://terabox-downloader.vercel.app/api/download",
        "format": "vercel_new"  
    },
    {
        "url": "https://terabox-api-theta.vercel.app/api",
        "format": "theta"
    },
    {
        "url": "https://terabox-dl.onrender.com/download",
        "format": "render"
    }
]

# Enhanced headers based on successful implementations
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.terabox.com",
    "Referer": "https://www.terabox.com/",
    "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

class TeraboxResolver:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()
    
    async def get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=60.0),
                follow_redirects=True,
                headers=BROWSER_HEADERS,
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
                
                print(f"[TeraboxResolver] Starting resolution for: {share_url}")
                
                # Method 1: Try working APIs sequentially
                for api_config in WORKING_APIs:
                    try:
                        result = await self._try_working_api(api_config, share_url)
                        if result[0]:  # If URL found
                            print(f"[TeraboxResolver] ✅ Success via {api_config['format']}")
                            return FileMeta(
                                name=result[1] or "terabox_file",
                                size=int(result[2]) if result[2] else None,
                                url=result[0]
                            )
                    except Exception as e:
                        print(f"[TeraboxResolver] ❌ {api_config['format']} failed: {e}")
                        continue
                
                # Method 2: Enhanced direct extraction
                result = await self._direct_extraction(share_url)
                if result[0]:
                    print(f"[TeraboxResolver] ✅ Success via direct extraction")
                    return FileMeta(
                        name=result[1] or "terabox_file",
                        size=int(result[2]) if result[2] else None,
                        url=result[0]
                    )
                
                raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                
            except Exception as e:
                await self.close()
                error_msg = str(e)
                if "expired" in error_msg.lower() or "invalid" in error_msg.lower():
                    raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                else:
                    raise RuntimeError(f"Resolver error: {error_msg}")
    
    async def _try_working_api(self, api_config, share_url):
        """Try working API endpoints with proper format handling"""
        try:
            client = await self.get_client()
            
            # Prepare request based on API format
            if api_config["format"] == "qtcloud":
                params = {"url": share_url}
                response = await client.get(api_config["url"], params=params, headers=API_HEADERS, timeout=20)
                
            elif api_config["format"] == "vercel_new":
                data = {"url": share_url}
                response = await client.post(api_config["url"], json=data, headers=API_HEADERS, timeout=20)
                
            elif api_config["format"] == "theta":
                params = {"url": share_url}
                response = await client.get(api_config["url"], params=params, headers=API_HEADERS, timeout=20)
                
            elif api_config["format"] == "render":
                data = {"link": share_url}
                response = await client.post(api_config["url"], json=data, headers=API_HEADERS, timeout=20)
                
            else:
                return None, None, None
            
            if response.status_code != 200:
                return None, None, None
            
            # Parse response
            try:
                js_data = response.json()
            except json.JSONDecodeError:
                return None, None, None
            
            # Extract data based on different response formats
            return self._extract_from_api_response(js_data, api_config["format"])
            
        except Exception as e:
            print(f"[TeraboxResolver] API {api_config['format']} error: {e}")
            return None, None, None
    
    def _extract_from_api_response(self, data, api_format):
        """Extract download info from different API response formats"""
        try:
            # Format 1: qtcloud workers
            if api_format == "qtcloud":
                if data.get("success") and data.get("data"):
                    file_info = data["data"]
                    return (
                        file_info.get("downloadUrl") or file_info.get("url"),
                        file_info.get("fileName") or file_info.get("name"),
                        file_info.get("fileSize") or file_info.get("size")
                    )
            
            # Format 2: vercel new format
            elif api_format == "vercel_new":
                if data.get("success") or data.get("status") == "success":
                    file_data = data.get("data") or data.get("result")
                    if isinstance(file_data, list) and file_data:
                        file_info = file_data[0]
                    else:
                        file_info = file_data or {}
                    
                    return (
                        file_info.get("direct_link") or file_info.get("downloadUrl"),
                        file_info.get("filename") or file_info.get("name"),
                        file_info.get("size") or file_info.get("fileSize")
                    )
            
            # Format 3: theta format
            elif api_format == "theta":
                if data.get("files") and isinstance(data["files"], list):
                    file_info = data["files"][0]
                    return (
                        file_info.get("link") or file_info.get("url"),
                        file_info.get("name") or file_info.get("filename"),
                        file_info.get("size")
                    )
            
            # Format 4: render format
            elif api_format == "render":
                if data.get("download_url"):
                    return (
                        data.get("download_url"),
                        data.get("file_name") or data.get("filename"),
                        data.get("file_size") or data.get("size")
                    )
            
            # Generic extraction
            direct_url = (
                data.get("direct_link") or data.get("downloadUrl") or 
                data.get("download_url") or data.get("url") or 
                data.get("dlink")
            )
            
            if direct_url:
                filename = (
                    data.get("filename") or data.get("fileName") or 
                    data.get("file_name") or data.get("name") or
                    data.get("title")
                )
                filesize = (
                    data.get("size") or data.get("fileSize") or 
                    data.get("file_size")
                )
                return direct_url, filename, filesize
            
            return None, None, None
            
        except Exception as e:
            print(f"[TeraboxResolver] Extraction error for {api_format}: {e}")
            return None, None, None
    
    async def _direct_extraction(self, share_url):
        """Direct extraction from Terabox page"""
        try:
            client = await self.get_client()
            
            # Normalize URL
            if "teraboxurl.com" in share_url:
                share_url = share_url.replace("teraboxurl.com", "www.terabox.com")
            
            # Get the page
            response = await client.get(share_url, headers=BROWSER_HEADERS, timeout=20)
            response.raise_for_status()
            
            html = response.text
            final_url = str(response.url)
            
            # Try multiple extraction patterns
            patterns = [
                r'"dlink":"([^"]+)"',
                r'"downloadUrl":"([^"]+)"', 
                r'"direct_link":"([^"]+)"',
                r'window\.pageData\s*=\s*({[^}]+})',
                r'locals\.mset\(({[^}]+})\)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    if match.startswith('http') and ('terabox' in match or 'teracdn' in match):
                        # Found direct URL
                        try:
                            # Try to decode if it's escaped
                            url = match.encode().decode('unicode_escape')
                        except:
                            url = match
                        
                        return url, "terabox_file", None
                    
                    elif match.startswith('{'):
                        # Found JSON data
                        try:
                            json_data = json.loads(match)
                            url = self._extract_from_json(json_data)
                            if url:
                                return url, "terabox_file", None
                        except:
                            continue
            
            return None, None, None
            
        except Exception as e:
            print(f"[TeraboxResolver] Direct extraction error: {e}")
            return None, None, None
    
    def _extract_from_json(self, data):
        """Extract URL from JSON data"""
        if isinstance(data, dict):
            # Look for download URLs
            for key in ['dlink', 'downloadUrl', 'direct_link', 'url']:
                if key in data and data[key]:
                    url = data[key]
                    if isinstance(url, str) and ('terabox' in url or 'teracdn' in url):
                        return url
            
            # Look nested
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self._extract_from_json(value)
                    if result:
                        return result
        
        elif isinstance(data, list):
            for item in data:
                result = self._extract_from_json(item)
                if result:
                    return result
        
        return None

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
                
