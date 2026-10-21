#!/bin/bash
# Round 7: run the round-6 reviewer's scripts (adapted to this checkout).
# Usage: bash run.sh <label> [HEAD rev]   label names the output files
# (before = 3aaeed4, after = the working tree). Ends by writing <label>.done.
cd "$(dirname "$0")" || exit 1
label=$1
export HEAD=${2:-WORKTREE}
for f in c_r6e2e c_r6e2e_b c_r6e2e_a3 c_r7sib; do
  python3 -I e2e6.py "cases/r6/$f.py" > "${label}_e2e_$f.txt" 2>&1
done
for w in none pre suf ansi; do
  WRAP=$w python3 -I probe6.py cases/r2/c_*.py cases/r3/c_*.py cases/r4/c_*.py cases/r5/c_*.py \
    cases/branch-r4/c_*.py cases/r6/c_r6hunt.py cases/r6/c_r6sib.py cases/r6/c_r6alias.py \
    cases/r6/c_r7sib.py > "${label}_probe_wrap_$w.txt" 2>&1
done
echo done > "$label.done"
# Split each probe output in two (the repository's 500-line file limit).
for f in "${label}"_probe_wrap_*.txt; do
  head -400 "$f" > "${f%.txt}.part1.txt"; tail -n +401 "$f" > "${f%.txt}.part2.txt"; rm "$f"
done
