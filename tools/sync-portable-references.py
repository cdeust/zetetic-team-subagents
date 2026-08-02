#!/usr/bin/env python3
"""Generate portable evidence references from canonical genius agents."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents" / "genius"
REFERENCES = (
    ROOT
    / "plugins"
    / "zetetic-reasoning"
    / "skills"
    / "evidence-synthesis"
    / "references"
)
NAMES = (
    "cochrane",
    "darwin",
    "feynman",
    "gadamer",
    "geertz",
    "laplace",
    "strauss",
    "toulmin",
)
SECTIONS = (
    ("identity", "Primary method and sources"),
    ("routing", "When to use this method"),
    ("revolution", "Problem and replacement"),
    ("canonical-moves", "Canonical moves"),
    ("blind-spots", "Blind spots"),
    ("refusal-conditions", "Refusal conditions"),
    ("workflow", "Workflow"),
    ("output-format", "Output format"),
)


def _render(name: str) -> str:
    source = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    rendered = [
        f"# {name.title()} evidence method",
        "",
        "> Generated from `agents/genius/"
        + name
        + ".md` by `tools/sync-portable-references.py`; do not edit directly.",
    ]
    for tag, heading in SECTIONS:
        match = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", source)
        if match is None:
            raise ValueError(f"{name}: missing <{tag}> section")
        body = re.sub(
            r" \(full guidance — relocated from frontmatter to keep cumulative "
            r"description tokens under Claude Code's 15k cap; routing accuracy preserved\)",
            "",
            match.group(1).strip(),
        )
        rendered.extend(("", f"## {heading}", "", body))
    return "\n".join(rendered).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    drifted = [
        name
        for name in NAMES
        if not (REFERENCES / f"{name}.md").is_file()
        or (REFERENCES / f"{name}.md").read_text(encoding="utf-8") != _render(name)
    ]
    if args.check:
        if drifted:
            raise SystemExit(
                "generated portable references drifted: "
                + ", ".join(drifted)
                + "; run python3 tools/sync-portable-references.py"
            )
        print("portable evidence references match their canonical agents")
        return

    REFERENCES.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        (REFERENCES / f"{name}.md").write_text(_render(name), encoding="utf-8")
    print(f"generated {len(NAMES)} portable references from agents/genius")


if __name__ == "__main__":
    main()
