import shutil
from pathlib import Path

import pytest

import make_pdf


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        '<img src="http://127.0.0.1:9/x" onerror="alert(2)">',
        '<iframe src="file:///etc/passwd"></iframe>',
        '<a href="javascript:alert(3)">x</a>',
        '<p style="background:url(http://evil)">x</p>',
        '<div onclick="alert(4)">x</div>',
    ],
)
def test_sanitize_neutralizes_hostile_html(hostile: str) -> None:
    cleaned = make_pdf.sanitize(hostile)
    for live in ("<script", "<img", "<iframe", "javascript:", "url(", "<div"):
        assert live not in cleaned


def test_sanitize_keeps_formatting_and_safe_links() -> None:
    html = (
        '<h2 id="x">Title</h2><p><strong>bold</strong> <a href="https://cnbc.com">link</a></p>'
        '<table><tr><td style="text-align: left;">VOO</td></tr></table>'
    )
    assert make_pdf.sanitize(html) == html


def test_markdown_raw_html_never_becomes_markup() -> None:
    body = make_pdf.md_to_body("# T\n\n<script>alert(1)</script>\n")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_style_numbers_colours_signed_values() -> None:
    styled = make_pdf.style_numbers("<td>+1.2%</td><td>−3.4%</td><td>5.6%</td>")
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
    assert make_pdf.label_for(score) == label


def test_badge_uses_the_capped_score_over_the_text() -> None:
    verification = "# Verification\n\n> **Confidence: 95 / 100 — High**\n"
    badge, appendix = make_pdf.verification_parts(verification, confidence=74)
    assert "Confidence 74/100 · Use with caution" in badge
    assert 'class="badge caution"' in badge
    assert "Appendix: Verification" in appendix


def test_build_html_sets_a_restrictive_content_security_policy() -> None:
    page = make_pdf.build_html("# Title\n\ntext", "t")
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page


def test_in_reports_refuses_paths_outside_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(make_pdf, "REPORTS", tmp_path)
    assert make_pdf.in_reports(tmp_path / "a.md", ".md", "report") == (tmp_path / "a.md").resolve()
    for bad in (Path("/etc/passwd"), tmp_path / ".." / "x.md", tmp_path / "a.txt"):
        with pytest.raises(SystemExit):
            make_pdf.in_reports(bad, ".md", "report")


def test_markdown_fallback_is_also_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("markdown")
    monkeypatch.setattr(shutil, "which", lambda name: None)  # pretend pandoc is missing
    body = make_pdf.md_to_body("# T\n\n<script>alert(1)</script>\n\n| A |\n|---|\n| +1% |\n")
    assert "<script>" not in body
    assert "<table>" in body


def test_main_builds_the_page_and_prints_the_pdf_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "etf-report.md"
    report.write_text("# ETF Analysis\n\n| Ticker | 1m |\n|---|---|\n| VOO | +1.0% |\n")
    verification = tmp_path / "etf-report-verification.md"
    verification.write_text("# Verification\n\n> **Confidence: 95 / 100 — High**\n")
    printed: dict[str, str] = {}
    monkeypatch.setattr(make_pdf, "REPORTS", tmp_path)
    monkeypatch.setattr(
        make_pdf, "print_pdf", lambda page, out: printed.update(page=page, out=str(out))
    )

    make_pdf.main([str(report), "--verification", str(verification), "--confidence", "74"])

    assert printed["out"] == str(report.with_suffix(".pdf").resolve())
    assert "Confidence 74/100" in printed["page"]
    assert '<span class="pos">+1.0%</span>' in printed["page"]
    assert capsys.readouterr().out.strip() == printed["out"]
