from pathlib import Path

import pytest

from etf_analyst import paths


def test_confine_accepts_files_inside_base(tmp_path: Path) -> None:
    assert (
        paths.confine(tmp_path / "r.md", tmp_path, ".md", "report") == (tmp_path / "r.md").resolve()
    )


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.md", "inside.txt", "sub/../../up.md"])
def test_confine_refuses_other_paths(path: str, tmp_path: Path) -> None:
    candidate = path if path.startswith("/") else tmp_path / path
    with pytest.raises(paths.PathError, match="report must be a .md file"):
        paths.confine(candidate, tmp_path, ".md", "report")


def test_confine_refuses_symlinks_that_point_outside(tmp_path: Path) -> None:
    base = tmp_path / "reports"
    base.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("x")
    (base / "link.md").symlink_to(secret)
    with pytest.raises(paths.PathError):
        paths.confine(base / "link.md", base, ".md", "report")


def test_reports_dir_is_inside_the_repository() -> None:
    assert (paths.ROOT / "pyproject.toml").exists()
    assert paths.DATA_DIR.parent == paths.REPORTS_DIR
