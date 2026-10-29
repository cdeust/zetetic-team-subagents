"""Time head git_commands on adversarial-size inputs (origin/main for reference)."""
import importlib.util, os, sys, time
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path + '/gate_targets.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
H = load('gt_head', os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../hooks/lib'))  # adapted: this checkout
inputs = {
 'many a[ words 1k': ' '.join(['a['] * 1000) + '\ngit commit -m x',
 'many a[ words 2k': ' '.join(['a['] * 2000) + '\ngit commit -m x',
 'many a[ words 4k': ' '.join(['a['] * 4000) + '\ngit commit -m x',
 'many (( 1.5k': ' '.join(['(('] * 1500) + '; git commit -m x',
 'many (( 3k': ' '.join(['(('] * 3000) + '; git commit -m x',
}
import multiprocessing as mp
def one(cmd, q):
    try:
        r = H.git_commands(cmd, '/tmp/base')
    except ValueError as e:
        r = 'REFUSE'
    except BaseException as e:
        r = 'CRASH:' + type(e).__name__
    q.put(str(r)[:60])
if __name__ == '__main__':
    mp.set_start_method('fork')
    for name, cmd in inputs.items():
        q = mp.Queue(); p = mp.Process(target=one, args=(cmd, q)); t = time.time(); p.start(); p.join(120)
        if p.is_alive():
            p.kill(); p.join(); r = 'TIMEOUT>120s'
        else:
            r = q.get() if not q.empty() else 'exit=%s' % p.exitcode
        print(f'{time.time() - t:8.2f}s  len={len(cmd):7d}  {name:28s} {r}', flush=True)
