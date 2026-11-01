"""Where the project keeps its files, and the guard that keeps untrusted paths inside them.

The agents that call this package read web search results, so any path they pass in (or that
appears inside a report) is untrusted. ``confine`` is the single place that decides whether such
a path is acceptable.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the repository (src/etf_analyst/paths.py -> repo)
REPORTS_DIR = ROOT / "reports"
DATA_DIR = REPORTS_DIR / "data"


class PathError(ValueError):
    """A path is outside the directory it must stay in, or has the wrong extension."""


def confine(path: Path | str, base: Path, suffix: str, what: str) -> Path:
    """Resolve ``path`` and return it if it's a ``suffix`` file inside ``base``.

    Resolving first means ``..`` segments and symlinks can't escape ``base``.

    Args:
        path: The path to check; ``~`` is expanded.
        base: The directory the file must be inside.
        suffix: Required extension, e.g. ``".md"``.
        what: Name used in the error message, e.g. ``"report"``.

    Returns:
        The resolved absolute path.

    Raises:
        PathError: The path is outside ``base`` or has a different extension.

    Example:
        >>> confine("/etc/passwd", REPORTS_DIR, ".md", "report")
        Traceback (most recent call last):
        ...
        etf_analyst.paths.PathError: report must be a .md file inside .../reports
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(base.resolve()) or resolved.suffix != suffix:
        raise PathError(f"{what} must be a {suffix} file inside {base}")
    return resolved
