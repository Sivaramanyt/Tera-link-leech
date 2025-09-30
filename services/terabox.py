# services/terabox.py

import asyncio
import json
import re
import httpx
import random
import time
from urllib.parse import urlparse, parse_qs
from tenacity import retry, stop_after_attempt, wait_fixed
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
    
    @retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
    async def resolve(self, share_url: str) -> FileMeta:
        # Add random delay to avoid rate limiting
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # 0) Try the public API first
        url, name, size = await self._via_public_api(share_url)
        if not url:
            # 1) Try optional library if present
            url, name, size = await self._with_lib(share_url)
        if not url:
            # 2) Fallback to site flows (official + 1024tera API)
            url, name, size = await self._site_flows(share_url)
        
        if not url:
            raise RuntimeError("Unable to resolve direct link")
        
        return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)
    
    async def _via_public_api(self, share_url: str):
        try:
            # Add timeout and better error handling
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=API_HEADERS,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            ) as client:
                # Add retries for API calls
                for attempt in range(3):
                    try:
                        r = await client.get(API_ENDPOINT, params={"url": share_url})
                        if r.status_code != 200:
                            if attempt < 2:  # Retry on failure
                                await asyncio.sleep(random.uniform(1, 3))
                                continue
                            return None, None, None
                        
                        js = r.json()
                        
                        # API returns an array under a fancy key, handle common shapes
                        items = js.get("📜 Extracted Info") or js.get("data") or []
                        if isinstance(items, list) and items:
                            it = items[0]
                            dlink = it.get("🔽 Direct Download Link") or it.get("url")
                            name = it.get("📂 Title") or it.get("name")
                            if dlink:
                                return dlink, name, it.get("size")
                        
                        # Some deployments might return flat keys
                        direct = js.get("direct") or js.get("download") or js.get("url")
                        if direct:
                            return direct, js.get("name") or js.get("filename"), js.get("size")
                        
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(random.uniform(1, 3))
                            continue
                        break
                        
        except Exception:
            pass
        return None, None, None
    
    async def _with_lib(self, share_url: str):
        if not get_direct_link:
            return None, None, None
        
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: get_direct_link(share_url))
            return data.get("url"), data.get("name"), data.get("size")
        except Exception:
            return None, None, None
    
    async def _site_flows(self, share_url: str):
        raw = share_url.strip().replace("\\", "/")
        
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers=HTML_HEADERS,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        ) as client:
            
            # Load first page to normalize domain and capture HTML
            r0 = await client.get(raw, headers=HTML_HEADERS)
            r0.raise_for_status()
            
            final = str(r0.url)
            html = r0.text
            host = urlparse(final).netloc.lower()
            q = parse_qs(urlparse(final).query)
            surl = (q.get("surl") or q.get("shorturl") or [None])[0]
            pwd = (q.get("pwd") or q.get("password") or [None])[0]
            
            # A) Official terabox embed: window.pageData JSON with dlink
            m = _PAGE_DATA_RE.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    files = (
                        data.get("shareInfo", {}).get("file_list")
                        or data.get("file_list")
                        or data.get("list")
                        or []
                    )
                    
                    if isinstance(files, list) and files:
                        f0 = files[0]
                        dlink = f0.get("dlink")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        
                        if dlink:
                            return dlink.encode("utf-8").decode("unicode_escape"), name, size
                            
                except Exception:
                    pass
            
            # B) 1024tera/1024terabox API: list -> transfer -> temp dlink
            if any(k in host for k in ["1024tera", "1024terabox"]) and surl:
                list_ep = f"https://www.1024tera.com/share/list?surl={surl}&page=1&pageSize=50"
                if pwd:
                    list_ep += f"&pwd={pwd}"
                
                try:
                    # Add retries for 1024tera API
                    for attempt in range(3):
                        try:
                            jl = await client.get(list_ep, headers=API_HEADERS)
                            jl.raise_for_status()
                            payload = jl.json()
                            
                            items = payload.get("list") or payload.get("data") or payload.get("files") or []
                            if isinstance(items, list) and items:
                                f0 = items[0]
                                name = f0.get("server_filename") or f0.get("filename")
                                size = f0.get("size")
                                
                                # Use dlink if already available
                                dlink = f0.get("dlink") or f0.get("url")
                                if dlink:
                                    return dlink, name, size
                                
                                # Otherwise request transfer
                                fs_id = f0.get("fs_id") or f0.get("fsid") or f0.get("id")
                                body = {"surl": surl, "fs_id": fs_id}
                                if pwd:
                                    body["pwd"] = pwd
                                
                                for ep in [
                                    "https://www.1024tera.com/share/transfer",
                                    "https://www.1024tera.com/api/file/transfer",
                                ]:
                                    jt = await client.post(ep, headers=API_HEADERS, json=body)
                                    if jt.status_code == 200:
                                        jd = jt.json()
                                        cand = (
                                            jd.get("dlink")
                                            or jd.get("url")
                                            or jd.get("data", {}).get("dlink")
                                            or jd.get("data", {}).get("url")
                                        )
                                        
                                        if cand:
                                            return cand, name, size
                            break  # Success, exit retry loop
                        except Exception as e:
                            if attempt < 2:
                                await asyncio.sleep(random.uniform(1, 3))
                                continue
                            break
                            
                except Exception:
                    pass
        
        # No safe direct file link found
        return None, None, None
        
