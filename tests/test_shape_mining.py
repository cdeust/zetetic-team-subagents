"""Miner contracts on disposable transcripts; never read users' session history."""

import json

import pytest

from tools import mine_shape_cases as miner


def turn(text, **extra):
    return {
        "type": "user",
        "message": {"content": text},
        "sessionId": "session-a",
        "uuid": "turn-a",
        "timestamp": "2026-10-23T00:00:00Z",
        "cwd": "/fixture/project",
        "gitBranch": "feature/example",
        **extra,
    }


def transcript(root, name, rows):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_mining_preserves_provenance_and_accounts_for_every_rejected_turn(tmp_path):
    root = tmp_path / "corpus"
    text = "Find why the café checkout rejects valid payments"
    path = transcript(
        root,
        "project/session.jsonl",
        [
            turn(text),
            turn("  FIND why the café checkout rejects valid payments  "),
            turn("agent task", isSidechain=True),
            turn("metadata", isMeta=True),
            turn("done", type="assistant"),
            turn(None),
            turn("<task-notification>complete</task-notification>"),
            turn("Resume from: checkpoint.md"),
            turn("[Image #1] explain this"),
            turn("ok"),
            turn("x" * 101),
        ],
    )
    with path.open("a") as stream:
        stream.write("{broken json\n")
    candidates, drops = miner.mine([path], root, miner.Limits(10, 100))
    assert len(candidates) == 1
    assert candidates[0]["text"] == text
    assert candidates[0]["chars"] == len(text)
    assert candidates[0]["provenance"] == {
        "project": "project",
        "session_id": "session-a",
        "turn_uuid": "turn-a",
        "timestamp": "2026-10-23T00:00:00Z",
        "cwd": "/fixture/project",
        "git_branch": "feature/example",
    }
    assert dict(drops) == {
        reason: 1
        for reason in (
            "duplicate-text",
            "subagent-turn",
            "meta-turn",
            "not-a-user-turn",
            "no-text-content",
            "machine-generated-turn",
            "machine-generated-prefix",
            "image-dependent-turn",
            "too-short",
            "too-long",
            "unparseable-line",
        )
    }


def test_mixed_content_keeps_only_authored_text_and_allows_quoted_checkpoint():
    content = [
        {"type": "text", "text": "Explain why"},
        {"type": "tool_result", "content": "tool output must not become a case"},
        {"type": "image", "source": {}},
        None,
        {"type": "text", "text": "Resume from: appears in my log"},
    ]
    obj = turn(content)
    text = miner.extract_text(obj)
    assert text == "Explain why Resume from: appears in my log"
    assert miner.drop_reason(obj, text, miner.Limits(1, len(text))) is None


def test_cli_draw_is_deterministic_and_growth_does_not_relabel_old_cases(
    tmp_path, capsys
):
    root = tmp_path / "corpus"
    transcript(
        root,
        "kept/a.jsonl",
        [turn(f"Diagnose failure in component {i}") for i in range(6)],
    )
    transcript(
        root, "kept/a/subagents/nested.jsonl", [turn("not human", isSidechain=True)]
    )
    transcript(root, "private-project/a.jsonl", [turn("must not be sampled")])
    first, again, growth = [
        tmp_path / f"out/{name}.jsonl" for name in ("first", "again", "growth")
    ]
    args = [
        "--transcripts",
        str(root),
        "--min-chars",
        "1",
        "--sample",
        "2",
        "--seed",
        "17",
        "--exclude-project",
        "private",
    ]
    assert miner.main([*args, "--out", str(first)]) == 0
    assert miner.main([*args, "--out", str(again)]) == 0
    assert first.read_bytes() == again.read_bytes()
    assert len(read_rows(first)) == 2
    assert miner.main([*args, "--out", str(growth), "--exclude-ids", str(first)]) == 0
    old_ids = {row["case_id"] for row in read_rows(first)}
    assert old_ids.isdisjoint(row["case_id"] for row in read_rows(growth))
    assert all(row["provenance"]["project"] == "kept" for row in read_rows(growth))
    stderr = capsys.readouterr().err
    assert "already-drawn" in stderr and "subagent-turn" in stderr


def test_sample_is_independent_of_input_order_and_full_draw_is_sorted():
    cases = [{"case_id": name} for name in ("d", "a", "c", "b")]
    assert miner.sample(cases, 2, 17) == miner.sample(list(reversed(cases)), 2, 17)
    expected = [{"case_id": name} for name in ("a", "b", "c", "d")]
    assert miner.sample(cases, 0, 17) == expected
    assert miner.sample(cases, len(cases), 17) == expected


@pytest.mark.parametrize("exists,expected", [(False, 2), (True, 3)])
def test_cli_missing_or_empty_corpus_never_creates_success_output(
    tmp_path, capsys, exists, expected
):
    root, out = tmp_path / "corpus", tmp_path / "result.jsonl"
    if exists:
        root.mkdir()
    assert miner.main(["--transcripts", str(root), "--out", str(out)]) == expected
    assert not out.exists()
    assert (
        "no candidate" if exists else "no such directory"
    ) in capsys.readouterr().err


def test_prior_draw_can_have_blank_lines_and_multiple_files(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text('\n{"case_id":"first"}\n')
    b.write_text('{"case_id":"second"}\n{"case_id":"first"}\n')
    assert miner.read_case_ids([a, b]) == {"first", "second"}
