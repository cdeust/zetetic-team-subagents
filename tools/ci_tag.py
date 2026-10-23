#!/usr/bin/env python3
"""Publish validated package versions without overwriting an existing tag.

Source: tasks/package-release-tags.md; git-scm.com/docs/git-push (--atomic).
Concurrent overlap is retried only after the pending set strictly shrinks.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def git(*args, check=True):
    return subprocess.run(["git", *args], text=True, capture_output=True, check=check)


def validate(tags, sha):
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("Release target must be a full commit SHA")
    if git("cat-file", "-t", sha).stdout.strip() != "commit":
        raise ValueError("Release target must name a commit object")
    trusted = git(
        "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"
    ).stdout.strip()
    if git("rev-parse", "HEAD").stdout.strip() != trusted:
        raise ValueError("Release checkout differs from trusted main")
    # Source: https://git-scm.com/docs/git-merge-base#Documentation/git-merge-base.txt---is-ancestor
    # The privileged checkout is main; only the explicit tested ancestor is tagged.
    git("merge-base", "--is-ancestor", sha, trusted)
    if (
        not isinstance(tags, list)
        or not tags
        or any(not isinstance(t, str) or not t for t in tags)
    ):
        raise ValueError("release_tags must be a nonempty list of tag names")
    if len(set(tags)) != len(tags):
        raise ValueError("duplicate release tags")
    for tag in tags:
        git("check-ref-format", "refs/tags/" + tag)
        if any(other != tag and other.startswith(tag + "/") for other in tags):
            raise ValueError("conflicting release tag refs")


def remote_existing(tags):
    refs = {"refs/tags/" + tag: tag for tag in tags}
    output = git("ls-remote", "--refs", "origin", *refs).stdout
    return {
        refs[line.split()[1]]
        for line in output.splitlines()
        if len(line.split()) == 2 and line.split()[1] in refs
    }


def prepare_local(tags, sha):
    for tag in tags:
        ref = "refs/tags/" + tag
        found = git("show-ref", "--verify", "--quiet", ref, check=False)
        if found.returncode == 0:
            if git("rev-parse", ref + "^{}").stdout.strip() != sha:
                raise ValueError("Local unpublished tag points elsewhere: " + tag)
        elif found.returncode == 1:
            git(
                "-c",
                "user.name=github-actions[bot]",
                "-c",
                "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "tag",
                "-a",
                "-m",
                "Release " + tag,
                "--",
                tag,
                sha,
            )
        else:
            raise subprocess.CalledProcessError(
                found.returncode, found.args, stderr=found.stderr
            )


def publish(tags, sha):
    existing = remote_existing(tags)
    pending = set(tags) - existing
    while pending:
        prepare_local(sorted(pending), sha)
        refs = [f"refs/tags/{tag}:refs/tags/{tag}" for tag in sorted(pending)]
        result = git("push", "--atomic", "origin", *refs, check=False)
        if result.returncode == 0:
            return sorted(pending), sorted(existing)
        remaining = pending - remote_existing(sorted(pending))
        if not remaining < pending:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, stderr=result.stderr
            )
        existing.update(pending - remaining)
        pending = remaining
    return [], sorted(existing)


def main():
    try:
        tags = json.loads(os.environ["RELEASE_TAGS"])
        sha = os.environ["TESTED_SHA"]
        validate(tags, sha)
        published, existing = publish(tags, sha)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(getattr(exc, "stderr", None) or str(exc), file=sys.stderr)
        return 1
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as out:
        for tag in published:
            out.write(f"Published {tag} at {sha}\n")
        for tag in existing:
            out.write(f"Existing {tag}: target preserved\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
