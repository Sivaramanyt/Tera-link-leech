# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs, unquote
from services.downloader import FileMeta

# Based on anasty17's working implementation
class TeraboxResolver:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()
    
    async def get_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=60.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                },
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def resolve(self, share_url: str) -> FileMeta:
        """Main resolve method based on anasty17's implementation"""
        async with self._lock:
            try:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                
                print(f"[TeraboxResolver] Resolving: {share_url}")
                
                # Extract direct download link using anasty17's method
                download_url, filename, filesize = await self._terabox_extractor(share_url)
                
                if download_url:
                    print(f"[TeraboxResolver] ✅ SUCCESS: {filename}")
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
    
    async def _terabox_extractor(self, url: str):
        """
        Based on anasty17's direct_link_generator.py terabox implementation
        This is the exact method used in the working mirror-leech-telegram-bot
        """
        try:
            client = await self.get_client()
            
            # Step 1: Handle different URL formats
            if "teraboxurl.com" in url:
                url = url.replace("teraboxurl.com", "www.terabox.com")
            elif "1024tera.com" in url:
                url = url.replace("1024tera.com", "www.terabox.com")
            elif "4funbox.com" in url:
                url = url.replace("4funbox.com", "www.terabox.com")
            elif "mirrobox.com" in url:
                url = url.replace("mirrobox.com", "www.terabox.com")
            elif "nephobox.com" in url:
                url = url.replace("nephobox.com", "www.terabox.com")
            
            print(f"[TeraboxResolver] Normalized URL: {url}")
            
            # Step 2: Get the main page
            response = await client.get(url, timeout=30)
            response.raise_for_status()
            
            if "TeraBox" not in response.text:
                raise Exception("Invalid TeraBox URL")
            
            # Step 3: Extract surl from URL or response
            parsed_url = urlparse(response.url)
            query_params = parse_qs(parsed_url.query)
            
            if "surl" in query_params:
                surl = query_params["surl"][0]
            else:
                # Extract from path
                path_parts = parsed_url.path.strip("/").split("/")
                if "s" in path_parts:
                    surl_index = path_parts.index("s") + 1
                    if surl_index < len(path_parts):
                        surl = path_parts[surl_index]
                    else:
                        raise Exception("Could not extract surl from URL")
                else:
                    raise Exception("Invalid TeraBox share URL format")
            
            print(f"[TeraboxResolver] Extracted surl: {surl}")
            
            # Step 4: Get file list using anasty17's method
            list_url = "https://www.terabox.com/share/list"
            list_params = {
                "surl": surl,
                "root": "1",
                "fid": "",
                "desc": "1",
                "sort": "name",
                "page": "1",
                "num": "20",
                "order": "time",
                "site_referer": response.url,
                "shorturl": surl,
                "app_id": "250528",
            }
            
            # Add required headers for API call
            api_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://www.terabox.com",
                "Referer": str(response.url),
                "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors", 
                "Sec-Fetch-Site": "same-origin",
            }
            
            # Make API request to get file list
            list_response = await client.get(list_url, params=list_params, headers=api_headers, timeout=30)
            
            if list_response.status_code != 200:
                print(f"[TeraboxResolver] List API returned: {list_response.status_code}")
                raise Exception(f"Failed to get file list: {list_response.status_code}")
            
            try:
                list_data = list_response.json()
            except json.JSONDecodeError:
                raise Exception("Invalid JSON response from file list API")
            
            print(f"[TeraboxResolver] List API response keys: {list(list_data.keys())}")
            
            # Step 5: Extract file information
            if list_data.get("errno") != 0:
                raise Exception(f"API Error: {list_data.get('errmsg', 'Unknown error')}")
            
            file_list = list_data.get("list", [])
            if not file_list:
                raise Exception("No files found in share")
            
            # Get first file (anasty17's implementation takes first file)
            first_file = file_list[0]
            
            filename = first_file.get("server_filename", "terabox_file")
            filesize = first_file.get("size")
            fs_id = first_file.get("fs_id")
            
            if not fs_id:
                raise Exception("Could not get file ID")
            
            print(f"[TeraboxResolver] File info - Name: {filename}, Size: {filesize}, ID: {fs_id}")
            
            # Step 6: Get download link using anasty17's method
            download_url = await self._get_download_link(client, surl, fs_id, str(response.url))
            
            if download_url:
                return download_url, filename, filesize
            else:
                raise Exception("Could not extract download URL")
                
        except Exception as e:
            print(f"[TeraboxResolver] Extraction error: {e}")
            return None, None, None
    
    async def _get_download_link(self, client, surl, fs_id, referer_url):
        """Get direct download link using anasty17's method"""
        try:
            # This is anasty17's working method for getting download links
            download_api_url = "https://www.terabox.com/share/download"
            
            download_params = {
                "surl": surl,
                "fid": fs_id,
                "type": "nolimit",
                "sign": "",
                "timestamp": "",
                "app_id": "250528",
            }
            
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://www.terabox.com",
                "Referer": referer_url,
                "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                "sec-ch-ua-mobile": "?0", 
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
            
            download_response = await client.get(download_api_url, params=download_params, headers=download_headers, timeout=30)
            
            if download_response.status_code != 200:
                print(f"[TeraboxResolver] Download API returned: {download_response.status_code}")
                return None
            
            try:
                download_data = download_response.json()
            except json.JSONDecodeError:
                print(f"[TeraboxResolver] Invalid JSON from download API")
                return None
            
            print(f"[TeraboxResolver] Download API response keys: {list(download_data.keys())}")
            
            if download_data.get("errno") != 0:
                print(f"[TeraboxResolver] Download API error: {download_data.get('errmsg')}")
                return None
            
            # Extract download URL
            dlink = download_data.get("dlink")
            if dlink:
                # Decode any escaped characters
                try:
                    dlink = dlink.encode().decode('unicode_escape')
                except:
                    pass
                
                print(f"[TeraboxResolver] ✅ Got download URL: {dlink[:100]}...")
                return dlink
            
            print(f"[TeraboxResolver] No dlink in response")
            return None
            
        except Exception as e:
            print(f"[TeraboxResolver] Download link error: {e}")
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
            
