#!/bin/bash
# Round 9: the residual R3-R5 (c_r9_residual_b.py), probe7 and full hook,
# every wrapper. Usage: bash run_residual.sh <label> PREV NEW
cd "$(dirname "$0")" || exit 1
label=$1; export PREV=$2 NEW=$3
R8=../round8
REPO=$(git rev-parse --show-toplevel)
for w in none pre suf ansi; do
  WRAP=$w python3 -I $R8/probe7.py "$REPO" c_r9_residual_b.py > "${label}_probe_resb_wrap_$w.txt" 2>&1
  WRAP=$w CONSUMERS=dirty python3 -I $R8/e2e7.py "$REPO" c_r9_residual_b.py > "${label}_e2e_resb_wrap_$w.txt" 2>&1
done
echo done > "$label.resb.done"
