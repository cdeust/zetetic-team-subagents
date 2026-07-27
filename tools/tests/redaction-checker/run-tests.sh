#!/usr/bin/env bash
# Regression suite — redaction-checker.sh (issue #43).
#
# Asserts:
#   T1 clean copy file → no findings, exit 0
#   T2 em dash in docs copy → EM_DASH finding, exit 0 (warn-only default)
#   T3 banned word → BANNED_WORD finding
#   T4 weasel phrase → WEASEL finding
#   T5 pattern inside a fenced code block → NOT flagged
#   T6 excluded path (skills/) → NOT scanned even when passed via --files
#   T7 strict profile (.zetetic.conf ZETETIC_PROFILE=strict) → findings exit 1
#   T8 usage error (no mode) → exit 2
set -uo pipefail

CHECKER="$(cd "$(dirname "$0")/../.." && pwd)/redaction-checker.sh"
PASS=0; FAIL=0

run_case() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || { echo "FAIL: could not cd to temp dir" >&2; exit 1; }
git init -q .
mkdir -p docs skills/writing

# T1 clean
printf 'This page explains the build. It cites Martin (2017), chapter 5.\n' > docs/clean.md
out=$("$CHECKER" --files docs/clean.md); rc=$?
run_case "T1 clean file: no findings, exit 0" test "$rc" -eq 0 -a -z "$out"

# T2 em dash (warn-only: exit 0 but finding printed)
printf 'The build is fast \xe2\x80\x94 very fast.\n' > docs/dash.md
out=$("$CHECKER" --files docs/dash.md); rc=$?
run_case "T2 em dash flagged" grep -q "EM_DASH" <<<"$out"
run_case "T2 em dash warn-only exit 0" test "$rc" -eq 0

# T3 banned word
printf 'We leverage a robust pipeline.\n' > docs/banned.md
out=$("$CHECKER" --files docs/banned.md)
run_case "T3 banned word flagged" grep -q "BANNED_WORD" <<<"$out"

# T4 weasel
printf 'Studies show this approach wins.\n' > docs/weasel.md
out=$("$CHECKER" --files docs/weasel.md)
run_case "T4 weasel flagged" grep -q "WEASEL" <<<"$out"

# T5 fenced code block not flagged
printf '%s\n' 'Real copy line.' '```' 'echo "studies show — leverage"' '```' > docs/fenced.md
out=$("$CHECKER" --files docs/fenced.md)
run_case "T5 fenced block ignored" test -z "$out"

# T6 excluded path not scanned
printf 'delve — studies show\n' > skills/writing/inventory-example.md
out=$("$CHECKER" --files skills/writing/inventory-example.md)
run_case "T6 skills/ path excluded" test -z "$out"

# T7 strict profile blocks
printf 'ZETETIC_PROFILE=strict\n' > .zetetic.conf
"$CHECKER" --files docs/weasel.md >/dev/null 2>&1; rc=$?
run_case "T7 strict profile exits 1" test "$rc" -eq 1
rm -f .zetetic.conf

# T8 usage error
"$CHECKER" >/dev/null 2>&1; rc=$?
run_case "T8 no mode exits 2" test "$rc" -eq 2

# T9 binary contrast / negative listing / dramatic fragment
printf "It's not a cache. It's a memory.\n" > docs/contrast.md
out=$("$CHECKER" --files docs/contrast.md)
run_case "T9 binary contrast flagged" grep -q "CONTRAST" <<<"$out"

# T10 setup patterns (throat-clearing / faux insight / signposting / rhetorical)
printf "What nobody tells you about recall.\n" > docs/setup.md
out=$("$CHECKER" --files docs/setup.md)
run_case "T10 faux-insight setup flagged" grep -q "SETUP" <<<"$out"

# T11 puffery / promotional / copula avoidance / AI artifacts
printf 'The launch marks a pivotal moment. I hope this helps.\n' > docs/puff.md
out=$("$CHECKER" --files docs/puff.md)
run_case "T11 puffery flagged" grep -q "PUFFERY" <<<"$out"

# T12 FP guard: technical prose brushing pattern shapes stays silent
printf 'The store is not thread-safe; callers hold the lock.\nServes requests from the read replica.\n' > docs/fp.md
out=$("$CHECKER" --files docs/fp.md)
run_case "T12 technical prose stays silent" test -z "$out"

# T13 inline code spans are identifiers, not copy (issue #52 follow-on).
# `systems-leverage` is a shipped skill NAME; renaming an artifact to satisfy
# a prose rule is the tail wagging the dog, so spans are stripped before match.
# shellcheck disable=SC2016  # backticks are literal Markdown, not expansion
printf 'The [`systems-leverage`](skills/systems-leverage/SKILL.md) skill routes it.\n' > docs/span.md
out=$("$CHECKER" --files docs/span.md)
run_case "T13 banned word inside an inline code span: NOT flagged" test -z "$out"

# T13b the same word in PROSE is still flagged — proves T13 stripped the span,
# not the detector (a stripping bug that disabled BANNED_WORD would pass T13).
printf 'We leverage the runtime here.\n' > docs/span_prose.md
out=$("$CHECKER" --files docs/span_prose.md)
run_case "T13b same word in prose still flagged" grep -q "BANNED_WORD" <<<"$out"

# T13c link TARGET is an address; link TEXT is copy the reader reads.
printf 'See [the robust guide](docs/robust-utilize-notes.md) for details.\n' > docs/link.md
out=$("$CHECKER" --files docs/link.md)
run_case "T13c banned word in link TEXT is flagged" grep -q "BANNED_WORD" <<<"$out"
run_case "T13c link target is not double-counted" test "$(grep -c BANNED_WORD <<<"$out")" -eq 1

# T14 REGRESSION: word boundaries must not rely on the GNU `\b` extension.
# Matching runs through bash's builtin `=~` (POSIX ERE), where `\b` matches
# nothing and every BANNED_WORD finding silently vanished. Start-of-line is
# the case a naive `[^alnum]` guard also gets wrong.
printf 'Leverage is the first word on this line.\n' > docs/bol.md
out=$("$CHECKER" --files docs/bol.md)
run_case "T14 banned word at start-of-line flagged (no \\b dependency)" grep -q "BANNED_WORD" <<<"$out"
printf 'The word ends the line: utilize\n' > docs/eol.md
out=$("$CHECKER" --files docs/eol.md)
run_case "T14 banned word at end-of-line flagged" grep -q "BANNED_WORD" <<<"$out"

# T15 REGRESSION: a clean file must exit 0. Written as `[[ ]] && { }`, the last
# test in the scan loop returned non-zero on a clean line, which under `set -e`
# aborted the script before its summary — a clean file reported failure.
printf 'A plain sentence with nothing to report.\n' > docs/exit0.md
"$CHECKER" --files docs/exit0.md >/dev/null 2>&1
run_case "T15 clean file exits 0 (set -e trap)" test "$?" -eq 0

# T16 REGRESSION (#64): --full must scan untracked-but-not-ignored copy, not
# only what `git ls-files` reports. A NEW file created but not yet committed was
# invisible to --full, so a local run passed while CI's committed-tree Redaction
# Sweep failed on the same content — a false local pass. The file is deliberately
# NOT git-added; under strict profile a finding must fail (exit 1) and name it.
# Pre-fix (plain `git ls-files`, nothing committed) --full scanned nothing:
# empty output, exit 0 — both assertions below fail, proving the test bites.
printf 'We leverage a robust pipeline.\n' > docs/untracked-64.md
out=$(ZETETIC_PROFILE=strict "$CHECKER" --full 2>&1); rc=$?
run_case "T16 untracked banned file scanned by --full (#64)" grep -q "docs/untracked-64.md" <<<"$out"
run_case "T16 untracked finding fails strict --full, exit 1 (#64)" test "$rc" -eq 1
rm -f docs/untracked-64.md

echo "----------------------------------------"
echo "redaction-checker suite: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
