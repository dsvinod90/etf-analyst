"""Allowlist HTML sanitizer for rendered reports.

Reports are written by an agent that reads web pages, so their HTML is untrusted. Only
formatting tags and a few attributes survive; everything else is escaped into visible text.
"""

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = frozenset(
    [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "ul",
        "ol",
        "li",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "colgroup",
        "col",
        "strong",
        "b",
        "em",
        "i",
        "code",
        "pre",
        "a",
        "del",
        "sup",
        "sub",
        "span",
    ]
)
ALLOWED_ATTRS = frozenset({"id", "class", "style", "href", "colspan", "rowspan", "start", "width"})
SAFE_HREF = re.compile(r"^(https?:|#)", re.IGNORECASE)  # no javascript:, data:, file: links
SAFE_STYLE = re.compile(r"\s*(text-align|width):\s*[\w.%\s-]+;?\s*")


class Sanitizer(HTMLParser):
    """Rebuild HTML keeping only formatting tags and attributes; everything else is escaped.

    Reports are written by an agent that reads web pages, so their HTML is untrusted:
    ``<script>``, ``<img>``, ``<iframe>`` and the like come out as visible, inert text.
    """

    def __init__(self) -> None:
        """Start with empty output; feed HTML with ``feed()``."""
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> str:
        keep = []
        for name, raw in attrs:
            value = raw or ""
            if name not in ALLOWED_ATTRS:
                continue
            if name == "href" and not SAFE_HREF.match(value.strip()):
                continue
            if name == "style" and not SAFE_STYLE.fullmatch(value):
                continue
            keep.append(f' {name}="{html.escape(value)}"')
        return "".join(keep)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], close: str) -> None:
        if tag in ALLOWED_TAGS:
            self.out.append(f"<{tag}{self._attrs(attrs)}{close}>")
        else:
            self.out.append(html.escape(self.get_starttag_text() or ""))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Keep an allowed opening tag (with safe attributes); escape any other."""
        self._start(tag, attrs, "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Keep an allowed self-closing tag (e.g. ``<br />``); escape any other."""
        self._start(tag, attrs, " /")

    def handle_endtag(self, tag: str) -> None:
        """Keep an allowed closing tag; escape any other."""
        self.out.append(f"</{tag}>" if tag in ALLOWED_TAGS else html.escape(f"</{tag}>"))

    def handle_data(self, data: str) -> None:
        """Escape text so it can't be read as markup."""
        self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        """Pass named entities like ``&amp;`` through unchanged."""
        self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        """Pass numeric entities like ``&#8722;`` through unchanged."""
        self.out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        """Drop HTML comments."""


def sanitize(body: str) -> str:
    """Return ``body`` with every tag and attribute outside the allowlists escaped."""
    parser = Sanitizer()
    parser.feed(body)
    parser.close()
    return "".join(parser.out)
