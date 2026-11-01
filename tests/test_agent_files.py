"""The agent instructions and run-report.sh must match the code they drive.

The agents only know what their Markdown files tell them, so a renamed command or moved file
that isn't updated there breaks the daily run without failing any other test.
"""

import re
import tomllib
from pathlib import Path

import pytest

from etf_analyst import paths

AGENT_FILES = sorted((paths.ROOT / ".claude" / "agents").glob("*.md"))
RUN_REPORT = paths.ROOT / "run-report.sh"
REPO_PATH = re.compile(r"~/Dev/etf-analyst/([\w./-]+)")
VENV_COMMAND = re.compile(r"\.venv/bin/(etf-[a-z-]+)")


def declared_commands() -> set[str]:
    pyproject = tomllib.loads((paths.ROOT / "pyproject.toml").read_text())
    return set(pyproject["project"]["scripts"])


def allowed_commands() -> set[str]:
    m = re.search(r"^COMMANDS=\(([^)]*)\)", RUN_REPORT.read_text(), re.MULTILINE)
    assert m, "run-report.sh must define COMMANDS=(...)"
    return set(m[1].split())


def test_both_agents_exist() -> None:
    assert [f.stem for f in AGENT_FILES] == ["etf-analyst", "etf-report-verifier"]


@pytest.mark.parametrize("agent", AGENT_FILES, ids=lambda p: p.stem)
def test_agent_name_matches_its_file(agent: Path) -> None:
    assert f"\nname: {agent.stem}\n" in agent.read_text()


@pytest.mark.parametrize("source", [*AGENT_FILES, RUN_REPORT], ids=lambda p: p.name)
def test_every_command_referenced_is_a_declared_console_script(source: Path) -> None:
    referenced = set(VENV_COMMAND.findall(source.read_text()))
    assert referenced <= declared_commands(), "add it to [project.scripts] or fix the reference"


def test_run_report_allows_exactly_the_declared_commands() -> None:
    assert allowed_commands() == declared_commands()


def test_every_declared_command_is_documented_for_an_agent() -> None:
    documented = set().union(*(VENV_COMMAND.findall(f.read_text()) for f in AGENT_FILES))
    assert documented == declared_commands()


@pytest.mark.parametrize("agent", AGENT_FILES, ids=lambda p: p.stem)
def test_every_repo_path_an_agent_mentions_exists(agent: Path) -> None:
    for rel in REPO_PATH.findall(agent.read_text()):
        rel = rel.rstrip(".")
        if rel.startswith((".venv/", "reports/")) or rel in ("reports", ""):
            continue  # created at install / run time; commands are checked above
        assert (paths.ROOT / rel).exists(), f"{agent.name} mentions ~/Dev/etf-analyst/{rel}"


def test_readable_files_in_run_report_exist() -> None:
    for rel in re.findall(r'"Read\(~/Dev/etf-analyst/([^)*]+)\)"', RUN_REPORT.read_text()):
        assert (paths.ROOT / rel).exists(), f"run-report.sh allows reading missing {rel}"
