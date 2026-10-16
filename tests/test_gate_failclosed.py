"""run-python.sh without Python (PR #169, round 3): the refusal must not depend on any tool, and must read `git`
or `gh` as a command word, not as a substring.

At ea62083 the refusal ran `grep` on the payload: with no grep on the PATH the pipeline failed and the call went
through; and "highlights" or a working directory under "github" matched the substring and was refused. Both
directions are tested, with a PATH that holds no tool at all (only the shell's builtins can answer).

Round 4 (review-r3/transcripts/a3_nopython.txt): at b851aa4 a quoted or escaped command word passed, `"git" push`,
`'git' commit`, `\\git push`, `git"" push`, `/usr/bin/"git" push`, while the Python hook reads each as git. The
payload is now dequoted before it is matched (run-python.sh, dequote). Every a3 command is tested in both
directions, against both copies of run-python.sh (hooks/ and the standalone plugins/zetetic-gates/ package).
"""
from __future__ import annotations

import json
import subprocess

import pytest

from gate_support import HOOKS, ROOT, payload
from test_gate_attacks import no_python_path, run_wrapper

COPIES = [HOOKS / "run-python.sh", ROOT / "plugins" / "zetetic-gates" / "hooks" / "run-python.sh"]

REFUSED = [
    "git commit -m x", "git push", "gh pr create --fill", "/usr/bin/git push origin feat", "cd sub && git commit -m x",
    "echo a; gh pr create", "(git push)", "time git push", "ls\ngit push", "echo $(git push)", "echo `git push`",
    "FOO=1 git push", "true|git push", "{ git push; }", "if true; then git push; fi", "ls\tgh pr create",
    # review-r3/bin/a3_cmds.txt: the quoted and escaped spellings the Python hook reads as git
    "git push origin main", '"git" push origin main', "'git' commit -m x", "\\git push origin main",
    'git"" push origin main', "git\\ push", '/usr/bin/"git" push origin main', "cd repo&&git push", "x=1 git push",
    "'gh' pr create", '"gh" pr create --fill', "\\gh pr create", "'/usr/bin/git' push", 'gi""t push', "g\\it push",
]
ALLOWED = [
    "ls -la", "echo highlights", "echo ghost", "cat gitlog.txt", "echo digit github", "grep -r ghz .", "echo legit",
    "python3 -m pytest tests/test_gitlab.py", "ls /home/me/github/repo",
    "echo highlights github ghost", "ls", "echo git", "gitk", "echo x-git y", "cat .git/config", "ls ~/git",
]


@pytest.mark.parametrize("command", REFUSED)
@pytest.mark.parametrize("tools", [(), ("cat",), ("cat", "grep")])
def test_a_command_word_git_or_gh_is_refused_whatever_tools_exist(tmp_path, command, tools):
    rc, err = run_wrapper(tmp_path, "gate-proof.py", payload(command, tmp_path), tools)
    assert rc == 2 and "refused (closed)" in err, (command, tools, err)


@pytest.mark.parametrize("command", ALLOWED)
@pytest.mark.parametrize("tools", [(), ("cat", "grep")])
def test_a_call_that_only_contains_the_letters_is_not_refused(tmp_path, command, tools):
    rc, err = run_wrapper(tmp_path, "gate-proof.py", payload(command, tmp_path), tools)
    assert rc == 0, (command, tools, err)


@pytest.mark.parametrize("cwd", ["/Users/me/github/repo", "/home/me/git", "/srv/gh", "/x/ghost/git-lab", "/Users/x/git"])
def test_a_working_directory_that_contains_the_letters_does_not_refuse_a_harmless_call(tmp_path, cwd):
    rc, err = run_wrapper(tmp_path, "gate-proof.py", {"cwd": cwd, "tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert rc == 0, (cwd, err)


def run_copy(tmp_path, copy, command: str, tools: tuple) -> int:
    out = subprocess.run(["/bin/bash", str(copy), str(HOOKS / "gate-proof.py")], input=json.dumps(payload(command, tmp_path)),
                         capture_output=True, text=True, env={"PATH": no_python_path(tmp_path, tools), "HOME": str(tmp_path)})
    return out.returncode


@pytest.mark.parametrize("copy", COPIES, ids=["hooks", "plugin"])
@pytest.mark.parametrize("tools", [(), ("cat",), ("cat", "grep")])
def test_both_copies_refuse_every_spelling_and_allow_every_harmless_call(tmp_path, copy, tools):
    assert {c: run_copy(tmp_path, copy, c, tools) for c in REFUSED} == {c: 2 for c in REFUSED}
    assert {c: run_copy(tmp_path, copy, c, tools) for c in ALLOWED} == {c: 0 for c in ALLOWED}


def test_the_two_copies_are_the_same_file():
    assert COPIES[0].read_bytes() == COPIES[1].read_bytes()  # scripts/sync-gates.py keeps them so


def test_an_empty_or_unreadable_payload_is_refused(tmp_path):
    rc, _ = run_wrapper(tmp_path, "gate-proof.py", {})
    assert rc == 0  # {} names no command: nothing to publish
    out = subprocess.run(["/bin/bash", str(HOOKS / "run-python.sh"), str(HOOKS / "gate-proof.py")], input="",
                         capture_output=True, text=True, env={"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert out.returncode == 2
