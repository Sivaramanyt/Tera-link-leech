# utils/validators.py
import re
from urllib.parse import urlparse

_TB_HOSTS = {
    "terabox.com", "www.terabox.com",
    "nephobox.com", "www.nephobox.com",
    "4funbox.com", "www.4funbox.com",
    "tibx.cc", "www.tibx.cc",
    "teraboxapp.com", "www.teraboxapp.com",
}

def is_terabox_url(raw: str) -> bool:
    if not raw:
        return False
    s = raw.strip().replace("\\", "/")
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s  # tolerate schema-less paste
    try:
        u = urlparse(s)
        host = (u.netloc or "").lower()
        return any(host.endswith(h) for h in _TB_HOSTS)
    except Exception:
        return False

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-. ]", "_", name)
    
