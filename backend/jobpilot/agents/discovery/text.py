"""HTML-to-text for job descriptions. Output is plain text only: no markup, no
scripts, no links are kept, so stored descriptions can never execute anything."""

import html
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}
_SKIP = {"script", "style", "noscript", "template"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif tag in _BLOCK and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value: str | None, limit: int = 20000) -> str:
    if not value:
        return ""
    # Greenhouse returns entity-encoded HTML (&lt;p&gt;…); decode once before parsing.
    if "&lt;" in value and "<" not in value:
        value = html.unescape(value)
    p = _Extractor()
    p.feed(value)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def location_parts(name: str | None) -> tuple[str | None, str | None]:
    """'Munich, Germany' -> ('Munich', 'DE'). Unknown countries return None."""
    if not name:
        return None, None
    from jobpilot.agents.discovery.countries import country_code, is_country_name

    parts = [p.strip() for p in re.split(r"[,;/|]", name) if p.strip()]
    country = None
    for p in reversed(parts):
        country = country_code(p)
        if country:
            break
    city = next((p for p in parts if not is_country_name(p) and p.lower() not in ("remote", "hybrid")), None)
    return city, country
