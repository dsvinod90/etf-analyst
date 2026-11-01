import shutil
from pathlib import Path

import pytest

from etf_analyst import pdf


def test_markdown_raw_html_never_becomes_markup() -> None:
    body = pdf.md_to_body("# T\n\n<script>alert(1)</script>\n")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_style_numbers_colours_signed_values() -> None:
    styled = pdf.style_numbers("<td>+1.2%</td><td>−3.4%</td><td>5.6%</td>")
    assert '<span class="pos">+1.2%</span>' in styled
    assert '<span class="neg">−3.4%</span>' in styled
    assert "<td>5.6%</td>" in styled


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (100, "High"),
        (90, "High"),
        (89, "Good"),
        (75, "Good"),
        (74, "Use with caution"),
        (59, "Unreliable"),
    ],
)
def test_label_for_uses_the_rubric_bands(score: int, label: str) -> None:
    assert pdf.label_for(score) == label


def test_badge_uses_the_capped_score_over_the_text() -> None:
    verification = "# Verification\n\n> **Confidence: 95 / 100 — High**\n"
    badge, appendix = pdf.verification_parts(verification, confidence=74)
    assert "Confidence 74/100 · Use with caution" in badge
    assert 'class="badge caution"' in badge
    assert "Appendix: Verification" in appendix


def test_build_html_sets_a_restrictive_content_security_policy() -> None:
    page = pdf.build_html("# Title\n\ntext", "t")
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page


def test_markdown_fallback_is_also_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("markdown")
    monkeypatch.setattr(shutil, "which", lambda name: None)  # pretend pandoc is missing
    body = pdf.md_to_body("# T\n\n<script>alert(1)</script>\n\n| A |\n|---|\n| +1% |\n")
    assert "<script>" not in body
    assert "<table>" in body


def test_main_builds_the_page_and_prints_the_pdf_path(
    tmp_reports: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_reports / "etf-report.md"
    report.write_text("# ETF Analysis\n\n| Ticker | 1m |\n|---|---|\n| VOO | +1.0% |\n")
    verification = tmp_reports / "etf-report-verification.md"
    verification.write_text("# Verification\n\n> **Confidence: 95 / 100 — High**\n")
    printed: dict[str, str] = {}
    monkeypatch.setattr(pdf, "print_pdf", lambda page, out: printed.update(page=page, out=str(out)))

    pdf.main([str(report), "--verification", str(verification), "--confidence", "74"])

    assert printed["out"] == str(report.with_suffix(".pdf").resolve())
    assert "Confidence 74/100" in printed["page"]
    assert '<span class="pos">+1.0%</span>' in printed["page"]
    assert capsys.readouterr().out.strip() == printed["out"]


def test_main_refuses_output_outside_reports(tmp_reports: Path) -> None:
    report = tmp_reports / "r.md"
    report.write_text("# T")
    with pytest.raises(SystemExit, match="output must be a .pdf file"):
        pdf.main([str(report), "-o", str(tmp_reports.parent / "x.pdf")])


def test_stylesheet_ships_with_the_package() -> None:
    assert ":root" in pdf.STYLESHEET.read_text()
