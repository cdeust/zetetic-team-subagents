"""`git push` words, parsed the way git parses them (hooks/lib/gate_pushargs.py), on data: no repository, no hook."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_pushargs as pushargs  # noqa: E402



@pytest.mark.parametrize("args,flags,positional", [
    (["-odebug", "origin", "feat"], {}, ["origin", "feat"]),
    (["-on", "origin", "feat"], {}, ["origin", "feat"]),
    (["-nv", "origin"], {"dry": True}, ["origin"]),
    (["-vn", "origin"], {"dry": True}, ["origin"]),
    (["-do", "x", "origin"], {"delete": True}, ["origin"]),
    (["-o", "n", "origin"], {}, ["origin"]),
    (["--dry", "origin"], {"dry": True}, ["origin"]),
    (["--dry-run", "--no-dry-run", "origin"], {"dry": False}, ["origin"]),
    (["--del", "origin"], {"delete": True}, ["origin"]),
    (["--re", "origin"], {}, ["origin"]),  # ambiguous prefix (repo, receive-pack, recurse-submodules): git refuses it
    (["--repo", "origin", "feat"], {"repo": "origin"}, ["feat"]),
    (["--repo=origin", "feat"], {"repo": "origin"}, ["feat"]),
    (["--no-repo", "origin"], {"repo": None}, ["origin"]),
    (["--tags", "--no-tags", "origin"], {"tags": False}, ["origin"]),
    (["--follow-tags", "origin"], {"follow_tags": True}, ["origin"]),
    (["--follow-tags", "--no-follow-tags", "origin"], {"follow_tags": False}, ["origin"]),
    (["origin"], {"follow_tags": None}, ["origin"]),
    (["--force-with-lease", "origin", "feat"], {}, ["origin", "feat"]),  # an optional value is written with `=`
    (["--force-with-lease=feat:abc", "origin", "feat"], {}, ["origin", "feat"]),
    (["--", "-n", "origin"], {}, ["-n", "origin"]),
    (["-", "origin"], {}, ["-", "origin"]),
])
def test_arguments_are_read_the_way_git_reads_them(args, flags, positional):
    found, words = pushargs.parse(args)
    assert {k: found[k] for k in flags} == flags and words == positional


def test_refspecs_are_split_the_way_git_splits_them():
    assert pushargs.refspecs(["+a:b", "c", ":d", "tag", "v1", "e:refs/tags/f"]) == [
        pushargs.Refspec("a", "b"), pushargs.Refspec("c", "c"), pushargs.Refspec("", "d"),
        pushargs.Refspec("refs/tags/v1", "refs/tags/v1"), pushargs.Refspec("e", "refs/tags/f")]
    assert [s.deletes for s in pushargs.refspecs([":d", "a"])] == [True, False]
    assert [s.to_tag for s in pushargs.refspecs(["a:refs/tags/t", "a:b"])] == [True, False]


@pytest.mark.parametrize("args", [["--tags", "origin", ":feat"], ["--all", "origin", ":feat"], ["--mirror", "origin", ":feat"],
                                  ["--follow-tags", "origin", ":feat"]])
def test_a_deletion_beside_an_option_that_publishes_still_publishes(args):
    assert pushargs.publishes_no_commit(args) is False
