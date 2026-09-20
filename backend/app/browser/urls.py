import re
from urllib.parse import quote_plus

SEARCH_URL = "https://www.google.com/search?q="
_ALLOWED_SCHEMES = {"http", "https"}
_HAS_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*)://", re.IGNORECASE)
# Schemes that don't use "//" but are dangerous or meaningless to navigate to.
_BLOCKED_PREFIX = re.compile(r"^(javascript|data|file|chrome|about|view-source|blob|vbscript):", re.IGNORECASE)
# "example.com", "www.example.co.uk/path", "localhost:8000" — a dotted host
# (alphabetic TLD) with an optional port and path, and no spaces.
_LOOKS_LIKE_HOST = re.compile(r"^[\w\-]+(\.[\w\-]+)*\.[a-z]{2,}(:\d+)?(/\S*)?$", re.IGNORECASE)


def normalize_address(text: str) -> str:
    """Turn whatever was typed into the address field into an http(s) URL.

    Full URLs pass through, bare hostnames get https://, and anything else is
    treated as search terms — so the on-screen keyboard can drive a Google
    search without ever typing inside a web page. Only http(s) is allowed:
    the browser is steered remotely, and file:/javascript: etc. have no place
    here.
    """
    text = text.strip()
    if not text:
        raise ValueError("Enter a web address or something to search for")

    scheme_match = _HAS_SCHEME.match(text)
    if scheme_match:
        if scheme_match.group(1).lower() not in _ALLOWED_SCHEMES:
            raise ValueError("Only http and https addresses are supported")
        return text
    if _BLOCKED_PREFIX.match(text):
        raise ValueError("Only http and https addresses are supported")

    if _LOOKS_LIKE_HOST.match(text):
        return f"https://{text}"
    return SEARCH_URL + quote_plus(text)


def is_web_url(url: str) -> bool:
    match = _HAS_SCHEME.match(url or "")
    return bool(match) and match.group(1).lower() in _ALLOWED_SCHEMES
