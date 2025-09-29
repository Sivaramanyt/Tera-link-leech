# services/terabox.py
import asyncio
import re
import json
import httpx
from urllib.parse import urlparse, parse_qs
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

try:
    from terabox_linker import get_direct_link  # optional
except Exception:
    get_direct_link = None

_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        url, name, size = await self._with_lib(share_url)
        if not url:
            url, name, size = await self._from_page_or_api(share_url)
        if not url:
            raise RuntimeError("Unable to resolve direct link")
        return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)

    async def _with_lib(self, share_url: str):
        if not get_direct_link:
            return None, None, None
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: get_direct_link(share_url))
            return data.get("url"), data.get("name"), data.get("size")
        except Exception:
            return None, None, None

    async def _from_page_or_api(self, share_url: str):
        url = share_url.strip().replace("\\", "/")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.terabox.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=25) as client:
            r = await client.get(url)
            r.raise_for_status()
            final_url = str(r.url)
            html = r.text

            # A) Official terabox pageData path
            m = _PAGE_DATA_RE.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    file_list = (
                        data.get("shareInfo", {}).get("file_list")
                        or data.get("file_list")
                        or data.get("list")
                        or []
                    )
                    if isinstance(file_list, list) and file_list:
                        f0 = file_list[0]
                        dlink = f0.get("dlink")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink.encode("utf-8").decode("unicode_escape"), name, size
                except Exception:
                    pass

            # B) 1024terabox/1024tera API path: build list API call using surl (and optional pwd)
            parsed = urlparse(final_url)
            host = parsed.netloc.lower()
            q = parse_qs(parsed.query)
            surl = (q.get("surl") or q.get("shorturl") or q.get("shareid") or [None])[0]
            pwd = (q.get("pwd") or q.get("password") or [None])[0]

            if any(h in host for h in ["1024terabox", "1024tera", "1024terabox.com", "1024tera.com"]) and surl:
                api = f"https://www.1024tera.com/share/list?surl={surl}&page=1&pageSize=50"
                if pwd:
                    api += f"&pwd={pwd}"
                try:
                    j = await client.get(api, headers={"Accept": "application/json"})
                    j.raise_for_status()
                    data = j.json()
                    arr = data.get("list") or data.get("data") or data.get("files") or []
                    if isinstance(arr, list) and arr:
                        f0 = arr[0]
                        dlink = f0.get("dlink") or f0.get("url")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink, name, size
                except Exception:
                    pass

            # C) Last resort: find `var list = [...]` embedded
            try:
                jmatch = re.search(r"var\s+list\s*=\s*(\[\s*{.*?}\s*]);", html, re.DOTALL)
                if jmatch:
                    arr = json.loads(jmatch.group(1))
                    if isinstance(arr, list) and arr:
                        f0 = arr[0]
                        dlink = f0.get("dlink") or f0.get("url")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink, name, size
            except Exception:
                pass

            # D) Fallback: follow redirect to CDN and infer headers
            try:
                if final_url and "terabox" not in final_url:
                    h = await client.head(final_url)
                    size = int(h.headers.get("content-length") or 0) or None
                    cd = h.headers.get("content-disposition", "")
                    name = None
                    if "filename=" in cd:
                        name = cd.split("filename=")[-1].strip('"; ')
                    return final_url, name, size
            except Exception:
                pass

        return None, None, None
                    
