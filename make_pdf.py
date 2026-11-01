#!/usr/bin/env python3
"""Render a Markdown ETF report to PDF.

Markdown -> HTML via pandoc (falls back to the Python `markdown` package),
then HTML -> PDF via headless Google Chrome.
Usage: make_pdf.py REPORT.md [-o OUT.pdf]   (default: same name, .pdf)
"""
import argparse
import html
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

CSS = """
@page { size: Letter; margin: 0.6in 0.6in; }
body { font: 10.5pt/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4pt; color: #1f4e79; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; color: #1f4e79; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p, li { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; break-inside: avoid; }
th, td { border: 1px solid #c8d1dc; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #e8eef5; }
tr:nth-child(even) td { background: #f7f9fb; }
code { font-size: 9pt; background: #f1f3f5; padding: 0 2pt; border-radius: 2pt; }
hr { border: none; border-top: 1px solid #c8d1dc; margin: 14pt 0; }
a { color: #1f4e79; }
blockquote { margin: 6pt 0; padding: 4pt 10pt; border-left: 3px solid #1f4e79; background: #f4f7fa; }
"""


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
            f"<style>{CSS}</style></head><body>{body}</body></html>")


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
                        f"--print-to-pdf={out}", page.as_uri()],
                       check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()
