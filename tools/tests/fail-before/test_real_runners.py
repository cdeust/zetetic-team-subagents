import json
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile

gate = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as td:
    for lang in ('rs', 'js', 'go'):
        if not shutil.which({'rs': 'cargo', 'js': 'npm', 'go': 'go'}[lang]):
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
        elif lang == 'go':
            (repo / 'go.mod').write_text('module probe\n\ngo 1.20\n')
            (repo / 'answer.go').write_text('package probe\nfunc Answer() int { return 1 }\n')
            prefix = 'package probe\nimport "testing"\n'
            cases = {
                'pass': (prefix + 'func TestAnswer(t *testing.T) { if Answer() != 1 { t.Fatal("wrong") } }\n', 'VACUOUS'),
                'fail': (prefix + 'func TestAnswer(t *testing.T) { if Answer() != 42 { t.Fatal("wrong") } }\n', 'as they must'),
                'zero': ('package probe\n', 'INCONCLUSIVE'),
                'compile': (prefix + 'func TestAnswer(t *testing.T) { invalid }\n', 'INCONCLUSIVE'),
            }
            path = repo / 'answer_test.go'
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
        path.parent.mkdir(exist_ok=True)
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

        if lang == 'go':
            path.write_text(cases['pass'][0])
            (repo / 'other_test.go').write_text(cases['fail'][0].replace('TestAnswer', 'TestOther'))
            (repo / '.zetetic.conf').write_text('ZETETIC_PROFILE=strict\n')
            result = run(str(gate), '--base', 'HEAD')
            assert result.returncode == 1 and 'VACUOUS' in result.stdout, result
            assert 'as they must' in result.stdout, result
            print('go mixed files: independent test-name selectors', flush=True)
