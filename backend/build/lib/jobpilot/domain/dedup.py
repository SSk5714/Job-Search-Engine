"""Deterministic URL normalization and cross-source fingerprints."""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "refid", "trk", "trkid",
    "src", "source", "campaign", "from", "sid", "tracking", "cmp", "icid", "lipi", "origin",
}


def normalize_url(url: str) -> str:
    """Canonical form used for the unique constraint on jobs.

    - lowercase scheme and host, drop `www.` and default ports
    - drop fragment and tracking parameters (utm_* and a known list)
    - sort remaining query parameters
    - strip trailing slash on the path
    """
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"\b(gmbh|ag|se|kg|co|ltd|inc|m/w/d|w/m/d|m/f/d|f/m/d|all genders)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def fingerprint(company: str, title: str, city: str | None) -> str:
    """Same job posted on two boards usually shares company + title + city."""
    raw = "|".join([_slug(company), _slug(title), _slug(city or "")])
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
