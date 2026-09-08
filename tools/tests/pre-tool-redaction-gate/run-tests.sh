#!/usr/bin/env bash
# Regression suite — hooks/pre-tool-redaction-gate.py (the redaction gate on
# every outbound action carrying prose).
#
# Asserts:
#   P1  Bash command without a prose verb       → exit 0, silent, checker not needed
#   P2  git commit -m with an em dash, default  → exit 0, stderr names EM_DASH + line
#   P3  REDACTION_STOP_BLOCK=on                 → exit 2, stderr names the finding
#   P4  .redaction-gate.json marker in cwd      → exit 2 (marker opt-in, no env)
#   P5  gh pr comment --body-file <file>        → the file's prose is scanned;
#                                                 a missing file is silent
#   P6  heredoc commit message                  → scanned (BANNED_WORD found)
#   P7  git commit -n -m: -n is --no-verify     → -m still parsed (finding found)
#   P8  mcp__github__* body                     → same contract; an unrelated
#                                                 tool (Read) is silent
#   P9  malformed payloads                      → exit 0, silent (fail-open)
#   P10 REDACTION_STOP_WARN=off                 → silent
#   P11 clean commit message                    → exit 0, silent
#   P12 module absent (hook copied alone)       → exit 0, never exit 2
#
# Self-contained: throwaway tmpdir, no writes to the working tree.
set -uo pipefail   # NOT -e: exit codes are the assertions.

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SUITE_DIR/../../.." && pwd)"
HOOK="$REPO_ROOT/hooks/pre-tool-redaction-gate.py"

PASS=0; FAIL=0
run_case() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || { echo "FAIL: could not cd to temp dir" >&2; exit 1; }
git init -q .

# bash_payload <command>   |  mcp_payload <tool_name> <body>  |  raw_payload <json>
bash_payload() {
  python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":sys.argv[2],"tool_input":{"command":sys.argv[1]}}))' "$1" "$tmp"
}
mcp_payload() {
  python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":sys.argv[1],"tool_input":{"body":sys.argv[2]}}))' "$1" "$2"
}
# run_hook <payload> [env assignments...] → sets ERR (stderr), OUT (stdout), RC
run_hook() {
  OUT=$(printf '%s' "$1" | env -u REDACTION_STOP_BLOCK -u REDACTION_STOP_WARN "${@:2}" python3 "$HOOK" 2>"$tmp/err"); RC=$?
  ERR=$(cat "$tmp/err")
}

DASH_MSG=$'git commit -m "The build is fast \xe2\x80\x94 very fast."'

# P1 no prose verb: nothing to scan
run_hook "$(bash_payload 'ls -la && echo "git commit is a verb only in a command position"')" env REDACTION_STOP_BLOCK=on
run_case "P1 no prose verb: exit 0" test "$RC" -eq 0
run_case "P1 no prose verb: silent" test -z "$ERR" -a -z "$OUT"

# P2 default tier warns, action proceeds
run_hook "$(bash_payload "$DASH_MSG")"
run_case "P2 em dash default: exit 0" test "$RC" -eq 0
run_case "P2 em dash default: stderr names EM_DASH" grep -q "EM_DASH" <<<"$ERR"
run_case "P2 em dash default: stderr quotes the line number" grep -q "line 1 EM_DASH" <<<"$ERR"
run_case "P2 em dash default: no stdout" test -z "$OUT"

# P3 env opt-in refuses the action
run_hook "$(bash_payload "$DASH_MSG")" env REDACTION_STOP_BLOCK=on
run_case "P3 block env: exit 2" test "$RC" -eq 2
run_case "P3 block env: reason names EM_DASH" grep -q "EM_DASH" <<<"$ERR"
run_case "P3 block env: reason hands back the skill eval" grep -q "redaction.md" <<<"$ERR"

# P4 marker opt-in (no env)
echo '{}' > .redaction-gate.json
run_hook "$(bash_payload "$DASH_MSG")"
run_case "P4 marker: exit 2" test "$RC" -eq 2
rm -f .redaction-gate.json

# P5 --body-file is read relative to the event cwd; a missing file is silent
printf 'We leverage a robust pipeline.\n' > notes.md
run_hook "$(bash_payload 'gh pr comment 12 --body-file notes.md')" env REDACTION_STOP_BLOCK=on
run_case "P5 body file scanned: exit 2" test "$RC" -eq 2
run_case "P5 body file scanned: BANNED_WORD named" grep -q "BANNED_WORD" <<<"$ERR"
run_hook "$(bash_payload 'gh pr comment 12 --body-file missing.md')" env REDACTION_STOP_BLOCK=on
run_case "P5 missing body file: exit 0, silent" test "$RC" -eq 0 -a -z "$ERR"

# P6 heredoc commit message: the body lives inside the quoted -m token
HEREDOC=$'git commit -m "$(cat <<\'EOF\'\nfeat(x): delve into the parser\n\nCo-Authored-By: t\nEOF\n)"'
run_hook "$(bash_payload "$HEREDOC")" env REDACTION_STOP_BLOCK=on
run_case "P6 heredoc commit message: exit 2" test "$RC" -eq 2
run_case "P6 heredoc commit message: BANNED_WORD named" grep -q "BANNED_WORD" <<<"$ERR"

# P7 -n is --no-verify for git commit (no argument): -m must still be parsed
run_hook "$(bash_payload 'git commit -n -m "We leverage it."')" env REDACTION_STOP_BLOCK=on
run_case "P7 git commit -n -m: finding found" grep -q "BANNED_WORD" <<<"$ERR"

# P8 GitHub MCP tools carry prose in tool_input.body; other tools are silent
run_hook "$(mcp_payload mcp__github__add_issue_comment 'Great question! We leverage it.')" env REDACTION_STOP_BLOCK=on
run_case "P8 mcp body: exit 2" test "$RC" -eq 2
run_case "P8 mcp body: PUFFERY named" grep -q "PUFFERY" <<<"$ERR"
run_hook "$(mcp_payload Read 'We leverage it.')" env REDACTION_STOP_BLOCK=on
run_case "P8 unrelated tool: exit 0, silent" test "$RC" -eq 0 -a -z "$ERR"

# P9 fail-open on bad payloads
for p in '[]' '42' 'null' '{"tool_name":"Bash","tool_input":7}' '{"tool_name":"Bash","tool_input":{"command":3}}' 'not json' ''; do
  run_hook "$p" env REDACTION_STOP_BLOCK=on
  run_case "P9 payload '$p': exit 0, silent" test "$RC" -eq 0 -a -z "$OUT" -a -z "$ERR"
done

# P10 warn silenced
run_hook "$(bash_payload "$DASH_MSG")" env REDACTION_STOP_WARN=off
run_case "P10 WARN=off: exit 0, silent" test "$RC" -eq 0 -a -z "$ERR"

# P11 clean message
run_hook "$(bash_payload 'git commit -m "fix(hooks): read the body file relative to cwd"')" env REDACTION_STOP_BLOCK=on
run_case "P11 clean commit message: exit 0, silent" test "$RC" -eq 0 -a -z "$ERR"

# P12 module absent → fail open. Copy the hook to a tree with no tools/ and no
# CLAUDE_PLUGIN_ROOT so _load_gate() finds nothing.
mkdir -p isolated/hooks && cp "$HOOK" isolated/hooks/
OUT=$(printf '%s' "$(bash_payload "$DASH_MSG")" | env -u CLAUDE_PLUGIN_ROOT REDACTION_STOP_BLOCK=on python3 isolated/hooks/pre-tool-redaction-gate.py 2>"$tmp/err"); RC=$?
run_case "P12 module absent: exit 0, no block" test "$RC" -eq 0

echo "----------------------------------------"
echo "pre-tool-redaction-gate suite: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
