"""CLI-level (main()) tests for the tools.goa scripts — the argument-parsing,
file I/O and exit-code paths that the pure-function unit tests above do not
exercise. One end-to-end happy path plus the documented error exit codes per
script, matching the exit-code contract each module's docstring declares.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.goa import (
    assemble_fixture,
    build_labeler_batches,
    ci_no_raw_corpus_text,
    concordance_gate,
    dedupe_minhash,
    fixture_freeze_gate,
    readonly_slice_reference,
    sample_ntsb,
    sample_stackexchange,
    validate_labeler_output,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "goa" / "synthetic"


def test_sample_stackexchange_main_writes_candidates(tmp_path):
    out = tmp_path / "candidates.jsonl"
    shape_map = tmp_path / "map.json"
    shape_map.write_text(
        json.dumps({"shapes": {"causal-audit": {"corpus": "stackexchange", "site": "s", "tags": ["causality"]}}}),
        encoding="utf-8",
    )
    rc = sample_stackexchange.main(
        [
            "--posts-xml",
            str(FIXTURES / "Posts.xml"),
            "--shape",
            "causal-audit",
            "--shape-map",
            str(shape_map),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.is_file()


def test_sample_stackexchange_main_usage_error_on_unknown_shape(tmp_path):
    shape_map = tmp_path / "map.json"
    shape_map.write_text(json.dumps({"shapes": {}}), encoding="utf-8")
    rc = sample_stackexchange.main(
        [
            "--posts-xml",
            str(FIXTURES / "Posts.xml"),
            "--shape",
            "nonexistent",
            "--shape-map",
            str(shape_map),
            "--out",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 2


def test_sample_ntsb_main_writes_candidates(tmp_path):
    out = tmp_path / "candidates.jsonl"
    rc = sample_ntsb.main(
        [
            "--export",
            str(FIXTURES / "ntsb_occurrences.synthetic.csv"),
            "--shape",
            "failure-forensics",
            "--text-field",
            "narrative",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.is_file()


def test_sample_ntsb_main_no_candidates_survive(tmp_path):
    empty_export = tmp_path / "empty.csv"
    empty_export.write_text("occurrence_id,narrative\n", encoding="utf-8")
    rc = sample_ntsb.main(
        ["--export", str(empty_export), "--shape", "failure-forensics", "--text-field", "narrative", "--out", str(tmp_path / "out.jsonl")]
    )
    assert rc == 3


def _write_candidates(path: Path) -> None:
    rows = [
        {
            "case_id": f"c{i}",
            "shape": "causal-audit",
            "corpus": "stackexchange",
            "text": f"unique invented text number {i} about causal audits",
            "provenance": {
                "corpus": "stackexchange",
                "source_id": f"s{i}",
                "license": "CC BY-SA 4.0",
                "site_or_dataset": "stats.SE",
                "tags": ["causality"],
                "score": i,
            },
        }
        for i in range(3)
    ]
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_dedupe_minhash_main_writes_deduped_output(tmp_path):
    candidates = tmp_path / "candidates.jsonl"
    _write_candidates(candidates)
    out = tmp_path / "deduped.jsonl"
    rc = dedupe_minhash.main(["--in", str(candidates), "--out", str(out)])
    assert rc == 0
    assert out.is_file()


def test_build_labeler_batches_main_writes_blind_batch(tmp_path):
    candidates = tmp_path / "candidates.jsonl"
    _write_candidates(candidates)
    out = tmp_path / "batch.jsonl"
    rc = build_labeler_batches.main(["--candidates", str(candidates), "--out", str(out)])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert set(row) == {"case_id", "text"}


def _label_row(case_id: str, label: str) -> dict:
    return {"case_id": case_id, "label": label, "confidence": 0.9, "rationale": "r"}


def test_validate_labeler_output_main_valid_file(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps(_label_row("c0", "causal-audit")), encoding="utf-8")
    assert validate_labeler_output.main(["--labels", str(labels)]) == 0


def test_validate_labeler_output_main_invalid_file(tmp_path):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"case_id": "c0"}), encoding="utf-8")
    assert validate_labeler_output.main(["--labels", str(labels)]) == 1


def test_validate_labeler_output_main_missing_file(tmp_path):
    assert validate_labeler_output.main(["--labels", str(tmp_path / "absent.jsonl")]) == 2


def test_concordance_gate_main_stage1_and_stage2(tmp_path):
    labeler_a = tmp_path / "a.jsonl"
    labeler_b = tmp_path / "b.jsonl"
    labeler_c = tmp_path / "c.jsonl"
    labeler_a.write_text("\n".join(json.dumps(r) for r in [_label_row("c0", "causal-audit"), _label_row("c1", "estimation")]), encoding="utf-8")
    labeler_b.write_text("\n".join(json.dumps(r) for r in [_label_row("c0", "causal-audit"), _label_row("c1", "boundary-design")]), encoding="utf-8")
    agreed_out = tmp_path / "agreed.jsonl"
    disagreements_out = tmp_path / "disagreements.jsonl"
    rc = concordance_gate.main(
        [
            "--labeler-a", str(labeler_a), "--labeler-b", str(labeler_b),
            "--emit-agreed", str(agreed_out), "--emit-disagreements", str(disagreements_out),
        ]
    )
    assert rc == 0
    assert json.loads(agreed_out.read_text().splitlines()[0])["case_id"] == "c0"

    labeler_c.write_text(json.dumps(_label_row("c1", "estimation")), encoding="utf-8")
    adjudicated_out = tmp_path / "adjudicated.jsonl"
    discarded_out = tmp_path / "discarded.jsonl"
    rc2 = concordance_gate.main(
        [
            "--labeler-a", str(labeler_a), "--labeler-b", str(labeler_b), "--labeler-c", str(labeler_c),
            "--emit-adjudicated", str(adjudicated_out), "--emit-discarded", str(discarded_out),
        ]
    )
    assert rc2 == 0
    assert json.loads(adjudicated_out.read_text().splitlines()[0])["label"] == "estimation"


def test_concordance_gate_main_no_common_cases(tmp_path):
    labeler_a = tmp_path / "a.jsonl"
    labeler_b = tmp_path / "b.jsonl"
    labeler_a.write_text(json.dumps(_label_row("c0", "causal-audit")), encoding="utf-8")
    labeler_b.write_text(json.dumps(_label_row("other", "causal-audit")), encoding="utf-8")
    rc = concordance_gate.main(["--labeler-a", str(labeler_a), "--labeler-b", str(labeler_b)])
    assert rc == 3


def test_assemble_fixture_main_writes_and_grows(tmp_path):
    candidates = tmp_path / "candidates.jsonl"
    _write_candidates(candidates)
    agreed = tmp_path / "agreed.jsonl"
    agreed.write_text(json.dumps({"case_id": "c0", "label": "causal-audit"}), encoding="utf-8")
    out = tmp_path / "external_testbase_v1.json"
    rc = assemble_fixture.main(["--candidates", str(candidates), "--agreed", str(agreed), "--out", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["manifest"]["row_count"] == 1

    agreed2 = tmp_path / "agreed2.jsonl"
    agreed2.write_text(json.dumps({"case_id": "c1", "label": "estimation"}), encoding="utf-8")
    rc2 = assemble_fixture.main(["--candidates", str(candidates), "--agreed", str(agreed2), "--out", str(out)])
    assert rc2 == 0
    payload2 = json.loads(out.read_text(encoding="utf-8"))
    assert payload2["manifest"]["row_count"] == 2


def test_readonly_slice_reference_main_writes_reference_rows(tmp_path):
    local_input = tmp_path / "local.jsonl"
    local_input.write_text(
        json.dumps({"source_id": "s1", "license": "BSD-3-Clause", "corpus": "swebench", "text": "issue body text"}),
        encoding="utf-8",
    )
    out = tmp_path / "swebench_readonly_reference.jsonl"
    rc = readonly_slice_reference.main(["--local-input", str(local_input), "--out", str(out)])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert "text" not in row


def test_ci_no_raw_corpus_text_main_reports_clean_or_dirty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run(["git", "init", "-q", "."], check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "config", "user.name", "t"], check=True)
    (tmp_path / "external_testbase_v1.json").write_text(
        json.dumps({"rows": [{"case_id": "a1", "source_id": "s1", "license": "L", "features": {}}]}),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "t"], check=True)
    rc = ci_no_raw_corpus_text.main(["--repo-root", str(tmp_path)])
    assert rc == 0


def _git(cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return result.stdout


def _init_git_repo(cwd: Path) -> None:
    _git(cwd, "init", "-q", ".")
    _git(cwd, "config", "user.email", "t@e.com")
    _git(cwd, "config", "user.name", "t")


def test_fixture_freeze_gate_main_no_fixtures_tracked(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "t")
    rc = fixture_freeze_gate.main(["--repo-root", str(tmp_path)])
    assert rc == 0


def test_fixture_freeze_gate_main_detects_append_and_violation(tmp_path):
    _init_git_repo(tmp_path)
    fixture_path = tmp_path / "external_testbase_v1.json"
    fixture_path.write_text(
        json.dumps({"manifest": {"row_count": 1}, "rows": [{"case_id": "a1", "label": "causal-audit"}]}),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD").strip()

    # pure append -> exit 0
    fixture_path.write_text(
        json.dumps(
            {
                "manifest": {"row_count": 2},
                "rows": [
                    {"case_id": "a1", "label": "causal-audit"},
                    {"case_id": "a2", "label": "estimation"},
                ],
            }
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "append")
    rc_append = fixture_freeze_gate.main(["--repo-root", str(tmp_path), "--pr-base-sha", base_sha])
    assert rc_append == 0

    # modify an existing row on top of the append -> exit 1
    fixture_path.write_text(
        json.dumps(
            {
                "manifest": {"row_count": 2},
                "rows": [
                    {"case_id": "a1", "label": "CHANGED"},
                    {"case_id": "a2", "label": "estimation"},
                ],
            }
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "modify")
    rc_modified = fixture_freeze_gate.main(["--repo-root", str(tmp_path), "--pr-base-sha", base_sha])
    assert rc_modified == 1


def test_fixture_freeze_gate_main_resolves_base_ref_from_head_caret(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "external_testbase_v1.json").write_text(
        json.dumps({"manifest": {"row_count": 1}, "rows": [{"case_id": "a1", "label": "x"}]}), encoding="utf-8"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "second")
    # no --pr-base-sha given: falls back to HEAD^, which IS the commit that
    # introduced the fixture unchanged, so this must still pass.
    rc = fixture_freeze_gate.main(["--repo-root", str(tmp_path)])
    assert rc == 0
