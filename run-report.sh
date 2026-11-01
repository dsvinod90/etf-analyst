#!/bin/bash
# Run the etf-analyst agent headless, verify its report, publish the PDF, and show a Mac notification.
# Run by the daily launchd job; also run it by hand any time:  ./run-report.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
REPORTS="$REPO/reports"
LOGS="$REPORTS/logs"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$LOGS"
LOG="$LOGS/run-$(date +%Y-%m-%d-%H%M).log"
START_MARKER="$LOGS/.run-start"
touch "$START_MARKER"

# notify SUBTITLE MESSAGE FILE -- clicking the notification opens FILE.
# Text and paths are passed as arguments, never spliced into shell or AppleScript code.
notify() {
  local url
  url=$(python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve().as_uri())' "$3")
  terminal-notifier -title "ETF Analyst" -subtitle "$1" -message "$2" \
    -open "$url" -group etf-analyst -sound default >/dev/null 2>&1 \
    || osascript -e 'on run argv' \
                 -e 'display notification (item 2 of argv) with title "ETF Analyst" subtitle (item 1 of argv)' \
                 -e 'end run' "$1" "$2" 2>/dev/null \
    || true
}

# What the unattended agents may do without asking. Anything else is denied.
# The agents read web search results, which could contain injected instructions, so:
#  - Bash may run only this project's own scripts (no `python3 -c`, no other commands);
#    the scripts themselves refuse file paths outside reports/
#  - files may be read only inside the repo and written only under reports/
#  - WebFetch is removed entirely, so nothing can be sent out encoded in a URL;
#    research uses WebSearch results only
SCRIPTS=(fetch_etf_data.py make_pdf.py verify_tables.py calc.py)
ALLOWED=(WebSearch "Read(~/Dev/etf-analyst/**)" "Edit(~/Dev/etf-analyst/reports/**)")
for s in "${SCRIPTS[@]}"; do
  ALLOWED+=("Bash(python3 ~/Dev/etf-analyst/$s:*)" "Bash(python3 $REPO/$s:*)")
done
DISALLOWED=(WebFetch)

cd "$REPO" || exit 1
echo "== etf-analyst run started $(date)" >"$LOG"

claude -p "Run your full workflow: screen the US ETF market with the latest prices, rank ETFs for long-term and short-term investing with explanations, and publish the report as a PDF per Step 5. Return the PDF path first, then the full report." \
  --agent etf-analyst \
  --allowedTools "${ALLOWED[@]}" --disallowedTools "${DISALLOWED[@]}" \
  >>"$LOG" 2>&1
STATUS=$?

# newest PDF written during this run (only names the analyst itself produces)
PDF=$(find "$REPORTS" -maxdepth 1 -newer "$START_MARKER" -print 2>/dev/null \
      | grep -E '/etf-report-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[0-9]{4})?\.pdf$' | sort | tail -1)
echo "== agent finished $(date), exit $STATUS, pdf: ${PDF:-none}" >>"$LOG"

if [[ $STATUS -ne 0 || -z "$PDF" ]]; then
  notify "Run failed" "Click to view the log" "$LOG"
  echo "etf-analyst run failed; see $LOG" >&2
  exit 1
fi

# independent check of the report: numbers vs raw data, news claims, reasoning
MD="${PDF%.pdf}.md"
echo "== verifier started $(date)" >>"$LOG"
VERDICT=$(claude -p "Verify the ETF report at $MD and publish the verification PDF per Step 8." \
  --agent etf-report-verifier \
  --allowedTools "${ALLOWED[@]}" --disallowedTools "${DISALLOWED[@]}" \
  2>>"$LOG")
echo "$VERDICT" >>"$LOG"
SCORE=$(grep -oE 'CONFIDENCE: [0-9]+/100' <<<"$VERDICT" | tail -1 | grep -oE '[0-9]+/100')
echo "== verifier finished $(date), confidence: ${SCORE:-unknown}" >>"$LOG"

VERIFICATION="${MD%.md}-verification.md"
if [[ -n "$SCORE" && -f "$VERIFICATION" ]]; then
  # rebuild the report PDF with a confidence badge and the verification as an appendix
  python3 "$REPO/make_pdf.py" "$MD" --verification "$VERIFICATION" -o "$PDF" >>"$LOG" 2>&1 \
    || echo "== could not add verification to the report PDF" >>"$LOG"
fi

if [[ -n "$SCORE" ]]; then
  notify "Report ready · Confidence $SCORE" "Click to open $(basename "$PDF")" "$PDF"
else
  notify "Report ready · verification failed" "Click to open $(basename "$PDF")" "$PDF"
fi
echo "$PDF"
