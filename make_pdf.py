#!/usr/bin/env python3
"""Render a Markdown ETF report to PDF.

Markdown -> HTML via pandoc (falls back to the Python `markdown` package),
then HTML -> PDF via headless Google Chrome.
Usage: make_pdf.py REPORT.md [-o OUT.pdf]   (default: same name, .pdf)
"""
import argparse
import html
from html.parser import HTMLParser
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800"
         "&family=Source+Serif+4:ital,wght@0,600;1,400&display=swap")

CSS = """
:root {
  --navy: #0f2a4a; --blue: #1d5c8f; --teal: #0f9d8a; --ink: #1c2430; --muted: #5b6676;
  --line: #dfe5ec; --zebra: #f6f8fb; --pos: #0a7d3b; --neg: #c0392b;
  --note-bg: #fff8e8; --note-line: #f0b429;
}
@page {
  size: Letter; margin: 0.65in 0.65in 0.7in;
  @bottom-left { content: "ETF Analysis"; font: 500 7.5pt Inter, sans-serif; color: #8a94a3; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 500 7.5pt Inter, sans-serif; color: #8a94a3; }
}
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 10pt/1.55 Inter, -apple-system, "Helvetica Neue", Arial, sans-serif; color: var(--ink); }

h1 { margin: 0 0 14pt; padding: 20pt 22pt; border-radius: 10pt; color: #fff;
     font: 800 22pt/1.2 Inter, sans-serif; letter-spacing: -0.02em;
     background: linear-gradient(120deg, var(--navy) 0%, var(--blue) 70%, var(--teal) 130%); }
h2 { margin: 22pt 0 8pt; padding: 2pt 0 2pt 10pt; border-left: 4pt solid var(--teal);
     font: 700 14.5pt/1.3 Inter, sans-serif; color: var(--navy); letter-spacing: -0.01em; break-after: avoid; }
h3 { margin: 14pt 0 4pt; font: 700 11pt/1.35 Inter, sans-serif; color: var(--blue); break-after: avoid; }
p, li { margin: 4pt 0; }
ul, ol { padding-left: 16pt; }
li::marker { color: var(--teal); }
strong { font-weight: 650; color: #0d1b2e; }
em { font-family: "Source Serif 4", Georgia, serif; font-style: italic; font-size: 1.05em; }
a { color: var(--blue); text-decoration: none; border-bottom: 0.5pt solid #b7c9dc; }

table { border-collapse: separate; border-spacing: 0; width: 100%; margin: 10pt 0 12pt; font-size: 8.6pt;
        border: 1px solid var(--line); border-radius: 7pt; overflow: hidden;
        font-feature-settings: "tnum" 1; }
th { background: var(--navy); color: #fff; font-weight: 600; text-align: left; padding: 6pt 7pt;
     font-size: 8pt; letter-spacing: 0.02em; }
td { padding: 5pt 7pt; border-top: 1px solid var(--line); vertical-align: top; }
tr { break-inside: avoid; }
thead { display: table-header-group; }  /* repeat header row on each page */
tr:nth-child(even) td { background: var(--zebra); }
td:first-child, td.ticker { font-weight: 600; color: var(--navy); }
.pos { color: var(--pos); font-weight: 600; }
.neg { color: var(--neg); font-weight: 600; }

blockquote { margin: 10pt 0 14pt; padding: 9pt 13pt; border-radius: 7pt; background: var(--note-bg);
             border-left: 4pt solid var(--note-line); font-size: 9pt; }
blockquote li { break-inside: avoid; }
blockquote p:first-child { margin-top: 0; }
blockquote p.label { color: #8a5a00; text-transform: uppercase; font-size: 8pt; letter-spacing: 0.06em; }
blockquote strong { color: #6b4500; }
blockquote ul { margin: 4pt 0 0; }

code { font-size: 8.6pt; background: #eef2f6; padding: 1pt 3pt; border-radius: 3pt; }
hr { border: none; border-top: 1px solid var(--line); margin: 16pt 0; }
h2 + ul, h2 + p { margin-top: 6pt; }

.badge { margin: -4pt 0 14pt; padding: 9pt 13pt; border-radius: 8pt; border: 1px solid; font-size: 9pt; }
.badge b { display: block; font-size: 11pt; margin-bottom: 2pt; }
.badge.high    { background: #e8f6ee; border-color: #9fd8b5; color: #0a5c2c; }
.badge.good    { background: #e9f1fa; border-color: #a9c6e6; color: #164a7a; }
.badge.caution { background: #fff5e0; border-color: #f0c674; color: #7a4d00; }
.badge.low     { background: #fdecea; border-color: #f0a8a0; color: #8c1d12; }
.appendix { break-before: page; }
.appendix + h1 { background: linear-gradient(120deg, #3b4656 0%, #5b6676 100%); font-size: 18pt; }
"""

# colour signed numbers in table cells: +12.3% green, -4.5% / −4.5% red
SIGNED = re.compile(r"(<td[^>]*>\s*(?:<strong>)?)([+\-−]\s?\$?\d[\d.,]*%?)")


TICKER = re.compile(r"<td([^>]*)>(\s*[A-Z]{2,5}\s*)</td>")


def colour_numbers(body):
    body = TICKER.sub(r'<td class="ticker"\1>\2</td>', body)  # bold ticker symbols in any column
    body = re.sub(r"<p><strong>(How to read[^<]*)</strong></p>", r'<p class="label"><strong>\1</strong></p>', body)
    return SIGNED.sub(lambda m: f'{m[1]}<span class="{"pos" if m[2][0] == "+" else "neg"}">{m[2]}</span>', body)


CONFIDENCE = re.compile(r"Confidence:\s*(\d+)\s*/\s*100\s*[—–-]\s*(High|Good|Use with caution|Unreliable)", re.I)
LEVELS = {"high": "high", "good": "good", "use with caution": "caution", "unreliable": "low"}


ALLOWED_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "ul", "ol", "li", "blockquote",
                "table", "thead", "tbody", "tr", "th", "td", "strong", "b", "em", "i", "code", "pre",
                "a", "del", "sup", "sub", "span", "colgroup", "col"}
ALLOWED_ATTRS = {"id", "class", "style", "href", "colspan", "rowspan", "start", "width"}


class Sanitizer(HTMLParser):
    """Rebuild HTML keeping only formatting tags; anything else (scripts, images, iframes...) is escaped.

    Reports are written by an agent that reads web pages, so they're treated as untrusted."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []

    def _attrs(self, attrs):
        keep = []
        for k, v in attrs:
            v = v or ""
            if k not in ALLOWED_ATTRS:
                continue
            if k == "href" and not re.match(r"^(https?:|#)", v.strip(), re.I):
                continue  # no javascript:, data:, file: links
            if k == "style" and not re.fullmatch(r"\s*(text-align|width):\s*[\w.%\s-]+;?\s*", v):
                continue
            keep.append(f' {k}="{html.escape(v)}"')
        return "".join(keep)

    def handle_starttag(self, tag, attrs):
        self.out.append(f"<{tag}{self._attrs(attrs)}>" if tag in ALLOWED_TAGS
                        else html.escape(self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        self.out.append(f"<{tag}{self._attrs(attrs)} />" if tag in ALLOWED_TAGS
                        else html.escape(self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.out.append(f"</{tag}>" if tag in ALLOWED_TAGS else html.escape(f"</{tag}>"))

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        pass


def sanitize(body):
    s = Sanitizer()
    s.feed(body)
    s.close()
    return "".join(s.out)


def md_to_body(md_text):
    """Markdown -> sanitized HTML body (raw HTML in the Markdown never reaches Chrome as markup)."""
    if shutil.which("pandoc"):
        body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html"], input=md_text,
                              check=True, capture_output=True, text=True).stdout
    else:
        try:
            import markdown
        except ImportError:
            sys.exit("Need pandoc (brew install pandoc) or the Python 'markdown' package.")
        body = markdown.markdown(md_text, extensions=["tables", "sane_lists"])
    return sanitize(body)


def verification_parts(verification_md):
    """Badge HTML for under the report's title, and the verification body for the appendix."""
    badge = ""
    m = CONFIDENCE.search(verification_md)
    if m:
        score, label = m[1], m[2].strip()
        badge = (f'<div class="badge {LEVELS.get(label.lower(), "good")}">'
                 f'<b>Verified · Confidence {score}/100 · {html.escape(label)}</b>'
                 f'<span>Independent check of every number, the key news claims and the reasoning: '
                 f'see the Verification appendix at the end.</span></div>')
    appendix = re.sub(r"^# (.*)$", r"# Appendix: \1", verification_md, count=1, flags=re.M)
    return badge, md_to_body(appendix)


# No scripts, no network except the fonts: a report can't make Chrome run code or call other hosts
CSP = ("default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src data:")


def build_html(report_md, title, verification_md=None):
    body = md_to_body(report_md)
    if verification_md:
        badge, appendix = verification_parts(verification_md)
        body = re.sub(r"(</h1>)", lambda m: m[1] + badge, body, count=1)
        body += f'<div class="appendix"></div>{appendix}'
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta http-equiv='Content-Security-Policy' content=\"{CSP}\">"
            f"<title>{html.escape(title)}</title>"
            f"<link rel='stylesheet' href='{FONTS}'><style>{CSS}</style></head>"
            f"<body>{colour_numbers(body)}</body></html>")


def find_chrome():
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("Google Chrome (or Chromium/Edge) is required to print the PDF.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--verification", type=Path,
                    help="verification report to show as a confidence badge + appendix")
    args = ap.parse_args()
    out = (args.out or args.report.with_suffix(".pdf")).resolve()
    verification = args.verification.read_text() if args.verification else None

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(build_html(args.report.read_text(), args.report.stem, verification))
        subprocess.run([find_chrome(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=10000",  # let web fonts load before printing
                        f"--print-to-pdf={out}", page.as_uri()],
                       check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()
