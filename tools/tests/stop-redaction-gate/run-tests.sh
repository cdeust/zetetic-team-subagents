#!/usr/bin/env bash
# Regression suite — hooks/stop-redaction-gate.py (the redaction gate on every
# returned message).
#
# Asserts:
#   H1  clean message                       → exit 0, no stdout, no stderr
#   H2  em dash, default tier               → exit 0, NO block JSON, stderr names EM_DASH + line
#   H3  REDACTION_STOP_BLOCK=on             → stdout {"decision":"block"} naming the finding
#   H4  .redaction-gate.json marker in cwd  → block (marker opt-in, no env)
#   H5  stop_hook_active + block opt-in     → NOT blocked (loop-safe), still warned
#   H6  non-dict / malformed payloads       → exit 0, silent (fail-open)
#   H7  no last_assistant_message           → falls back to the transcript's final
#                                             assistant text (multi-row message)
#   H8  REDACTION_STOP_WARN=off             → silent
#   H9  pattern only inside a fenced block  → silent (checker fence rule reused)
#   H10 SubagentStop payload                → same contract as Stop (block works)
#   H11 checker absent                      → exit 0, silent (fail-open)
#
# Self-contained: throwaway tmpdir, no writes to the working tree.
set -uo pipefail   # NOT -e: hooks are expected to exit 0 in every arm.

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SUITE_DIR/../../.." && pwd)"
HOOK="$REPO_ROOT/hooks/stop-redaction-gate.py"

PASS=0; FAIL=0
run_case() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || { echo "FAIL: could not cd to temp dir" >&2; exit 1; }
git init -q .

# payload <message> [extra-json-fields]
payload() {
  python3 -c 'import json,sys; d={"session_id":"t","hook_event_name":"Stop","last_assistant_message":sys.argv[1]}; d.update(json.loads(sys.argv[2]) if len(sys.argv)>2 else {}); print(json.dumps(d))' "$@"
}
# run_hook <payload> → sets OUT (stdout), ERR (stderr), RC
run_hook() {
  OUT=$(printf '%s' "$1" | env -u REDACTION_STOP_BLOCK -u REDACTION_STOP_WARN "${@:2}" python3 "$HOOK" 2>"$tmp/err"); RC=$?
  ERR=$(cat "$tmp/err")
}

DASH=$'The build is fast \xe2\x80\x94 very fast.'

# H1 clean
run_hook "$(payload 'The suite passed. Two files changed.')"
run_case "H1 clean message: exit 0" test "$RC" -eq 0
run_case "H1 clean message: no stdout" test -z "$OUT"
run_case "H1 clean message: no stderr" test -z "$ERR"

# H2 default tier warns, never blocks
run_hook "$(payload "$DASH")"
run_case "H2 em dash default: exit 0" test "$RC" -eq 0
run_case "H2 em dash default: no block JSON" test -z "$OUT"
run_case "H2 em dash default: stderr names EM_DASH" grep -q "EM_DASH" <<<"$ERR"
run_case "H2 em dash default: stderr quotes the line number" grep -q "line 1 EM_DASH" <<<"$ERR"

# H3 env opt-in blocks
run_hook "$(payload "$DASH")" env REDACTION_STOP_BLOCK=on
run_case "H3 block env: decision block" grep -q '"decision": *"block"' <<<"$OUT"
run_case "H3 block env: reason names EM_DASH" grep -q "EM_DASH" <<<"$OUT"
run_case "H3 block env: reason hands back the skill eval" grep -q "redaction.md" <<<"$OUT"
run_case "H3 block env: exit 0" test "$RC" -eq 0

# H4 marker opt-in blocks (no env)
echo '{}' > .redaction-gate.json
run_hook "$(payload "$DASH")"
run_case "H4 marker: decision block" grep -q '"decision": *"block"' <<<"$OUT"
rm -f .redaction-gate.json

# H5 loop-safety: stop_hook_active never re-blocks, still reports
run_hook "$(payload "$DASH" '{"stop_hook_active":true}')" env REDACTION_STOP_BLOCK=on
run_case "H5 stop_hook_active: no block" test -z "$OUT"
run_case "H5 stop_hook_active: residual finding still warned" grep -q "EM_DASH" <<<"$ERR"

# H6 fail-open on bad payloads
for p in '[]' '42' 'null' '{"last_assistant_message": 7}' 'not json' ''; do
  run_hook "$p" env REDACTION_STOP_BLOCK=on
  run_case "H6 payload '$p': exit 0, silent" test "$RC" -eq 0 -a -z "$OUT" -a -z "$ERR"
done

# H7 transcript fallback: the final message spans two rows sharing message.id;
# an EARLIER message (other id) carries a pattern that must NOT be scanned.
cat > transcript.jsonl <<'EOF'
{"type":"user","message":{"role":"user","content":"hi"}}
{"type":"assistant","message":{"id":"msg_old","role":"assistant","content":[{"type":"text","text":"Studies show this wins."}]}}
{"type":"user","message":{"role":"user","content":"go on"}}
{"type":"assistant","message":{"id":"msg_new","role":"assistant","content":[{"type":"text","text":"First half is clean."}]}}
{"type":"assistant","message":{"id":"msg_new","role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}}]}}
{"type":"assistant","message":{"id":"msg_new","role":"assistant","content":[{"type":"text","text":"We leverage the runtime here."}]}}
EOF
run_hook "$(payload '' "{\"transcript_path\":\"$tmp/transcript.jsonl\"}")" env REDACTION_STOP_BLOCK=on
run_case "H7 transcript fallback: last message's second text block scanned" grep -q "BANNED_WORD" <<<"$OUT"
run_case "H7 transcript fallback: earlier message NOT scanned" bash -c '! grep -q WEASEL <<<"$1"' _ "$OUT"
run_case "H7 transcript fallback: line number is within the final message" grep -q "line 2 BANNED_WORD" <<<"$OUT"

# H8 warn silenced
run_hook "$(payload "$DASH")" env REDACTION_STOP_WARN=off
run_case "H8 WARN=off: silent" test -z "$OUT" -a -z "$ERR"

# H9 fenced code is not copy
FENCED=$'Run this:\n```\necho "studies show — leverage"\n```\nDone.'
run_hook "$(payload "$FENCED")" env REDACTION_STOP_BLOCK=on
run_case "H9 fenced block ignored" test -z "$OUT" -a -z "$ERR"

# H10 SubagentStop uses the same contract
run_hook "$(payload "$DASH" '{"hook_event_name":"SubagentStop","agent_id":"a1","agent_type":"paper-writer"}')" env REDACTION_STOP_BLOCK=on
run_case "H10 SubagentStop: decision block" grep -q '"decision": *"block"' <<<"$OUT"

# H11 checker absent → fail open. Copy the hook to a tree with no tools/ and
# no CLAUDE_PLUGIN_ROOT so resolve_checker() finds nothing.
mkdir -p isolated/hooks && cp "$HOOK" isolated/hooks/
OUT=$(printf '%s' "$(payload "$DASH")" | env -u CLAUDE_PLUGIN_ROOT REDACTION_STOP_BLOCK=on python3 isolated/hooks/stop-redaction-gate.py 2>"$tmp/err"); RC=$?
run_case "H11 checker absent: exit 0, no block" test "$RC" -eq 0 -a -z "$OUT"

echo "----------------------------------------"
echo "stop-redaction-gate suite: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
