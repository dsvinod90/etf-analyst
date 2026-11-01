#!/usr/bin/env python3
"""Render a Markdown ETF report to PDF.

Markdown -> HTML via pandoc (falls back to the Python `markdown` package),
then HTML -> PDF via headless Google Chrome.
Usage: make_pdf.py REPORT.md [-o OUT.pdf]   (default: same name, .pdf)
"""
import argparse
import html
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
blockquote p:first-child { margin-top: 0; color: #8a5a00; text-transform: uppercase; font-size: 8pt;
                           letter-spacing: 0.06em; }
blockquote strong { color: #6b4500; }
blockquote ul { margin: 4pt 0 0; }

code { font-size: 8.6pt; background: #eef2f6; padding: 1pt 3pt; border-radius: 3pt; }
hr { border: none; border-top: 1px solid var(--line); margin: 16pt 0; }
h2 + ul, h2 + p { margin-top: 6pt; }
"""

# colour signed numbers in table cells: +12.3% green, -4.5% / −4.5% red
SIGNED = re.compile(r"(<td[^>]*>\s*(?:<strong>)?)([+\-−]\s?\$?\d[\d.,]*%?)")


TICKER = re.compile(r"<td([^>]*)>(\s*[A-Z]{2,5}\s*)</td>")


def colour_numbers(body):
    body = TICKER.sub(r'<td class="ticker"\1>\2</td>', body)  # bold ticker symbols in any column
    return SIGNED.sub(lambda m: f'{m[1]}<span class="{"pos" if m[2][0] == "+" else "neg"}">{m[2]}</span>', body)


def md_to_html(md_path, title):
    if shutil.which("pandoc"):
        body = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", str(md_path)],
                              check=True, capture_output=True, text=True).stdout
    else:
        try:
            import markdown
        except ImportError:
            sys.exit("Need pandoc (brew install pandoc) or the Python 'markdown' package.")
        body = markdown.markdown(md_path.read_text(), extensions=["tables", "sane_lists"])
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
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
    args = ap.parse_args()
    out = (args.out or args.report.with_suffix(".pdf")).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(md_to_html(args.report, args.report.stem))
        # CI runners (Linux) can't use Chrome's sandbox
        sandbox = ["--no-sandbox"] if sys.platform.startswith("linux") else []
        subprocess.run([find_chrome(), "--headless", "--disable-gpu", "--no-pdf-header-footer", *sandbox,
                        "--virtual-time-budget=10000",  # let web fonts load before printing
                        f"--print-to-pdf={out}", page.as_uri()],
                       check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()
