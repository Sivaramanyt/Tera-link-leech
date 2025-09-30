# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs, unquote
from services.downloader import FileMeta

# Updated working APIs (as of September 2025)
RELIABLE_APIs = [
    {
        "url": "https://teradownloader.com/api/download",
        "method": "POST",
        "format": "teradownloader"
    },
    {
        "url": "https://api.terabox-dl.workers.dev/download", 
        "method": "POST",
        "format": "workers"
    },
    {
        "url": "https://terabox-api.onrender.com/api/v1/download",
        "method": "POST", 
        "format": "render_v1"
    }
]

# Fallback direct extraction patterns
EXTRACTION_PATTERNS = [
    r'"dlink":"([^"]+)"',
    r'"downloadUrl":"([^"]+)"',
    r'"direct_link":"([^"]+)"',
    r'window\.pageData\s*=\s*({.*?});',
    r'locals\.mset\(({.*?})\)',
    r'"url":"(https://[^"]*teracdn[^"]*)"'
]

# Enhanced browser headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "sec-ch-ua": '"Not A(Brand";v="99", "Microsoft Edge";v="121", "Chromium";v="121"',
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
                timeout=httpx.Timeout(45.0, read=90.0),
                follow_redirects=True,
                headers=HEADERS,
                limits=httpx.Limits(max_keepalive_connections=3, max_connections=6)
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def resolve(self, share_url: str) -> FileMeta:
        async with self._lock:
            try:
                # Rate limiting
                await asyncio.sleep(random.uniform(2.0, 4.0))
                
                print(f"[TeraboxResolver] 🔍 Resolving: {share_url}")
                
                # Clean and normalize the URL
                clean_url = self._normalize_url(share_url)
                print(f"[TeraboxResolver] 🔗 Normalized URL: {clean_url}")
                
                # Method 1: Try working APIs with proper error handling
                for api_config in RELIABLE_APIs:
                    try:
                        print(f"[TeraboxResolver] 🧪 Trying API: {api_config['format']}")
                        result = await self._try_reliable_api(api_config, clean_url)
                        if result and result[0]:
                            print(f"[TeraboxResolver] ✅ SUCCESS via {api_config['format']}")
                            return FileMeta(
                                name=result[1] or "terabox_file.mp4",
                                size=int(result[2]) if result[2] else None,
                                url=result[0]
                            )
                        else:
                            print(f"[TeraboxResolver] ❌ {api_config['format']} returned empty")
                    except Exception as e:
                        print(f"[TeraboxResolver] ❌ {api_config['format']} failed: {e}")
                        continue
                
                # Method 2: Direct page scraping with multiple attempts
                print(f"[TeraboxResolver] 🕷️ Attempting direct scraping...")
                result = await self._scrape_terabox_page(clean_url)
                if result and result[0]:
                    print(f"[TeraboxResolver] ✅ SUCCESS via direct scraping")
                    return FileMeta(
                        name=result[1] or "terabox_file.mp4",
                        size=int(result[2]) if result[2] else None,
                        url=result[0]
                    )
                
                # Method 3: Try alternative URL formats
                print(f"[TeraboxResolver] 🔄 Trying alternative URL formats...")
                for alt_url in self._generate_alternative_urls(clean_url):
                    try:
                        result = await self._scrape_terabox_page(alt_url)
                        if result and result[0]:
                            print(f"[TeraboxResolver] ✅ SUCCESS via alternative URL: {alt_url}")
                            return FileMeta(
                                name=result[1] or "terabox_file.mp4",
                                size=int(result[2]) if result[2] else None,
                                url=result[0]
                            )
                    except Exception as e:
                        print(f"[TeraboxResolver] ❌ Alternative URL failed: {e}")
                        continue
                
                print(f"[TeraboxResolver] ❌ All methods failed")
                raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                
            except Exception as e:
                await self.close()
                error_msg = str(e).lower()
                if any(x in error_msg for x in ["expired", "invalid", "private", "not found"]):
                    raise RuntimeError("Link expired or invalid. Please get a fresh link from Terabox.")
                else:
                    raise RuntimeError(f"Resolver error: {str(e)}")
    
    def _normalize_url(self, url: str) -> str:
        """Normalize Terabox URLs to standard format"""
        # Handle different domain variations
        replacements = [
            ("teraboxurl.com", "www.terabox.com"),
            ("1024tera.com", "www.terabox.com"),
            ("4funbox.com", "www.terabox.com"),
            ("mirrobox.com", "www.terabox.com"),
            ("nephobox.com", "www.terabox.com"),
            ("terabox.app", "www.terabox.com"),
        ]
        
        clean_url = url.strip()
        for old, new in replacements:
            if old in clean_url:
                clean_url = clean_url.replace(old, new)
        
        # Ensure https
        if not clean_url.startswith(('http://', 'https://')):
            clean_url = 'https://' + clean_url
        
        return clean_url
    
    def _generate_alternative_urls(self, base_url: str) -> list:
        """Generate alternative URL formats"""
        alternatives = []
        
        try:
            parsed = urlparse(base_url)
            
            # Extract surl parameter if present
            if "surl=" in parsed.query:
                surl = parse_qs(parsed.query).get("surl", [None])[0]
                if surl:
                    alternatives.extend([
                        f"https://www.terabox.com/s/{surl}",
                        f"https://www.terabox.com/sharing/link?surl={surl}",
                    ])
            
            # Extract from path
            if "/s/" in parsed.path:
                path_part = parsed.path.split("/s/")[-1]
                alternatives.extend([
                    f"https://www.terabox.com/s/{path_part}",
                    f"https://www.terabox.com/sharing/link?surl={path_part}",
                ])
        except:
            pass
        
        return list(set(alternatives))  # Remove duplicates
    
    async def _try_reliable_api(self, api_config: dict, url: str):
        """Try reliable API endpoints"""
        try:
            client = await self.get_client()
            
            # Prepare request payload
            if api_config["format"] == "teradownloader":
                payload = {"url": url, "format": "json"}
                headers = {**HEADERS, "Content-Type": "application/json"}
                
            elif api_config["format"] == "workers":
                payload = {"link": url}
                headers = {**HEADERS, "Content-Type": "application/json"}
                
            elif api_config["format"] == "render_v1":
                payload = {"terabox_url": url}
                headers = {**HEADERS, "Content-Type": "application/json"}
                
            else:
                return None, None, None
            
            # Make request
            if api_config["method"] == "POST":
                response = await client.post(
                    api_config["url"],
                    json=payload,
                    headers=headers,
                    timeout=30
                )
            else:
                response = await client.get(
                    api_config["url"],
                    params=payload,
                    headers=headers,
                    timeout=30
                )
            
            if response.status_code != 200:
                print(f"[TeraboxResolver] API {api_config['format']} returned {response.status_code}")
                return None, None, None
            
            # Parse response
            try:
                data = response.json()
            except:
                print(f"[TeraboxResolver] API {api_config['format']} returned non-JSON")
                return None, None, None
            
            # Extract download info based on API format
            return self._extract_api_data(data, api_config["format"])
            
        except Exception as e:
            print(f"[TeraboxResolver] API {api_config['format']} exception: {e}")
            return None, None, None
    
    def _extract_api_data(self, data: dict, api_format: str):
        """Extract download information from API responses"""
        try:
            if api_format == "teradownloader":
                if data.get("success") and data.get("data"):
                    file_data = data["data"]
                    return (
                        file_data.get("download_url"),
                        file_data.get("filename"),
                        file_data.get("filesize")
                    )
            
            elif api_format == "workers":
                if data.get("status") == "success" and data.get("result"):
                    file_data = data["result"]
                    return (
                        file_data.get("direct_link"),
                        file_data.get("name"),
                        file_data.get("size")
                    )
            
            elif api_format == "render_v1":
                if data.get("success") and data.get("download_link"):
                    return (
                        data.get("download_link"),
                        data.get("file_name"),
                        data.get("file_size")
                    )
            
            # Generic extraction
            download_url = (
                data.get("download_url") or data.get("direct_link") or
                data.get("downloadUrl") or data.get("url") or data.get("link")
            )
            
            if download_url:
                filename = (
                    data.get("filename") or data.get("file_name") or
                    data.get("name") or data.get("title")
                )
                filesize = (
                    data.get("filesize") or data.get("file_size") or
                    data.get("size")
                )
                return download_url, filename, filesize
            
            return None, None, None
            
        except Exception as e:
            print(f"[TeraboxResolver] Data extraction error for {api_format}: {e}")
            return None, None, None
    
    async def _scrape_terabox_page(self, url: str):
        """Scrape Terabox page directly"""
        try:
            client = await self.get_client()
            
            # Get page with proper headers
            response = await client.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            
            html = response.text
            print(f"[TeraboxResolver] 📄 Page loaded, size: {len(html)} chars")
            
            # Try extraction patterns
            for pattern in EXTRACTION_PATTERNS:
                matches = re.findall(pattern, html, re.DOTALL)
                for match in matches:
                    if match.startswith('http') and any(domain in match for domain in ['teracdn', 'terabox']):
                        # Found direct URL
                        try:
                            clean_url = match.encode().decode('unicode_escape')
                            print(f"[TeraboxResolver] 🎯 Found direct URL via pattern: {pattern[:20]}...")
                            return clean_url, "terabox_file", None
                        except:
                            return match, "terabox_file", None
                    
                    elif match.startswith('{'):
                        # Found JSON data
                        try:
                            json_data = json.loads(match)
                            direct_url = self._extract_from_json_data(json_data)
                            if direct_url:
                                print(f"[TeraboxResolver] 🎯 Found URL in JSON data")
                                return direct_url, "terabox_file", None
                        except:
                            continue
            
            return None, None, None
            
        except Exception as e:
            print(f"[TeraboxResolver] Scraping error: {e}")
            return None, None, None
    
    def _extract_from_json_data(self, data):
        """Extract download URL from JSON data"""
        if isinstance(data, dict):
            # Look for download URLs
            url_keys = ['dlink', 'downloadUrl', 'direct_link', 'url', 'download_url']
            for key in url_keys:
                if key in data and data[key]:
                    url = data[key]
                    if isinstance(url, str) and ('teracdn' in url or 'terabox' in url):
                        return url
            
            # Recursive search
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self._extract_from_json_data(value)
                    if result:
                        return result
        
        elif isinstance(data, list):
            for item in data:
                result = self._extract_from_json_data(item)
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
