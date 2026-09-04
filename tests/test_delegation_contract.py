"""Contract tests for tools/delegation_contract.py — the fail-closed
pre-mutation oracle scripts/spawn-agent.sh calls before creating a worktree.

Closes HC-ZETETIC-004 (mechanical-delegation-preconditions): every invalid
fixture must be denied with a stable, named reason and never reach a
mutation; every valid control must pass. Fixtures live in
tools/tests/delegation-contract/ as the shared valid/invalid corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import delegation_contract as dc  # noqa: E402

FIXTURE_DIR = ROOT / "tools" / "tests" / "delegation-contract"


def _materialize(fixture_name: str, target_repo: Path) -> Path:
    """Substitute {{TARGET_REPO}} in a fixture and write it under target_repo's
    parent tmp dir, returning the materialized contract path."""
    raw = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    filled = raw.replace("{{TARGET_REPO}}", str(target_repo))
    out = target_repo.parent / f"materialized-{fixture_name}"
    out.write_text(filled, encoding="utf-8")
    return out


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    """A minimal fake target repo containing agents/engineer.md, so
    unknown-agent vs. known-agent resolution is exercised for real."""
    repo = tmp_path / "target"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "engineer.md").write_text("---\nname: engineer\n---\nbody\n", encoding="utf-8")
    (repo / "src").mkdir()
    return repo


def test_valid_contract_launches(target_repo: Path) -> None:
    contract_path = _materialize("fixture-valid.json", target_repo)
    contract = dc.validate(contract_path, target_repo)
    assert contract["agent"] == "engineer"
    assert contract["push_authority"] == "forbidden"


@pytest.mark.parametrize(
    "fixture_name,expected_reason",
    [
        ("fixture-invalid-missing-push-authority.json", "missing_required_field"),
        ("fixture-invalid-path-escapes-repo.json", "path_escapes_repo"),
        ("fixture-invalid-unknown-agent.json", "unknown_agent"),
        ("fixture-invalid-empty-owned-paths.json", "empty_owned_paths"),
        ("fixture-invalid-missing-acceptance-oracle.json", "empty_acceptance_oracle"),
        ("fixture-invalid-missing-pr-number-handback.json", "missing_pr_number_handback"),
    ],
)
def test_invalid_contract_denied_with_stable_reason(
    target_repo: Path, fixture_name: str, expected_reason: str
) -> None:
    contract_path = _materialize(fixture_name, target_repo)
    with pytest.raises(dc.ContractError) as exc_info:
        dc.validate(contract_path, target_repo)
    assert exc_info.value.reason == expected_reason


def test_malformed_json_denied(target_repo: Path) -> None:
    contract_path = FIXTURE_DIR / "fixture-malformed.json"
    with pytest.raises(dc.ContractError) as exc_info:
        dc.validate(contract_path, target_repo)
    assert exc_info.value.reason == "malformed_json"


def test_overlapping_ownership_denied(target_repo: Path) -> None:
    contract_path = _materialize("fixture-valid.json", target_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    # Simulate an already-active delegation owning an overlapping glob.
    lock_dir = target_repo / ".claude" / "delegation-locks"
    lock_dir.mkdir(parents=True)
    active = dict(contract)
    active["owned_paths"] = ["src/**"]
    (lock_dir / "active.json").write_text(json.dumps(active), encoding="utf-8")

    with pytest.raises(dc.ContractError) as exc_info:
        dc.validate(contract_path, target_repo)
    assert exc_info.value.reason == "overlapping_ownership"


def test_disjoint_ownership_proceeds(target_repo: Path) -> None:
    (target_repo / "docs").mkdir()
    contract_path = _materialize("fixture-valid.json", target_repo)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    lock_dir = target_repo / ".claude" / "delegation-locks"
    lock_dir.mkdir(parents=True)
    active = dict(contract)
    active["owned_paths"] = ["docs/**"]  # disjoint from "src/**"
    (lock_dir / "active.json").write_text(json.dumps(active), encoding="utf-8")

    # Must not raise — disjoint owned_paths always proceed.
    dc.validate(contract_path, target_repo)


def test_register_and_release_active_lock(target_repo: Path) -> None:
    contract_path = _materialize("fixture-valid.json", target_repo)
    contract = dc.validate(contract_path, target_repo)
    lock_path = dc.register_active(contract, "engineer-test-001", target_repo)
    assert lock_path.is_file()
    dc.release_active(lock_path)
    assert not lock_path.exists()


def test_cli_exits_zero_on_valid(target_repo: Path) -> None:
    import subprocess

    contract_path = _materialize("fixture-valid.json", target_repo)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "delegation_contract.py"), str(contract_path), "--repo-root", str(target_repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "launch"


def test_cli_exits_nonzero_on_invalid(target_repo: Path) -> None:
    import subprocess

    contract_path = _materialize("fixture-invalid-missing-push-authority.json", target_repo)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "delegation_contract.py"), str(contract_path), "--repo-root", str(target_repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["decision"] == "deny"
    assert payload["reason"] == "missing_required_field"
