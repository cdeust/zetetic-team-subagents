#!/usr/bin/env python3
"""Generate cross-harness portable skill packages from their canonical sources.

Generalized (Phase 5 of the agent-to-skill migration plan). This used to be
hardcoded to one skill: it always rendered `evidence-synthesis`'s eight
genius-agent references into
`plugins/zetetic-reasoning/skills/evidence-synthesis/references/` and nowhere
else. It now discovers every skill that opts in to cross-harness packaging via
a `portable:` frontmatter block on its canonical `skills/**/*.md` source, and
renders each skill's genius-agent reference files (when it names any) under
`plugins/<package>/skills/<skill>/references/`. Adding a new packaged skill —
including one with nothing to generate, like `design`, which is self-contained
with no genius-agent references — means adding a `portable:` block to that
skill's own frontmatter, not editing this script.

Discovery contract — a skill opts in with:

    portable:
      package: <plugins/ directory name the skill packages into>
      references: [<agents/genius/*.md name>, ...]   # optional, default []

`references` lists the genius agents whose `agents/genius/<name>.md` sections
get rendered into that skill's portable `references/` directory (unchanged
rendering logic from before this generalization). A skill that omits
`references` (or gives an empty list) is still a registered package member —
`--list` and the test suite read this script's discovery, not a duplicated
list — it simply has no generated files.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents" / "genius"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
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


@dataclass(frozen=True)
class PortableSkill:
    """One skill packaged for cross-harness (Codex/Gemini CLI) use.

    Precondition: `source` is a `skills/**/*.md` file whose frontmatter
    contains a `portable:` mapping with a `package` key.
    Postcondition: `references_dir` names where this skill's genius-agent
    reference files (if any) belong, under the target package.
    """

    slug: str
    source: Path
    package: str
    references: tuple[str, ...] = ()

    @property
    def references_dir(self) -> Path:
        return ROOT / "plugins" / self.package / "skills" / self.slug / "references"


def discover_portable_skills() -> tuple[PortableSkill, ...]:
    """Scan every canonical skill source for a `portable:` frontmatter block.

    Precondition: none (safe to call from a fresh checkout).
    Postcondition: returns one `PortableSkill` per skill file whose
    frontmatter declares `portable.package`, sorted by slug for determinism.
    """
    skills = []
    for path in ROOT.glob("skills/**/*.md"):
        if path.name in {"_index.md", "_template.md"}:
            continue
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
        if not match:
            continue
        frontmatter = yaml.safe_load(match.group(1)) or {}
        portable = frontmatter.get("portable")
        if not portable:
            continue
        skills.append(
            PortableSkill(
                slug=path.parent.name,
                source=path,
                package=portable["package"],
                references=tuple(portable.get("references", ())),
            )
        )
    return tuple(sorted(skills, key=lambda skill: (skill.package, skill.slug)))


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
        section = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", source)
        if section is None:
            raise ValueError(f"{name}: missing <{tag}> section")
        body = re.sub(
            r" \(full guidance — relocated from frontmatter to keep cumulative "
            r"description tokens under Claude Code's 15k cap; routing accuracy preserved\)",
            "",
            section.group(1).strip(),
        )
        rendered.extend(("", f"## {heading}", "", body))
    return "\n".join(rendered).rstrip() + "\n"


def _drifted_references(skill: PortableSkill) -> list[str]:
    drifted = []
    for name in skill.references:
        target = skill.references_dir / f"{name}.md"
        if not target.is_file() or target.read_text(encoding="utf-8") != _render(name):
            drifted.append(f"{skill.package}/{skill.slug}:{name}")
    return drifted


def _skill_summary(skill: PortableSkill) -> dict:
    return {
        "package": skill.package,
        "slug": skill.slug,
        "references": list(skill.references),
    }


def _run_list(skills: tuple[PortableSkill, ...]) -> None:
    print(json.dumps([_skill_summary(skill) for skill in skills]))


def _run_check(skills: tuple[PortableSkill, ...]) -> None:
    drifted: list[str] = []
    for skill in skills:
        drifted.extend(_drifted_references(skill))
    if drifted:
        raise SystemExit(
            "generated portable references drifted: "
            + ", ".join(drifted)
            + "; run python3 tools/sync-portable-references.py"
        )
    print(
        f"portable references match their canonical agents for {len(skills)} skill(s)"
    )


def _run_generate(skills: tuple[PortableSkill, ...]) -> None:
    generated = 0
    for skill in skills:
        if not skill.references:
            continue
        skill.references_dir.mkdir(parents=True, exist_ok=True)
        for name in skill.references:
            (skill.references_dir / f"{name}.md").write_text(
                _render(name), encoding="utf-8"
            )
            generated += 1
    print(f"generated {generated} portable reference(s) across {len(skills)} skill(s)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the discovered portable skills as JSON and exit",
    )
    args = parser.parse_args()

    skills = discover_portable_skills()
    if not skills:
        raise SystemExit(
            "no skill declares a `portable:` frontmatter block "
            "(expected at least evidence-synthesis)"
        )

    if args.list:
        _run_list(skills)
    elif args.check:
        _run_check(skills)
    else:
        _run_generate(skills)


if __name__ == "__main__":
    main()
