# utils/validators.py
import re
from urllib.parse import urlparse

_TB_HOSTS = {
    "terabox.com", "www.terabox.com",
    "nephobox.com", "www.nephobox.com",
    "4funbox.com", "www.4funbox.com",
    "tibx.cc", "www.tibx.cc",  # common shorteners
    "teraboxapp.com", "www.teraboxapp.com",
}

def is_terabox_url(raw: str) -> bool:
    # Normalize slashes and strip spaces
    s = raw.strip().replace("\\", "/")
    try:
        u = urlparse(s)
        host = (u.netloc or "").lower()
        if host in _TB_HOSTS:
            return True
        # Accept t.me/clickable text where schema is missing
        if not u.scheme and any(h in s.lower() for h in _TB_HOSTS):
            return True
    except Exception:
        pass
    return False

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-. ]", "_", name)
    
