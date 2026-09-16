"""Exercise push repository resolution through the packaged CLI boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = sys.argv[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        other = root / 'other space'
        other.mkdir()
        cases = [
            ('git push', root),
            ('echo git push', None),
            ('git status', None),
            (f'git -C "{other}" push', other),
            (f'cd "{other}" && git push', other),
            (f'(cd "{other}"); git push', root),
            (f'(cd "{other}" && git push)', other),
            ('env FLAG=1 git push', root),
            ('command git push', root),
            ('echo ready\ngit push', root),
            (f'cd \"{other}\"\ngit push', other),
        ]
        for command, expected in cases:
            event = {'cwd': str(root), 'tool_input': {'command': command}}
            result = subprocess.run([sys.executable, parser], input=json.dumps(event),
                                    text=True, capture_output=True, check=True)
            assert result.stdout.rstrip('\0') == (str(expected) if expected else ''), (command, result)
        malformed = subprocess.run([sys.executable, parser], input='[1]', text=True,
                                   capture_output=True, check=True)
        assert 'INCONCLUSIVE' in malformed.stderr and not malformed.stdout
        print(f'{len(cases) + 1} context cases passed')


if __name__ == '__main__':
    main()
