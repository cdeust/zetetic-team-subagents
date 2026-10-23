#!/usr/bin/env python3
"""ci_contract.py -- validates a repository's ``ci.json`` before any test runs.

The contract (docs/superpowers/specs/2026-10-22-single-ci-design.md, "Repository
contract: ci.json"): exactly the keys ``unit``, ``regression``, ``e2e``,
``environment`` and ``install``, each a non-empty shell command, plus an
optional ``version_file`` (default ``.claude-plugin/plugin.json``), or exclusive
``release_packages`` entries with version_file and tag_prefix. Every manifest
version and tag ref is validated before exporting commands or release tags.
A missing file, a missing key or an empty command fails the pipeline here, so a step that
has nothing to run never passes (the design's first anti-goal).

This file is also embedded verbatim in ``templates/ci/pipeline.yml`` as an inline
``python3 -`` step: standard library only, arguments through ``sys.argv``.

Usage: ``python3 tools/ci_contract.py [repo-root]`` (default: the current
directory). Exit 0 and the five commands plus ``version_file`` on stdout when
valid; exit 1 and the faults on stderr otherwise. --github-output exports the
validated commands and tags to GITHUB_OUTPUT. Source: tasks/package-release-tags.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import List

KEYS = ("unit", "regression", "e2e", "environment", "install")
VERSION_KEY = "version_file"
DEFAULT_VERSION_FILE = ".claude-plugin/plugin.json"
RELEASE_KEY = "release_packages"
ALLOWED_KEYS = KEYS + (VERSION_KEY, RELEASE_KEY)
ALLOWED = ", ".join(ALLOWED_KEYS)


def _load(root: Path):
    """The parsed document, or the one fault that stops validation."""
    path = root / "ci.json"
    if not path.is_file():
        return None, "ci.json: missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"ci.json: not valid JSON ({exc})"
    if not isinstance(data, dict):
        return None, "ci.json: must be a JSON object"
    return data, None


def _release_specs(data: dict) -> list[dict]:
    """Explicit package identities, or the historical single v<version> tag."""
    if RELEASE_KEY not in data:
        return [
            {
                "version_file": data.get(VERSION_KEY, DEFAULT_VERSION_FILE),
                "tag_prefix": "v",
            }
        ]
    if VERSION_KEY in data:
        raise ValueError("release_packages: cannot be combined with version_file")
    specs = data[RELEASE_KEY]
    if not isinstance(specs, list) or not specs:
        raise ValueError("release_packages: must be a nonempty list")
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != {"version_file", "tag_prefix"}:
            raise ValueError(
                "release_packages: entries need version_file and tag_prefix only"
            )
    return specs


def _manifest_path(root: Path, value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("version_file: not a string")
    if not value.strip():
        raise ValueError("version_file: empty path")
    relative = Path(value)
    path = (root / relative).resolve()
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not path.is_relative_to(root.resolve())
    ):
        raise ValueError("version_file: must stay inside the repository")
    if not path.is_file():
        raise ValueError(f"version_file: {value} does not exist")
    return path


def _manifest_version(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        doc = json.loads(body)
    elif path.suffix == ".toml":
        # Stdlib parser added in 3.11: https://docs.python.org/3/library/tomllib.html.
        try:
            import tomllib
        except ImportError as exc:
            raise ValueError(
                "version_file: TOML requires Python 3.11+ (stdlib tomllib)"
            ) from exc
        doc = tomllib.loads(body)
        doc = doc.get("project") or doc.get("package")
    else:
        raise ValueError(f"version_file: unsupported format: {path.name}")
    version = doc.get("version") if isinstance(doc, dict) else None
    if not isinstance(version, str) or not version or version != version.strip():
        raise ValueError(f"version_file: {path.name} needs a nonempty string version")
    return version


def _valid_tag(tag: str) -> bool:
    # Delegate ref grammar to Git: https://git-scm.com/docs/git-check-ref-format.
    return (
        subprocess.run(
            ["git", "check-ref-format", f"refs/tags/{tag}"], capture_output=True
        ).returncode
        == 0
    )


def release_tags(data: dict, root: Path) -> list[str]:
    """Resolve and validate the whole release plan without filesystem writes."""
    tags, paths, prefixes = [], set(), set()
    for spec in _release_specs(data):
        path = _manifest_path(root, spec["version_file"])
        prefix = spec["tag_prefix"]
        if not isinstance(prefix, str) or not prefix or not _valid_tag(prefix + "0"):
            raise ValueError("tag_prefix: invalid Git tag prefix")
        if path in paths or prefix in prefixes:
            raise ValueError("release_packages: duplicate manifest or tag prefix")
        version = _manifest_version(path)
        tag = prefix + version
        if not _valid_tag(tag):
            raise ValueError(f"version_file: invalid Git tag: {tag!r}")
        if any(
            tag == prior or tag.startswith(prior + "/") or prior.startswith(tag + "/")
            for prior in tags
        ):
            raise ValueError("release_packages: duplicate or conflicting tag refs")
        tags.append(tag)
        paths.add(path)
        prefixes.add(prefix)
    return tags


def _version_faults(data: dict, root: Path) -> List[str]:
    try:
        release_tags(data, root)
    except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
        return [str(exc)]
    return []


def faults(root: Path) -> List[str]:
    """Every fault of ``root/ci.json``, in key order then unknown keys; empty
    when the file honours the contract."""
    data, fatal = _load(root)
    if fatal:
        return [fatal]
    found: List[str] = []
    for key in KEYS:
        if key not in data:
            found.append(f"{key}: missing")
        elif not isinstance(data[key], str):
            found.append(f"{key}: not a string")
        elif not data[key].strip():
            found.append(f"{key}: empty command")
    found.extend(
        f"{key}: unknown key (allowed: {ALLOWED})"
        for key in data
        if key not in ALLOWED_KEYS
    )
    found.extend(_version_faults(data, root))
    return found


def _export(data: dict, tags: list[str]) -> None:
    outputs = {key: data[key] for key in KEYS}
    outputs["release_tags"] = json.dumps(tags)
    outputs["release_group"] = hashlib.sha256(
        json.dumps(sorted(tags)).encode()
    ).hexdigest()
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in outputs.items():
            # GitHub multiline output protocol: delimiter cannot occur on its own line.
            # https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#multiline-strings
            delimiter = str(uuid.uuid4())
            while delimiter in value.splitlines():
                delimiter = str(uuid.uuid4())
            out.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def main(argv: List[str]) -> int:
    root = Path(argv[0]) if argv else Path(".")
    found = faults(root)
    if found:
        for line in found:
            print(line, file=sys.stderr)
        return 1
    data, _ = _load(root)
    for key in KEYS:
        print(f"{key}: {data[key]}")
    if RELEASE_KEY in data:
        print(f"{RELEASE_KEY}: {json.dumps(data[RELEASE_KEY])}")
    else:
        print(f"{VERSION_KEY}: {data.get(VERSION_KEY, DEFAULT_VERSION_FILE)}")
    if "--github-output" in argv:
        _export(data, release_tags(data, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
