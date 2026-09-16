import json
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile

gate = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as td:
    for lang in ('rs', 'js'):
        if not shutil.which('cargo' if lang == 'rs' else 'npm'):
            print(f'{lang}: runner unavailable; real-runner probe not executed')
            continue
        repo = Path(td) / lang
        repo.mkdir()
        def run(*args):
            return subprocess.run(args, cwd=repo, text=True, capture_output=True)
        run('git', 'init', '-q')
        run('git', 'config', 'user.name', 'test')
        run('git', 'config', 'user.email', 'test@example.invalid')
        if lang == 'rs':
            (repo / 'Cargo.toml').write_text('[package]\nname = "probe"\nversion = "0.1.0"\nedition = "2021"\n')
            (repo / 'src').mkdir()
            (repo / 'src/lib.rs').write_text('pub fn answer() -> u32 { 1 }\n')
            cases = {
                'pass': ('#[test]\nfn answer() { assert_eq!(probe::answer(), 1); }\n', 'VACUOUS'),
                'fail': ('#[test]\nfn answer() { assert_eq!(probe::answer(), 42); }\n', 'as they must'),
                'zero': ('// no tests\n', 'INCONCLUSIVE'),
                'compile': ('this is not rust\n', 'INCONCLUSIVE'),
            }
            path = repo / 'tests/check.rs'
        else:
            (repo / 'package.json').write_text(json.dumps({'scripts': {'test': 'node --test'}}))
            (repo / 'answer.js').write_text('exports.answer = () => 1;\n')
            prefix = "const test = require('node:test'); const assert = require('node:assert'); const {answer} = require('../answer');\n"
            cases = {
                'pass': (prefix + "test('answer', () => assert.equal(answer(), 1));\n", 'VACUOUS'),
                'fail': (prefix + "test('answer', () => assert.equal(answer(), 42));\n", 'as they must'),
                'zero': ('// no tests\n', 'INCONCLUSIVE'),
                'compile': ('this is not JavaScript {{{\n', 'INCONCLUSIVE'),
            }
            path = repo / 'tests/check.test.js'
        run('git', 'add', '.')
        run('git', 'commit', '-qm', 'base')
        path.parent.mkdir()
        for name, (body, expected) in cases.items():
            path.write_text(body)

            result = run(str(gate), '--base', 'HEAD')
            print(lang, name, result.returncode, result.stdout.strip(), flush=True)
            assert expected in result.stdout, (name, expected, result)

        if lang == 'js':
            second = path.parent / 'second.test.js'
            path.write_text('// empty\n')
            second.write_text('// also empty\n')
            result = run(str(gate), '--base', 'HEAD')
            assert 'VACUOUS' not in result.stdout and result.stdout.count('INCONCLUSIVE') == 2, result
            print('js two empty files: INCONCLUSIVE', flush=True)
            path.write_text(cases['pass'][0])
            second.write_text(cases['fail'][0])
            (repo / '.zetetic.conf').write_text('ZETETIC_PROFILE=strict\n')
            result = run(str(gate), '--base', 'HEAD')
            assert result.returncode == 1 and 'VACUOUS' in result.stdout, result
            assert 'as they must' in result.stdout, result
            print('js mixed pass/fail files: strict block with both verdicts', flush=True)
