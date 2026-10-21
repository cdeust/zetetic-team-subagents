"""Sizes of each intermediate (input, rewritten text, shlex tokens) and the
time of git_commands on the round-5 blow-up shapes and size-cap shapes.
Usage: python3 -I sizes.py"""
import importlib.util, os, subprocess, time
W = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                   cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
spec = importlib.util.spec_from_file_location('gt', W + '/hooks/lib/gate_targets.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
shapes = {f'dq-subst d={d}': '"$(' * d + 'echo ' + '\\' * 200 + ')"' * d + '; git commit -m x' for d in (10, 14, 20)}
shapes.update({f'dq-span d={d}': '"${x:-' * d + '\\\\' * 100 + '}"' * d + '; git commit -m x' for d in (14, 20)})
shapes.update({
    'newlines 30k': 'echo a\n' * 18000 + 'git commit -m x',
    'parens 20k': 'echo ' + '(a) ' * 20000 + '; git commit -m x',
    'ansi escapes 3k': "echo $'" + "\\'" * 3000 + "'; git commit -m x",
    'one token at cap': 'git commit -m "' + 'x' * 131000 + '"',
})
for name, cmd in shapes.items():
    try:
        rewritten = m.shell_text.shell_lines(cmd)
        tokens = len(m._tokens(rewritten)) if len(rewritten) <= m.MAX_COMMAND else 'over cap'
        size = len(rewritten)
    except ValueError as error:
        size, tokens = 'raise', str(error)[:40]
    t = time.time()
    try:
        result = m.git_commands(cmd, '/tmp')
    except ValueError:
        result = 'REFUSE'
    print(f'{name:20s} input={len(cmd):7d} rewritten={size!s:8s} tokens={tokens!s:10s} time={time.time() - t:6.2f}s {str(result)[:30]}', flush=True)
