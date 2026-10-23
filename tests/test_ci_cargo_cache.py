"""Cargo reuse must not change bare-runner or coverage acceptance semantics."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / "templates/ci/pipeline.yml"
PIN = "55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
PATHS = {
    "target",
    "~/.cargo/registry/index",
    "~/.cargo/registry/cache",
    "~/.cargo/git/db",
}


def test_cargo_caches_are_limited_to_compilation_jobs():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    caches = [
        (job, step)
        for job, config in jobs.items()
        for step in config["steps"]
        if step.get("uses", "").startswith("actions/cache")
    ]
    assert [job for job, _ in caches] == ["unit", "unit", "regression", "e2e"]
    for _, step in caches:
        assert step["uses"].endswith("@" + PIN)
        assert "hashFiles('Cargo.lock') != ''" in step["if"]
        assert set(step["with"]["path"].splitlines()) == PATHS


def test_cache_keys_separate_jobs_toolchains_config_and_dependencies():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for job in ("unit", "regression", "e2e"):
        step = next(
            s
            for s in jobs[job]["steps"]
            if s.get("uses", "").startswith("actions/cache")
        )
        key = step["with"]["key"]
        fallback = step["with"]["restore-keys"].strip()
        for expression in ("runner.os", "runner.arch", "github.job"):
            assert "${{ " + expression + " }}" in key
            assert "${{ " + expression + " }}" in fallback
        for path in (
            "rust-toolchain",
            "rust-toolchain.toml",
            ".cargo/config",
            ".cargo/config.toml",
            "ci.json",
        ):
            assert f"'{path}'" in fallback
        assert key == fallback + "${{ hashFiles('Cargo.lock') }}"
        command = next(
            i
            for i, s in enumerate(jobs[job]["steps"])
            if s.get("name") == f"Run the {job} command"
        )
        assert jobs[job]["steps"].index(step) < command


def test_unit_saves_only_successful_build_before_enforcing_coverage():
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["unit"]["steps"]
    restore = next(
        s for s in steps if s.get("uses", "").startswith("actions/cache/restore@")
    )
    save = next(s for s in steps if s.get("uses", "").startswith("actions/cache/save@"))
    run = next(s for s in steps if s.get("name") == "Run the unit command")
    coverage = next(s for s in steps if s.get("name") == "Enforce the coverage floor")
    assert (
        steps.index(restore)
        < steps.index(run)
        < steps.index(save)
        < steps.index(coverage)
    )
    assert save["if"].startswith("success() && ")
    assert f"steps.{restore['id']}.outputs.cache-hit != 'true'" in save["if"]
    assert (
        save["with"]["key"]
        == "${{ steps." + restore["id"] + ".outputs.cache-primary-key }}"
    )
    assert "python3 - coverage.xml --min 90" in coverage["run"]
