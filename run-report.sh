#!/bin/bash
# Run the etf-analyst agent headless, publish the PDF, and show a Mac notification.
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

# notify SUBTITLE MESSAGE FILE -- clicking the notification opens FILE
# (terminal-notifier; falls back to a plain, non-clickable osascript notification)
notify() {
  terminal-notifier -title "ETF Analyst" -subtitle "$1" -message "$2" \
    -execute "open '$3'" -group etf-analyst -sound default >/dev/null 2>&1 \
    || osascript -e "display notification \"$2\" with title \"ETF Analyst\" subtitle \"$1\"" 2>/dev/null \
    || true
}

cd "$REPO" || exit 1
echo "== etf-analyst run started $(date)" >"$LOG"

claude -p "Run your full workflow: screen the US ETF market with the latest prices, rank ETFs for long-term and short-term investing with explanations, and publish the report as a PDF per Step 5. Return the PDF path first, then the full report." \
  --agent etf-analyst \
  --allowedTools "Bash(python3:*)" "Bash(ls:*)" "Bash(date:*)" Read Write WebSearch WebFetch \
  >>"$LOG" 2>&1
STATUS=$?

# newest PDF written during this run
PDF=$(find "$REPORTS" -maxdepth 1 -name 'etf-report-*.pdf' -newer "$START_MARKER" -print 2>/dev/null | sort | tail -1)
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
  --allowedTools "Bash(python3:*)" "Bash(ls:*)" Read Write WebSearch WebFetch \
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
