#!/bin/bash
# Round 9: the round-7 reviewer's probe7/e2e7 as adapted in round8/ (PREV/NEW
# select the previous and new head), with the round-8 replay's 784-row fixer
# file list. Columns: main / r6 = PREV / r7 = NEW.
# Usage: bash run.sh <label> PREV NEW
#   bash run.sh r9 f646e4e1de6b0815de7a806991b5d89acc785c00 WORKTREE
cd "$(dirname "$0")" || exit 1
label=$1; export PREV=$2 NEW=$3
R8=../round8
REPO=$(git rev-parse --show-toplevel)
F=$R8/cases_fixer_r7
for w in none pre suf ansi; do
  WRAP=$w python3 -I $R8/probe7.py "$REPO" $R8/cases7/c_sib.py $R8/cases7/c_size.py $R8/cases7/c_cost.py \
    $R8/cases7/c_e2e_block.py c_r9.py c_r9_residual.py > "${label}_probe_new_wrap_$w.txt" 2>&1
  WRAP=$w python3 -I $R8/probe7.py "$REPO" $F/r2/c_*.py $F/r3/c_*.py $F/r4/c_*.py $F/r5/c_*.py $F/branch-r4/c_*.py \
    $F/r6/c_r6hunt.py $F/r6/c_r6sib.py $F/r6/c_r6alias.py $F/r6/c_r7sib.py > "${label}_probe_prior_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=dirty python3 -I $R8/e2e7.py "$REPO" $R8/cases7/c_e2e_block.py > "${label}_e2e_block_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=dirty python3 -I $R8/e2e7.py "$REPO" c_r9.py > "${label}_e2e_r9_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=dirty python3 -I $R8/e2e7.py "$REPO" c_r9_residual.py > "${label}_e2e_r9res_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=clean python3 -I $R8/e2e7.py "$REPO" $R8/cases7/c_cost.py > "${label}_e2e_cost_wrap_$w.txt" 2>&1
done
# Split long outputs (the repository's 500-line file limit).
for f in "${label}"_probe_prior_wrap_*.txt; do
  head -450 "$f" > "${f%.txt}.part1.txt"; tail -n +451 "$f" > "${f%.txt}.part2.txt"; rm "$f"
done
echo done > "$label.done"
