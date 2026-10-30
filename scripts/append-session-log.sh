#!/usr/bin/env bash
# Appends a structured session log entry to docs/SESSION_LOG.md at session end.
# Invoked by the Claude Code Stop hook (.claude/settings.json).
# The entry is auto-generated from git state and test results.
# Review and complete the "Done" section before committing.

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
LOG_FILE="$REPO_ROOT/docs/SESSION_LOG.md"
TODAY="$(date '+%Y-%m-%d')"
BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

# Recent commits since yesterday (or last 10 if none today)
RECENT_COMMITS="$(git -C "$REPO_ROOT" log --oneline --since="24 hours ago" 2>/dev/null || echo "(no commits in last 24h)")"
if [ -z "$RECENT_COMMITS" ]; then
  RECENT_COMMITS="$(git -C "$REPO_ROOT" log --oneline -10 2>/dev/null || echo "(no commits)")"
fi

# Current test count (unit + property)
TEST_COUNT="$(cd "$REPO_ROOT" && PYTHONPATH=backend python3 -m pytest backend/tests/unit/ backend/tests/property/ --collect-only -q 2>/dev/null | tail -1 || echo "unknown")"

# Last SESSION_LOG entry date (for deduplication)
LAST_ENTRY_DATE="$(grep -m1 '^## [0-9]' "$LOG_FILE" 2>/dev/null | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' || echo "none")"

# Skip if an entry already exists for today
if [ "$LAST_ENTRY_DATE" = "$TODAY" ]; then
  echo "append-session-log.sh: entry for $TODAY already exists, skipping."
  exit 0
fi

# Run invariant property tests and capture result
INVARIANT_RESULT="unknown"
if cd "$REPO_ROOT" && PYTHONPATH=backend python3 -m pytest backend/tests/property/ -q --tb=short > /tmp/invariant_results.txt 2>&1; then
  INVARIANT_RESULT="PASS ($(tail -1 /tmp/invariant_results.txt))"
else
  INVARIANT_RESULT="FAIL — see /tmp/invariant_results.txt"
fi

ENTRY="---

## $TODAY — Auto-generated session entry (REVIEW BEFORE COMMITTING)

**Phase:** $(grep -m1 'Current phase:' "$REPO_ROOT/docs/PROJECT_STATE.md" | sed 's/.*Current phase: //')
**Branch:** \`$BRANCH\`

### Invariant checks (auto-run by Stop hook)

\`\`\`
$INVARIANT_RESULT
\`\`\`

### Test count at session end

\`\`\`
$TEST_COUNT
\`\`\`

### Commits this session

\`\`\`
$RECENT_COMMITS
\`\`\`

### Done

<!-- Fill in manually or let the next session prepend a proper entry above this one. -->
<!-- This auto-entry is a fallback, not a replacement for agent-authored entries. -->

"

# Prepend the entry after the header separator (line 7, after the first ---)
HEADER_END=$(grep -n '^---$' "$LOG_FILE" | head -1 | cut -d: -f1)
{
  head -n "$HEADER_END" "$LOG_FILE"
  echo ""
  printf '%s' "$ENTRY"
  tail -n +"$((HEADER_END + 1))" "$LOG_FILE"
} > /tmp/session_log_tmp.md

mv /tmp/session_log_tmp.md "$LOG_FILE"
echo "append-session-log.sh: appended auto-entry for $TODAY to docs/SESSION_LOG.md"
