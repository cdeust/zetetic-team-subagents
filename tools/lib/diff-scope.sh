# shellcheck shell=bash
# diff-scope.sh — changed-line ranges, so a commit gate reports only what the
# commit is answerable for.
#
# Sourced by tools/craftsmanship-checker.sh and tools/redaction-checker.sh.
# NOT executable on its own (no shebang by design — sourced library; the
# shell= directive declares the dialect for static analysis).
#
# WHY THIS EXISTS
# The structural detectors measure a WHOLE FILE, and that is correct: you
# cannot tell how long a function is from the added lines alone. The reporting
# decision is a different question from the measurement decision. A commit that
# rewords one doc comment in a file holding a pre-existing over-long function
# was refused over that function, and the author could neither fix it in that
# commit nor bypass the gate -- so the gate stopped being about the commit and
# became about the file's history. Same shape in the prose checker: a one-line
# change to a document with 25 pre-existing em dashes re-reported all 25.
#
# A gate that blocks a commit over code the commit did not touch trains authors
# to bypass it, and a bypassed gate enforces nothing.
#
# CONTRACT
# ZETETIC_DIFF_RANGES carries the changed-line ranges of the content under
# check, as one record per file:
#
#     <path>:<start>-<end>[,<start>-<end>...];<path>:...
#
# Set => scoped reporting: a finding is reported only when its span intersects
#        a changed range of its own file (ds_touches).
# Unset => every finding is reported, as before. --full, --files on a named file
#        set, and --stdin never set it, so audit and review modes are unchanged.
#
# A file present in the variable with NO ranges (``path:``) has changed ranges
# that are empty -- a pure deletion, say -- and nothing in it is attributable.
# A file ABSENT from a set variable is not under diff scope at all and is
# reported in full; that is the conservative direction (report, don't hide).
#
# The variable, rather than a `git diff` inside each checker, because the
# commit gate (hooks/lib/staged_checks.py) checks FROZEN INDEX BLOBS
# materialized into a disposable repository: `git diff --cached` there compares
# nothing. Only the caller that holds the real repository can compute the
# ranges, so the caller passes them in.

# Fill ZETETIC_DIFF_RANGES from the index of the repository at $1 (default:
# the current one). `-U0` so a hunk header names exactly the changed lines.
# `+0,0` (a pure deletion) contributes no range, leaving `path:`.
ds_ranges_from_index() {
  local root="${1:-}" out="" name first=1 start count end line
  local -a diff_cmd=(git)
  [[ -n "$root" ]] && diff_cmd+=(-C "$root")
  # The file list comes from --name-only -z, which is authoritative and cannot be
  # spoofed by file CONTENT. Parsing `+++ b/` headers out of a combined diff was
  # a real false negative: an ADDED line reading `++ b/ignored` opened a bogus
  # record and the real file's later hunks were credited to it, suppressing its
  # findings. Hunks are therefore read per file, one diff per file, where every
  # `@@` line provably belongs to that file.
  while IFS= read -r -d '' name; do
    [[ -z "$name" ]] && continue
    [[ $first -eq 1 ]] || out+=";"
    first=0
    out+="$name:"
    local sep=""
    while IFS= read -r line; do
      [[ "$line" == '@@ '* ]] || continue
      # @@ -a,b +c,d @@  -> the added side is the +c,d field.
      start="${line#*+}"; start="${start%% *}"; start="${start%%@@*}"
      count="${start#*,}"; start="${start%%,*}"
      [[ "$count" == "$start" ]] && count=1
      if [[ "$count" == 0 ]]; then
        # A pure deletion (`+n,0`) removes lines at this point. It records no
        # added line, yet it can still create a violation -- deleting a `def`
        # line merges two functions into one over-long one. The deletion SITE is
        # therefore recorded as a point range, so a span covering it is
        # attributed to this commit.
        [[ "$start" == 0 ]] && continue
        end="$start"
      else
        end=$((start + count - 1))
      fi
      out+="${sep}${start}-${end}"
      sep=","
    done < <("${diff_cmd[@]}" diff --cached -U0 --diff-filter=ACMR -- "$name" 2>/dev/null)
  done < <("${diff_cmd[@]}" diff --cached --name-only -z --diff-filter=ACMR 2>/dev/null)
  ZETETIC_DIFF_RANGES="$out"
  # The directory the recorded paths are relative to, so an absolute path handed
  # to a checker can be resolved to the SAME form, exactly rather than by suffix.
  ZETETIC_DIFF_ROOT="${root:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  export ZETETIC_DIFF_RANGES ZETETIC_DIFF_ROOT
}

# ds_scoped: 0 when diff scoping is in force (the variable is SET, even empty).
# `${VAR+set}` not `${VAR:-}`: an empty value is a real state (a commit whose
# changed set is empty), distinct from the variable being absent.
ds_scoped() {
  [[ -n "${ZETETIC_DIFF_RANGES+set}" ]]
}

# The ranges recorded for a file. Returns 0 with the ranges (possibly empty)
# when the file HAS a record, 1 when it has none -- the two are different states
# and the caller treats them differently. Matching is on the path SUFFIX, because
# a checker is handed an absolute or repo-relative path while the ranges are
# recorded repo-relative. The repo-relative form of the target is derived by
# stripping ZETETIC_DIFF_ROOT, and ONLY exact matches count.
#
# A suffix match is NOT safe here and was a real false negative: with both
# `a/x.py` and `z/a/x.py` staged, `z/a/x.py` ends with `/a/x.py`, so it picked up
# `a/x.py`'s ranges and its own pre-existing violations were suppressed. A
# truncated path can always collide with a shorter real one, so the only sound
# rule is to resolve the target to the same form the ranges are recorded in.
ds_ranges_for() {
  local target="$1" record path candidate
  local root="${ZETETIC_DIFF_ROOT:-}"
  # Repo-relative candidate: the target with the recorded root stripped.
  candidate="$target"
  if [[ -n "$root" && "$target" == "$root"/* ]]; then
    candidate="${target#"$root"/}"
  fi
  local IFS=';'
  for record in ${ZETETIC_DIFF_RANGES:-}; do
    path="${record%%:*}"
    if [[ "$candidate" == "$path" || "$target" == "$path" ]]; then
      echo "${record#*:}"
      return 0
    fi
  done
  return 1
}

# ds_touches FILE START END — 0 when [START,END] intersects a changed range of
# FILE, so the finding is this commit's to answer for. Always 0 when scoping is
# off. A file with no recorded ranges yields 1: nothing in it is attributable.
#
# END may be empty or 0 for a finding with no span (a file-level rule). Such a
# finding is attributed whenever the file changed AT ALL: the rule is about the
# file as a whole, the commit changed that file, and the author can act on it
# (FILE_TOO_LONG on a file you just added lines to is exactly the signal §4.1
# is for). Only a file the commit does not touch escapes it.
ds_touches() {
  local target="$1" start="$2" end="${3:-}" ranges range from to
  ds_scoped || return 0
  # No record for this file: it is not under diff scope, so report in full.
  # A record with empty ranges IS under scope and attributes nothing.
  ranges="$(ds_ranges_for "$target")" || return 0
  [[ -z "$ranges" ]] && return 1
  [[ -z "$end" || "$end" == 0 ]] && end="$start"
  [[ "$start" -gt "$end" ]] && { local swap="$start"; start="$end"; end="$swap"; }
  local IFS=','
  for range in $ranges; do
    from="${range%%-*}"; to="${range##*-}"
    [[ "$start" -le "$to" && "$end" -ge "$from" ]] && return 0
  done
  return 1
}
