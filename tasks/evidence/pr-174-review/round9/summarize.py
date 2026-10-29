"""Round 9: counts and differences from the run.sh / run_residual.sh outputs
in this directory. Columns of probe7/e2e7: main, r6 = PREV (f646e4e), r7 =
NEW (this tree). Usage: python3 summarize.py > out_summary.txt"""
import collections
import glob
import re

FLAGGED = {'FAIL-OPEN-REGRESSION', 'HEAD-CRASH', 'R7-WEAKER', 'R7-REFUSE-COST'}


def read_lines(pattern):
    lines = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as handle:
            lines += handle.read().splitlines()
    return lines


def probe_rows(kind, wrap):
    lines = read_lines(f'r9_probe_{kind}_wrap_{wrap}*.txt')
    return [line.split() for line in lines if re.match(r'(ok|FIXED|FAIL|NEW-REFUSE|HEAD)', line)]


def print_probe(kind, wrap):
    rows = probe_rows(kind, wrap)
    vs_main = dict(collections.Counter(row[0] for row in rows))
    vs_prev = dict(collections.Counter(row[1] for row in rows))
    print(f'{kind:5s} {wrap:4s} rows={len(rows)} vs-main={vs_main} vs-f646e4e={vs_prev}')
    for row in rows:
        if row[0] in FLAGGED or row[1] in FLAGGED:
            print('     ', row[0], row[1], row[2])


def hook_rows(path):
    """(name, runs, consumer, main, prev, new) for each exit row of an e2e7 output."""
    name = runs = None
    for line in read_lines(path):
        head = re.match(r'(.*?)\s+WRAP=\S+ runs: (.*?)\s+len=', line)
        row = re.match(r'\s+(\w+) main=(\d)\S* r6=(\d)\S* r7=(\d)', line)
        if head:
            name, runs = head.group(1).strip(), head.group(2)
        elif row and name:
            yield (name, runs, *row.groups())


def print_hook(path):
    for name, runs, consumer, main, prev, new in hook_rows(path):
        ran = 'commit' in runs or 'push' in runs
        if new != prev or (ran and main == '2' and new == '0'):
            print(f'{path:32s} {name:34s} {consumer} main/f646e4e/new={main}/{prev}/{new} {runs}')


for kind in ('new', 'prior', 'resb'):
    for wrap in ('none', 'pre', 'suf', 'ansi'):
        print_probe(kind, wrap)
print()
for path in sorted(glob.glob('r9_e2e_*_wrap_*.txt')):
    print_hook(path)
