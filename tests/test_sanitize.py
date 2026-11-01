import pytest

from etf_analyst.sanitize import sanitize


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
    cleaned = sanitize(hostile)
    for live in ("<script", "<img", "<iframe", "javascript:", "url(", "<div"):
        assert live not in cleaned


def test_sanitize_keeps_formatting_and_safe_links() -> None:
    html = (
        '<h2 id="x">Title</h2><p><strong>bold</strong> <a href="https://cnbc.com">link</a></p>'
        '<table><tr><td style="text-align: left;">VOO</td></tr></table>'
    )
    assert sanitize(html) == html


def test_sanitize_drops_comments_and_keeps_entities() -> None:
    assert sanitize("<p>a &amp; b &#8722;1<!-- hidden --></p>") == "<p>a &amp; b &#8722;1</p>"
