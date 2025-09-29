# services/terabox.py
import asyncio
import json
import httpx
import re
from urllib.parse import urlparse, parse_qs
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Optional external helper if later added
try:
    from terabox_linker import get_direct_link  # type: ignore
except Exception:
    get_direct_link = None

_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)

API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://www.terabox.com/",
}

HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.terabox.com/",
}

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        # Try optional third-party helper first
        url, name, size = await self._with_lib(share_url)
        if not url:
            # Use API-first flow modeled after Mirror-Leech implementations
            url, name, size = await self._api_first_flow(share_url)
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

    async def _api_first_flow(self, share_url: str):
        raw = share_url.strip().replace("\\", "/")
        async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
            # 0) Load landing to normalize domain and capture embedded JSON if present
            r0 = await client.get(raw, headers=HTML_HEADERS)
            r0.raise_for_status()
            final = str(r0.url)
            html = r0.text
            host = urlparse(final).netloc.lower()
            q = parse_qs(urlparse(final).query)
            surl = (q.get("surl") or q.get("shorturl") or [None])[0]
            pwd = (q.get("pwd") or q.get("password") or [None])[0]

            # A) Official terabox pageData JSON with dlink/name/size
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

            # B) 1024tera/1024terabox: call list API then transfer API to get temp dlink
            if any(k in host for k in ["1024tera", "1024terabox"]) and surl:
                list_ep = f"https://www.1024tera.com/share/list?surl={surl}&page=1&pageSize=50"
                if pwd:
                    list_ep += f"&pwd={pwd}"
                try:
                    jl = await client.get(list_ep, headers=API_HEADERS)
                    jl.raise_for_status()
                    payload = jl.json()
                    items = payload.get("list") or payload.get("data") or payload.get("files") or []
                    if isinstance(items, list) and items:
                        f0 = items[0]
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        # Use dlink if included
                        dlink = f0.get("dlink") or f0.get("url")
                        if dlink:
                            return dlink, name, size
                        # Else call transfer to get temp link
                        fs_id = f0.get("fs_id") or f0.get("fsid") or f0.get("id")
                        body = {"surl": surl, "fs_id": fs_id}
                        if pwd:
                            body["pwd"] = pwd
                        for ep in [
                            "https://www.1024tera.com/share/transfer",
                            "https://www.1024tera.com/api/file/transfer",
                        ]:
                            try:
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
                            except Exception:
                                continue
                except Exception:
                    pass

            # C) Last resort: if final URL is already a CDN (not terabox host), use it
            if final and "terabox" not in urlparse(final).netloc.lower():
                return final, None, None

        return None, None, None
                    
