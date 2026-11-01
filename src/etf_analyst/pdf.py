"""Render a Markdown ETF report to PDF.

Markdown -> HTML via pandoc (falls back to the Python ``markdown`` package), then the
allowlist sanitizer, then HTML -> PDF via headless Google Chrome. Styles live in
``assets/report.css``. Input and output paths must be inside ``reports/``.

Usage:
    etf-pdf REPORT.md [-o OUT.pdf] [--verification VERIFICATION.md] [--confidence 0-100]
"""

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from etf_analyst import paths
from etf_analyst.sanitize import sanitize

STYLESHEET = files("etf_analyst") / "assets" / "report.css"
CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
CHROME_COMMANDS = ("google-chrome", "chromium", "chromium-browser")
FONT_WAIT_MS = 10_000  # let web fonts load before Chrome prints
FONTS = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800"
    "&family=Source+Serif+4:ital,wght@0,600;1,400&display=swap"
)
# No scripts, no network except the fonts: a report can't make Chrome run code or call other hosts
CSP = (
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src data:"
)
# colour signed numbers in table cells: +12.3% green, -4.5% / −4.5% red
SIGNED = re.compile(r"(<td[^>]*>\s*(?:<strong>)?)([+\-−]\s?\$?\d[\d.,]*%?)")
TICKER_CELL = re.compile(r"<td([^>]*)>(\s*[A-Z]{2,5}\s*)</td>")
GLOSSARY_LABEL = re.compile(r"<p><strong>(How to read[^<]*)</strong></p>")
CONFIDENCE = re.compile(
    r"Confidence:\s*(\d+)\s*/\s*100\s*[—–-]\s*(High|Good|Use with caution|Unreliable)",
    re.IGNORECASE,
)
BADGE_CLASS = {"High": "high", "Good": "good", "Use with caution": "caution", "Unreliable": "low"}


def md_to_body(md_text: str) -> str:
    """Convert Markdown to a sanitized HTML body (raw HTML never reaches Chrome as markup)."""
    if shutil.which("pandoc"):
        body = subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html"],  # noqa: S607 -- resolved via PATH on purpose
            input=md_text,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    else:
        try:
            import markdown  # optional fallback dependency
        except ImportError:
            sys.exit("Need pandoc (brew install pandoc) or the Python 'markdown' package.")
        body = markdown.markdown(md_text, extensions=["tables", "sane_lists"])
    return sanitize(body)


def style_numbers(body: str) -> str:
    """Add CSS classes: bold tickers, the glossary label, and green/red signed numbers."""
    body = TICKER_CELL.sub(r'<td class="ticker"\1>\2</td>', body)
    body = GLOSSARY_LABEL.sub(r'<p class="label"><strong>\1</strong></p>', body)

    def colour(m: re.Match[str]) -> str:
        css_class = "pos" if m[2].startswith("+") else "neg"
        return f'{m[1]}<span class="{css_class}">{m[2]}</span>'

    return SIGNED.sub(colour, body)


def label_for(score: int) -> str:
    """Return the confidence label for a 0-100 score (bands match the verifier's rubric)."""
    if score >= 90:
        return "High"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Use with caution"
    return "Unreliable"


def verification_parts(verification_md: str, confidence: int | None = None) -> tuple[str, str]:
    """Return the badge HTML (for under the title) and the appendix HTML.

    Args:
        verification_md: The verifier's Markdown report.
        confidence: The score after run-report.sh's own checks; overrides the one in the text.
    """
    badge = ""
    m = CONFIDENCE.search(verification_md)
    score = confidence if confidence is not None else (int(m[1]) if m else None)
    if score is not None:
        label = label_for(score)
        badge = (
            f'<div class="badge {BADGE_CLASS[label]}">'
            f"<b>Verified · Confidence {score}/100 · {html.escape(label)}</b>"
            "<span>Independent check of every number, the key news claims and the reasoning: "
            "see the Verification appendix at the end.</span></div>"
        )
    appendix = re.sub(r"^# (.*)$", r"# Appendix: \1", verification_md, count=1, flags=re.MULTILINE)
    return badge, md_to_body(appendix)


def build_html(
    report_md: str,
    title: str,
    verification_md: str | None = None,
    confidence: int | None = None,
) -> str:
    """Build the full HTML page for Chrome to print (sanitized body, CSP, styles, badge)."""
    body = md_to_body(report_md)
    if verification_md:
        badge, appendix = verification_parts(verification_md, confidence)
        # added *after* sanitizing: it's our own markup, built from escaped values
        body = body.replace("</h1>", f"</h1>{badge}", 1)
        body += f'<div class="appendix"></div>{appendix}'
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta http-equiv='Content-Security-Policy' content=\"{CSP}\">"
        f"<title>{html.escape(title)}</title>"
        f"<link rel='stylesheet' href='{FONTS}'><style>{STYLESHEET.read_text()}</style></head>"
        f"<body>{style_numbers(body)}</body></html>"
    )


def find_chrome() -> str:
    """Return the path of an installed Chrome, Chromium or Edge, or exit with a message."""
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    for name in CHROME_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Google Chrome (or Chromium/Edge) is required to print the PDF.")


def print_pdf(page_html: str, out: Path) -> None:
    """Write ``page_html`` to a temporary file and have headless Chrome print it to ``out``."""
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(page_html)
        subprocess.run(
            [
                find_chrome(),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--virtual-time-budget={FONT_WAIT_MS}",
                f"--print-to-pdf={out}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("report", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument(
        "--verification",
        type=Path,
        help="verification report to show as a confidence badge + appendix",
    )
    ap.add_argument(
        "--confidence",
        type=int,
        choices=range(101),
        metavar="0-100",
        help="score to show on the badge (overrides the one in the verification text)",
    )
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Render the report given on the command line and print the PDF's path."""
    args = parse_args(argv)
    reports = paths.REPORTS_DIR
    try:
        report = paths.confine(args.report, reports, ".md", "report")
        out = paths.confine(args.out or report.with_suffix(".pdf"), reports, ".pdf", "output")
        verification = None
        if args.verification:
            verification = paths.confine(
                args.verification, reports, ".md", "verification"
            ).read_text()
    except paths.PathError as e:
        sys.exit(str(e))
    print_pdf(build_html(report.read_text(), report.stem, verification, args.confidence), out)
    print(out)


if __name__ == "__main__":
    main()
