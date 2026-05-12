import re
from urllib.parse import urlparse

_URL_REGEX = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def sanitize_url(url: str) -> str:
    """Mask the hostname or IP of a URL, preserving scheme and port."""
    if not isinstance(url, str):
        return url
    try:
        parsed = urlparse(url)
        if not parsed.netloc and parsed.path:
            parsed = urlparse("//" + url)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        scheme = f"{parsed.scheme}://" if parsed.scheme else ""
        masked_host = ""
        if host:
            masked_host = ".".join(["***"] * (host.count(".") + 1))
        return f"{scheme}{masked_host}{port}{parsed.path or ''}"
    except Exception:
        return url


def sanitize_error_message(error_msg: str) -> str:
    """Detect and sanitize URLs inside an error message."""
    if not isinstance(error_msg, str):
        return str(error_msg)
    return _URL_REGEX.sub(lambda m: sanitize_url(m.group(0)), error_msg)


def safe_http_error_message(response, original_error: Exception) -> str:
    """Return a sanitized HTTP error message."""
    try:
        detail = response.json()
    except Exception:
        try:
            detail = response.text[:500]
        except Exception:
            detail = ""
    base = sanitize_error_message(str(original_error))
    detail_msg = sanitize_error_message(str(detail))
    return f"{base}: {detail_msg}" if detail_msg else base


def safe_exception_message(exception: Exception) -> str:
    """Return a sanitized string representation of an exception."""
    return sanitize_error_message(str(exception))
