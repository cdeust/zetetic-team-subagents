#!/bin/bash
# Round 8: the round-7 reviewer's probe7/e2e7 (adapted: PREV/NEW select the
# previous and new head). Usage: bash run.sh <label> PREV NEW
#   before: bash run.sh before 3aaeed4eb9c25cc5a1db6aa9ca522c7083614db0 888312bd488599ba6a569d137beb10355bebb39e
#   after:  bash run.sh after 888312bd488599ba6a569d137beb10355bebb39e WORKTREE
cd "$(dirname "$0")" || exit 1
label=$1; export PREV=$2 NEW=$3
REPO=$(git rev-parse --show-toplevel)
for w in none pre suf ansi; do
  WRAP=$w python3 -I probe7.py "$REPO" cases7/c_sib.py cases7/c_size.py > "${label}_probe_new_wrap_$w.txt" 2>&1
  WRAP=$w python3 -I probe7.py "$REPO" cases_fixer_r7/r2/c_*.py cases_fixer_r7/r3/c_*.py cases_fixer_r7/r4/c_*.py \
    cases_fixer_r7/r5/c_*.py cases_fixer_r7/branch-r4/c_*.py cases_fixer_r7/r6/c_*.py > "${label}_probe_prior_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=dirty python3 -I e2e7.py "$REPO" cases7/c_e2e_block.py > "${label}_e2e_block_wrap_$w.txt" 2>&1
done
for w in none pre; do
  WRAP=$w CONSUMERS=clean python3 -I e2e7.py "$REPO" cases7/c_cost.py > "${label}_e2e_cost_wrap_$w.txt" 2>&1
done
# Split long outputs (the repository's 500-line file limit).
for f in "${label}"_probe_prior_wrap_*.txt; do
  head -450 "$f" > "${f%.txt}.part1.txt"; tail -n +451 "$f" > "${f%.txt}.part2.txt"; rm "$f"
done
echo done > "$label.done"
