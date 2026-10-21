"""Allowlist cost on the corpus: rows where origin/main refused and the new
head returns [], tabulated by the command names in them (the rows an
allowlist rule would decide). Usage: python3 r9allow.py files..."""
import ast, collections, re, sys
WT = '/Users/cdeust/Developments/anthropic-partnership/zetetic-team-subagents/.claude/worktrees/fix-gate-heredoc/'
sys.path.insert(0, WT + 'hooks/lib')
import importlib.util
spec = importlib.util.spec_from_file_location('gt', WT + 'hooks/lib/gate_targets.py')
gt = importlib.util.module_from_spec(spec); spec.loader.exec_module(gt)
names, rows = collections.Counter(), 0
for path in sys.argv[1:]:
    for line in open(path):
        if 'main=REFUSE' not in line or ' r7=[] ' not in line:
            continue
        m = re.search(r" cmd=(.*?)\s*$", line)
        if not m:
            continue
        try:
            cmd = ast.literal_eval(m.group(1))
        except Exception:
            continue
        rows += 1
        rewritten, _dropped = gt.shell_text.read(cmd)
        text = gt.shell_text.unquoted(rewritten)
        found = set()
        for pos in gt._POSITION.finditer(text):
            word = gt._WORD.match(text, pos.end()).group()
            if word and not gt._ASSIGNMENT.match(word):
                found.add(word)
        names.update(found)
print('rows main=REFUSE new=[]:', rows)
for name, count in names.most_common():
    print(f'{count:5d} {name}')
