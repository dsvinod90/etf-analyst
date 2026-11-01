# CLAUDE.md

Rules for working on this repo. They follow standard Python practice (PEP 8, PEP 257, PEP 484,
strict typing, tested code) plus this project's security constraints. `make check` enforces most
of them; the rest are on you.

## Project

Two Claude Code agents plus the `etf_analyst` package, which screens US ETFs, verifies reports
and renders PDFs. A launchd job runs `run-report.sh` daily at 8 AM.

```
run-report.sh ─► etf-analyst agent ─► etf-screen --save ─► reports/data/*.json
                       │ writes reports/etf-report-<date>.md ─► etf-pdf ─► .pdf
              ─► etf-report-verifier agent ─► etf-verify, etf-calc ─► *-verification.md
              ─► score cap (code) ─► etf-pdf --verification ─► Mac notification
```

`src/etf_analyst/` (src layout, installed editable into `.venv` by `make venv`):

| Module | Responsibility | Depends on |
|---|---|---|
| `metrics` | Pure price-series math (`pct`, `sma`, `rsi`, `volatility`, `max_drawdown`, `cagr`) | — |
| `records` | Shared record types (`ETF`) | — |
| `paths` | Project directories and `confine()`, the one guard for untrusted paths | — |
| `yahoo` | Yahoo Finance client: `get_json`, `discover`, `analyze` | metrics, records |
| `scoring` | z-scores, weights (`LONG_TERM`, `SHORT_TERM`), `score`, ranks | records |
| `screen` | `etf-screen` CLI; `run_screen()` for in-process use | yahoo, scoring, paths |
| `verify` | `etf-verify` CLI; `check_report()` | screen, paths |
| `safe_calc` | `etf-calc` CLI; `evaluate()`, the AST-allowlist calculator | — |
| `sanitize` | Allowlist HTML sanitizer | — |
| `pdf` | `etf-pdf` CLI: Markdown → sanitized HTML → PDF; styles in `assets/report.css` | sanitize, paths |

Other files: `run-report.sh` runs both agents and **owns their tool permissions**;
`.claude/agents/*.md` are the agent instructions (symlinked into `~/.claude/agents/`);
`tests/` mirrors the modules (`test_<module>.py`), with shared builders in `tests/helpers.py`
and the `tmp_reports` fixture in `tests/conftest.py`.

**Core design rule: code computes every number; agents only research, judge and explain.**
Never move arithmetic or data handling into agent instructions.

**Module rules:**
- Dependencies point one way, as in the table; no import cycles. Pure logic (`metrics`,
  `scoring`, `safe_calc`, `sanitize`) does no I/O, so it's trivially testable.
- CLI modules keep `main()` thin: parse arguments, call a library function
  (`run_screen`, `check_report`, `build_html`), print. Library functions return values and
  raise exceptions (`paths.PathError`, `ValueError`); only `main()` turns them into `sys.exit`.
- Reach shared state through the module (`paths.REPORTS_DIR`), not `from paths import
  REPORTS_DIR`, so tests can monkeypatch it.
- A new command needs: a `main(argv)` in its module, an entry in `[project.scripts]`, an
  allow rule in `run-report.sh` (`COMMANDS`), and the path in the agent instructions.

## Commands

```sh
make venv        # create .venv with the pinned dev tools (requirements-dev.txt)
make format      # ruff format + safe auto-fixes
make check       # lint + typecheck + tests: must pass before every commit (CI runs the same)
make lint        # ruff check, ruff format --check, shellcheck run-report.sh
make typecheck   # mypy --strict
make test        # pytest with coverage (fails under 80%)

.venv/bin/pytest tests/test_safe_calc.py -k round   # run a subset
.venv/bin/etf-screen VOO --top 1                     # try a command
./run-report.sh                                 # full pipeline, ~7-9 min, uses Claude
```

Always use the tools from `.venv/`, not global installs, so versions match CI.

## Python standards

### Runtime
- **Python 3.12+. Standard library only at runtime.** The only optional package is `markdown`
  (PDF fallback when pandoc is missing). Adding a runtime dependency needs an explicit decision
  from the user; dev-only tools go in `requirements-dev.txt`, pinned to exact versions.
- Code lives in the `src/etf_analyst` package (src layout). Agents and `run-report.sh` call its
  console scripts from `.venv/bin/`; renaming a command means updating `pyproject.toml`,
  `run-report.sh` and the agent files together.

### Formatting and linting
- **ruff** is the single source of truth for style and imports: line length 100, rules in
  `pyproject.toml` (pycodestyle, pyflakes, isort, naming, pyupgrade, bugbear, bandit,
  pydocstyle, annotations, …). Run `make format`; don't hand-format.
- Don't add `# noqa` or `# type: ignore` to get a check to pass. If a suppression is really
  justified, scope it to one rule and give the reason on the same line, e.g.
  `# noqa: S310 -- URL host checked above`. Reviewers should be able to verify the reason.
- Don't loosen `pyproject.toml` rules to make code pass. Fix the code.

### Naming and structure
- `snake_case` functions and variables, `CapWords` classes, `UPPER_CASE` module constants
  declared at the top of the module. Prefix module-private helpers with `_`.
- **No magic numbers:** name them (`REQUEST_TIMEOUT = 20  # seconds`) and give units in a comment.
- Functions do one thing and stay short (aim for < 40 lines). Extract pure logic from I/O so it
  can be unit-tested; put pure numeric helpers in `metrics.py`.
- Prefer `pathlib.Path`, f-strings, comprehensions, `dataclass` for records with fixed fields,
  `frozenset`/`tuple` for constants. Don't assign lambdas to names; use `def`.
- Every script has `main(argv: Sequence[str] | None = None) -> None` and an
  `if __name__ == "__main__":` guard. Parse arguments with `argparse` in `parse_args(argv)`,
  so `main` can be called from tests.

### Types
- **Every function and method is fully annotated; `mypy --strict` must pass.**
- Use built-in generics and unions (`list[str]`, `dict[str, float]`, `X | None`), and
  `collections.abc` (`Sequence`, `Callable`, `Iterator`) for parameters. Accept the most general
  type you need, and return concrete types.
- `Any` is allowed only for genuinely untyped data (parsed JSON), behind a named alias
  (`ETF = dict[str, Any]`). Don't let it leak into return types of typed helpers.

### Documentation
- Every module starts with a docstring: what it does, then a `Usage:` section.
- Public functions, classes and methods have **Google-style docstrings** (PEP 257): a one-line
  summary in the imperative mood, then **why** if it isn't obvious, units (%, seconds), what
  `None` means, and `Args:` / `Returns:` / `Raises:` when not self-evident. Include examples
  for anything non-obvious; `safe_calc.evaluate` is the model.
- Comments explain *why*, never *what* the next line does.
- Update `README.md` when commands, files or behavior change, and this file when conventions do.

### Errors and data
- **Catch specific exceptions only.** Batch work (one ticker of many) catches the specific
  failure types (`FETCH_ERRORS`) and records them in the output (`errors[ticker] = str(e)`);
  never `except Exception`, and never swallow an error silently.
- CLI input errors exit with a clear message (`sys.exit("report must be a .md file inside …")`),
  not a traceback.
- Missing values are `None` end to end. Never substitute 0 or a guess.
- Percentages are stored as percent numbers (`12.34` = 12.34%), rounded to 2 decimals (RSI: 1).
- Machine-readable output goes to **stdout as JSON**; diagnostics go to stderr. Agents and
  `run-report.sh` parse stdout, so never print anything else there.
- Network calls: fixed https hosts only (checked in code), a timeout, and a `User-Agent`.

### Subprocesses
- `subprocess.run([...], check=True, capture_output=True)` with an argument list.
  **Never `shell=True`**, and never build command strings from data.

## Security: non-negotiable

The agents read web search results, so **anything an agent writes (reports, verification files,
arguments it passes to scripts) is untrusted input.** Every rule here came from a real code
scanning alert; each has a test in `tests/`. Don't regress them.

- **No `eval`, `exec`, `compile` on untrusted text, `pickle`, or `yaml.load`.** Arithmetic goes
  through `safe_calc.evaluate`, an AST allowlist. Extend it only by allowing more node types, and keep
  its limits (`LIMIT`, the pre-computation power check, `round()` digits 0-10).
- **Confine paths with `paths.confine`.** Every command an agent can call refuses paths outside
  `reports/`, including paths read from file contents (the report's `Data file:` line). Don't
  write a second path check; use this one.
- **Validate and encode external identifiers** (`VALID_TICKER`, `urllib.parse.quote`).
- **HTML:** rendered Markdown always passes through `sanitize.sanitize` (a tag and attribute
  allowlist), and the page keeps its Content-Security-Policy. Our own markup (the badge) is added
  *after* sanitizing, from `html.escape`d values.
- **Shell and AppleScript:** pass values as arguments (`osascript … on run argv`,
  `terminal-notifier -open <file:// URL>`), never by splicing them into code.
- **Agent permissions** (`ALLOWED` / `DISALLOWED` in `run-report.sh`) stay minimal: Bash only
  for the four `etf-*` commands in `.venv/bin/`, Read/Edit only under `reports/` (plus reading
  `metrics.py` for its docstrings), no WebFetch. Never add broad rules such as
  `Bash(python3:*)`, `Bash(cat:*)` or `Read(~/**)`.
- **The confidence score is capped in code** when table accuracy is below 98%; don't let the
  verifier's own text be the only source of the score.
- Never commit `reports/`, `.venv/`, secrets, tokens or editor swap files.

## Testing

- **Every change to logic ships with tests**, and every bug or security fix with a test that
  reproduces it (e.g. `round(1, -10**9)` is refused in under 0.5 s).
- Use pytest: plain `assert`, `@pytest.mark.parametrize` for input tables, the `tmp_path`,
  `monkeypatch` and `capsys` fixtures. One behavior per test, named for that behavior
  (`test_cagr_returns_none_without_enough_history`).
- **Tests never call Yahoo Finance or any other external service: mock every external call.**
  Tests must be fast, deterministic and work offline (CI included), and real API responses
  change daily.
  - Mock at the boundary: `monkeypatch.setattr(yahoo, "get_json", fake)`, returning fixed data
    built with `tests/helpers.py` (`chart_response`, `make_etf`). For code that calls the
    screen in-process, mock `screen.run_screen` / `verify.run_screen` instead.
  - This is **enforced**: the autouse `_no_network` fixture in `tests/conftest.py` blocks
    sockets and DNS, so a missing mock fails with `NetworkBlockedError` instead of quietly
    calling Yahoo. Don't disable or work around it. If code needs a new external call, add a
    function for it that tests can monkeypatch.
- **Tests never launch Chrome or write to the real `reports/`.** Mock `pdf.print_pdf`, and use
  the `tmp_reports` fixture, which points `paths.REPORTS_DIR` / `paths.DATA_DIR` at a temp dir.
- Coverage must stay at or above 80% (enforced); new code should be fully covered.

## Workflow

- Before committing: `make check` passes. For changes to commands the agents call, also run
  `./run-report.sh` once and confirm the log ends with a confidence score.
- After changing `pyproject.toml` (dependencies, commands), rerun `make venv`.
- **Never edit `run-report.sh` while the job is running**
  (`launchctl print gui/$(id -u)/com.dsvinod90.etf-analyst | grep state`): bash reads the
  script as it executes.
- Keep commits focused, with an imperative subject line and a body explaining why.
