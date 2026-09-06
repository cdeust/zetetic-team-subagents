"""Contract tests for every cross-harness portable skill package.

Generalized (Phase 5 of the agent-to-skill migration plan): this used to
hardcode a single package (`zetetic-reasoning` / `evidence-synthesis`).
Packages and their skills are now discovered from
`tools/sync-portable-references.py --list`, which reads the `portable:`
frontmatter each canonical skill source opts in with (see that script's
module docstring). Adding a third packaged skill means adding a `portable:`
block to its source file -- these tests then cover it automatically, with no
test file edited by hand.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HOST_COUPLING = re.compile(r"\b(?:claude|hooks?|mcp)\b", re.IGNORECASE)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frontmatter_keys(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    return {
        line.split(":", 1)[0]
        for line in frontmatter.splitlines()
        if line and not line.startswith((" ", "\t"))
    }


def _load_skill(path: Path) -> dict:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---\n", 2)[1])
    reference_names = set(re.findall(r"\(references/([a-z-]+\.md)\)", text))
    references = {
        name: (path / "references" / name).read_text(encoding="utf-8")
        for name in reference_names
    }
    return {
        "name": frontmatter["name"],
        "description": frontmatter["description"],
        "instructions": text.split("---\n", 2)[2],
        "references": references,
    }


def _discover_portable_skills() -> list[dict]:
    result = subprocess.run(
        ["python3", "tools/sync-portable-references.py", "--list"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


PORTABLE_SKILLS = _discover_portable_skills()
PACKAGES = sorted({skill["package"] for skill in PORTABLE_SKILLS})
SKILL_IDS = [f"{skill['package']}/{skill['slug']}" for skill in PORTABLE_SKILLS]
EVIDENCE_SYNTHESIS = next(
    skill for skill in PORTABLE_SKILLS if skill["slug"] == "evidence-synthesis"
)


def test_discovery_finds_at_least_the_known_packaged_skills() -> None:
    # A regression guard on the discovery mechanism itself: if `portable:`
    # frontmatter parsing silently breaks, every other test in this file
    # would just as silently stop covering anything.
    assert {"zetetic-reasoning", "zetetic-design"} <= set(PACKAGES)
    assert {"evidence-synthesis", "design"} <= {
        skill["slug"] for skill in PORTABLE_SKILLS
    }


@pytest.mark.parametrize("skill", PORTABLE_SKILLS, ids=SKILL_IDS)
def test_required_portable_files_exist(skill: dict) -> None:
    package_dir = ROOT / "plugins" / skill["package"]
    skill_dir = package_dir / "skills" / skill["slug"]
    required = {
        package_dir / ".codex-plugin" / "plugin.json",
        package_dir / "gemini-extension.json",
        package_dir / "README.md",
        skill_dir / "SKILL.md",
        skill_dir / "agents" / "openai.yaml",
    }
    assert all(path.is_file() for path in required)


@pytest.mark.parametrize("package", PACKAGES)
def test_codex_manifest_declares_only_the_skill_surface(package: str) -> None:
    manifest = _json(ROOT / "plugins" / package / ".codex-plugin" / "plugin.json")
    assert manifest["name"] == package
    assert SEMVER.fullmatch(manifest["version"])
    assert manifest["skills"] == "./skills/"
    assert not ({"hooks", "mcpServers", "apps", "postInstall"} & manifest.keys())


@pytest.mark.parametrize("package", PACKAGES)
def test_gemini_manifest_matches_codex_identity(package: str) -> None:
    package_dir = ROOT / "plugins" / package
    codex = _json(package_dir / ".codex-plugin" / "plugin.json")
    gemini = _json(package_dir / "gemini-extension.json")
    assert set(gemini) == {"name", "version", "description"}
    assert gemini["name"] == codex["name"]
    assert gemini["version"] == codex["version"]
    assert SEMVER.fullmatch(gemini["version"])


def test_repo_marketplace_points_to_the_isolated_packages() -> None:
    marketplace = _json(ROOT / ".agents" / "plugins" / "marketplace.json")
    assert marketplace["name"] == "zetetic-marketplace"
    entries = {entry["name"]: entry for entry in marketplace["plugins"]}
    assert set(entries) == set(PACKAGES)
    for package in PACKAGES:
        entry = entries[package]
        assert entry["source"] == {
            "source": "local",
            "path": f"./plugins/{package}",
        }
        assert entry["policy"] == {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        }
        assert entry["category"]


@pytest.mark.parametrize("skill", PORTABLE_SKILLS, ids=SKILL_IDS)
def test_skill_frontmatter_is_portable(skill: dict) -> None:
    skill_md = (
        ROOT / "plugins" / skill["package"] / "skills" / skill["slug"] / "SKILL.md"
    )
    assert _frontmatter_keys(skill_md) == {"name", "description"}


@pytest.mark.parametrize("skill", PORTABLE_SKILLS, ids=SKILL_IDS)
def test_skill_links_exactly_the_vendored_references(skill: dict) -> None:
    skill_dir = ROOT / "plugins" / skill["package"] / "skills" / skill["slug"]
    reference_dir = skill_dir / "references"
    expected = set(skill["references"])
    if not expected:
        # A skill with no genius-agent references (e.g. `design`, which is
        # self-contained) must not carry a leftover/unused references dir.
        assert not reference_dir.is_dir()
        return
    assert {path.stem for path in reference_dir.glob("*.md")} == expected
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    links = set(re.findall(r"\(references/([a-z-]+)\.md\)", skill_text))
    assert links == expected
    assert all((reference_dir / f"{link}.md").is_file() for link in links)


@pytest.mark.parametrize("skill", PORTABLE_SKILLS, ids=SKILL_IDS)
def test_codex_and_gemini_host_layouts_load_the_complete_skill(
    skill: dict, tmp_path: Path
) -> None:
    package = ROOT / "plugins" / skill["package"]
    skill_source = package / "skills" / skill["slug"]

    codex_plugin = tmp_path / "codex" / "plugins" / skill["package"]
    shutil.copytree(package, codex_plugin)
    codex_manifest = _json(codex_plugin / ".codex-plugin" / "plugin.json")
    codex_skill = (codex_plugin / codex_manifest["skills"] / skill["slug"]).resolve()

    gemini_skill = tmp_path / "gemini" / "skills" / skill["slug"]
    shutil.copytree(skill_source, gemini_skill)

    loaded = {
        "codex": _load_skill(codex_skill),
        "gemini-cli": _load_skill(gemini_skill),
    }
    assert loaded["codex"] == loaded["gemini-cli"]
    expected_references = {f"{name}.md" for name in skill["references"]}
    for host, loaded_skill in loaded.items():
        assert loaded_skill["name"] == skill["slug"], host
        assert set(loaded_skill["references"]) == expected_references, host


def test_every_reference_has_multiple_traceable_sources() -> None:
    for skill in PORTABLE_SKILLS:
        reference_dir = (
            ROOT / "plugins" / skill["package"] / "skills" / skill["slug"] / "references"
        )
        if not reference_dir.is_dir():
            continue
        for path in reference_dir.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            assert "## Primary" in text
            assert text.count("\n- ") >= 2


def test_evidence_synthesis_requires_sources_uncertainty_blind_spots_and_refusal() -> None:
    # This is a content contract specific to evidence-synthesis's zetetic
    # method, not a shape every packaged skill shares (a design audit does
    # not phrase itself in terms of "counter-evidence"). Scoped to that one
    # skill deliberately -- see the module docstring for what IS generalized.
    skill_md = (
        ROOT
        / "plugins"
        / EVIDENCE_SYNTHESIS["package"]
        / "skills"
        / EVIDENCE_SYNTHESIS["slug"]
        / "SKILL.md"
    )
    text = skill_md.read_text(encoding="utf-8").casefold()
    required_phrases = {
        "primary source",
        "independent",
        "counter-evidence",
        "uncertainty and blind spots",
        "refuse or stop",
        "i don't know",
        "do not invent",
    }
    assert all(phrase in text for phrase in required_phrases)


@pytest.mark.parametrize("package", PACKAGES)
def test_portable_package_contains_no_host_specific_runtime_tokens(package: str) -> None:
    package_dir = ROOT / "plugins" / package
    text_files = [
        path
        for path in package_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md", ".yaml", ".yml"}
    ]
    violations = {
        str(path.relative_to(package_dir)): HOST_COUPLING.findall(
            path.read_text(encoding="utf-8")
        )
        for path in text_files
        if HOST_COUPLING.search(path.read_text(encoding="utf-8"))
    }
    assert violations == {}


def test_release_bundle_includes_every_portable_package() -> None:
    script = (ROOT / "tools" / "build-release-bundle.sh").read_text(encoding="utf-8")
    assert ".agents/plugins/marketplace.json" in script
    for package in PACKAGES:
        assert f"plugins/{package}" in script


def test_portable_references_are_generated_from_canonical_agents() -> None:
    subprocess.run(
        ["python3", "tools/sync-portable-references.py", "--check"],
        cwd=ROOT,
        check=True,
    )
