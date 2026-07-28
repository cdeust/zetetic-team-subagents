#!/usr/bin/env bash
# doc-command-check.sh — every command a document tells a reader to RUN must
# name a file that exists in this repository.
#
# Why (issue #73): CONTRIBUTING.md documented five test scripts, none of which
# existed. `bash tests/run-all.sh`, `bash tests/test-acl.sh` and three siblings
# had been written beside the tree and never re-verified, so a first-time
# contributor's very first command failed with "No such file or directory". The
# list drifted silently because nothing measured it. This measures it.
#
# Scope is deliberately narrow: only tokens in a position where the document is
# instructing the reader to execute something — the argument to bash / sh /
# python3 (with or without -m ... for module form) inside a fenced code block.
# Prose mentions, host paths under ~/.claude, URLs and placeholders are not
# path claims and are not checked. A wider net would flag the README's own
# illustrative output (`retry.py`) and train everyone to ignore the gate, which
# is how the shellcheck warning backlog accumulated (issue #74).
#
# Usage:
#   bash tools/doc-command-check.sh              check the default doc set
#   bash tools/doc-command-check.sh FILE...      check the named documents
#
# Exit: 0 when every runnable command resolves; 1 when any does not; 2 on a
# usage error or when the doc set is empty (an audit of nothing is not a pass).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to repo root $REPO_ROOT" >&2; exit 1; }

# The contributor-facing surface: the documents a newcomer reads before they
# have any way to know a command is stale.
DEFAULT_DOCS=(README.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md)

docs=()
if [[ $# -gt 0 ]]; then
  docs=("$@")
else
  for d in "${DEFAULT_DOCS[@]}"; do
    [[ -f "$d" ]] && docs+=("$d")
  done
  while IFS= read -r d; do
    [[ -n "$d" ]] && docs+=("$d")
  done < <(find docs -maxdepth 1 -name '*.md' 2>/dev/null | sort)
fi

if [[ ${#docs[@]} -eq 0 ]]; then
  echo "FATAL: no documents to check." >&2
  exit 2
fi

# Emit one "doc:line:token" per runnable command argument found in a fenced
# code block. awk tracks fence state so prose is never scanned.
#
# A line beginning with a "$ " shell prompt is a SIMULATED SESSION TRANSCRIPT,
# not an instruction. That is this repo's own convention: README's blocked-commit
# demo and docs/EXAMPLES.md's walkthroughs are prompt-prefixed recordings of a
# session in the reader's own project (they run `python bench/retry_window.py`
# against files this repo does not ship, and should not), while every command a
# contributor is meant to copy and run here is written bare. Checking transcripts
# would report a file this repo never claimed to have.
extract_commands() {
  awk -v doc="$1" '
    /^[[:space:]]*```/ { in_fence = !in_fence; next }
    !in_fence { next }
    /^[[:space:]]*\$[[:space:]]/ { next }   # simulated session transcript
    {
      line = $0
      sub(/#.*$/, "", line)          # strip trailing comments
      n = split(line, tok, /[[:space:]]+/)
      for (i = 1; i <= n; i++) {
        t = tok[i]
        if (t != "bash" && t != "sh" && t != "python3" && t != "python") continue
        # The operand is the next token, unless it is a flag. `-m` (module name)
        # and `-c` (inline code) take an operand that is not a path, so those
        # invocations are skipped whole; any other flag is stepped over to reach
        # the operand.
        j = i + 1
        while (j <= n && tok[j] ~ /^-/) {
          if (tok[j] == "-m" || tok[j] == "-c") { j = 0; break }
          j++
        }
        if (j == 0 || j > n) continue
        print doc ":" NR ":" tok[j]
      }
    }
  ' "$1"
}

checked=0
missing=0

for doc in "${docs[@]}"; do
  if [[ ! -f "$doc" ]]; then
    echo "FATAL: document not found: $doc" >&2
    exit 2
  fi
  while IFS= read -r rec; do
    [[ -z "$rec" ]] && continue
    tok="${rec##*:}"
    where="${rec%:*}"

    # Strip surrounding quotes: `bash "tools/x.sh"` is the same claim as
    # `bash tools/x.sh`. Done before the filters below so a quote cannot smuggle
    # a variable past them (`"$REPO"/tools/x.sh` starts with a quote, not a $).
    tok="${tok%\"}"; tok="${tok#\"}"
    tok="${tok%\'}"; tok="${tok#\'}"

    # Not a repo-path claim: host paths, absolute paths, URLs, shell variables
    # or substitutions anywhere in the token, placeholders and globs. Each is
    # something the reader substitutes, not a file this repository ships.
    case "$tok" in
      ''|'~'*|/*|http*|*'$'*|*'<'*|*'>'*|*'*'*|*'{'*) continue ;;
    esac

    checked=$(( checked + 1 ))
    if [[ ! -f "$tok" ]]; then
      missing=$(( missing + 1 ))
      printf 'MISSING  %s: command names a file that does not exist: %s\n' "$where" "$tok"
    fi
  done < <(extract_commands "$doc")
done

echo ""
printf 'doc-command-check: %d runnable command(s) checked across %d document(s), %d missing\n' \
  "$checked" "${#docs[@]}" "$missing"

if [[ "$checked" -eq 0 ]]; then
  echo "FATAL: no runnable commands found to check — the extractor matched nothing," >&2
  echo "       which means it is broken or the docs stopped documenting commands." >&2
  exit 2
fi

if [[ "$missing" -gt 0 ]]; then
  echo "FAILED: a document instructs the reader to run a file this repo does not ship."
  exit 1
fi

echo "PASSED: every documented command resolves."
exit 0
