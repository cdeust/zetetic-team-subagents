"""Exit-code tables from the e2e7.py outputs: per case and wrapper, main /
previous head / new head, and which shells ran git. Columns r6 and r7 are
the PREV and NEW heads of run.sh: before = 3aaeed4 / 888312b, after =
888312b / this tree. Usage: python3 table.py"""
import glob, re
for path in sorted(glob.glob('*_e2e_*_wrap_*.txt')):
    with open(path) as handle:
        lines = handle.read().splitlines()
    print('==', path)
    name = runs = None
    for line in lines:
        m = re.match(r'(.*?)\s+WRAP=\S+ runs: (.*?)\s+len=', line)
        if m:
            name, runs = m.group(1).strip(), m.group(2)
            continue
        m = re.match(r'\s+(\w+) main=(\S+) r6=(\S+) r7=(\S+)', line)
        if m and name:
            print(f'{name:34s} {m.group(1):5s} {m.group(2):12s} {m.group(3):12s} {m.group(4):12s} {runs}')
