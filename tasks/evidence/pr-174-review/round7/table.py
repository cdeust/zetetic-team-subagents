"""Exit-code table from e2e6.py outputs: per case, main / before (3aaeed4) / after
(this tree), and the git commit/push each shell ran. Usage: python3 table.py"""
import glob, re
rows = {}
for label in ('before', 'after'):
    for path in sorted(glob.glob(f'{label}_e2e_*.txt')):
        name = runs = None
        with open(path) as handle:
            lines = handle.read().splitlines()
        for line in lines:
            if 'runs:' in line:
                name = line.split(' runs:')[0].strip()
                runs = ' '.join('%s:%s' % (sh, 'y' if v != '[]' else '-') for sh, v in
                                re.findall(r'(bash|zsh|czsh)=(\[[^\]]*\])', line))
                rows.setdefault(name, {})['runs'] = runs
            m = re.match(r'\s+(main|head) exit=(\d+)', line)
            if m and name:
                rows[name]['main' if m.group(1) == 'main' else label] = m.group(2)
print(f'{"case":34s} main before after  shells (y = a git commit/push ran)')
for name, r in rows.items():
    print(f'{name:34s} {r.get("main", "?"):4s} {r.get("before", "?"):6s} {r.get("after", "?"):5s}  {r.get("runs", "")}')
