"""Agreement and adjudication must preserve disagreement, not silently label it."""

import json
import math

import pytest

from tools import score_shape_labels as scorer


def labels(tmp_path, name, values):
    path = tmp_path / f"{name}.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"case_id": case, "label": label})
            for case, label in values.items()
        )
        + "\n"
    )
    return str(path)


def test_cli_reports_common_set_and_writes_majorities_separately_from_splits(
    tmp_path, capsys
):
    raters = {
        "alice": {
            "same": "chain",
            "majority": "tree",
            "split": "chain",
            "alone": "none",
        },
        "bob": {"same": "chain", "majority": "tree", "split": "tree"},
        "carol": {"same": "chain", "majority": "graph", "split": "graph"},
    }
    args = []
    for name, values in raters.items():
        args.extend(["--rater", f"{name}={labels(tmp_path, name, values)}"])
    settled, splits = tmp_path / "out/settled.jsonl", tmp_path / "out/splits.jsonl"
    assert scorer.main([*args, "--settled", str(settled), "--splits", str(splits)]) == 0
    rows = [json.loads(line) for line in settled.read_text().splitlines()]
    assert [(r["case_id"], r["label"], r["margin"]) for r in rows] == [
        ("majority", "tree", "2/3"),
        ("same", "chain", "3/3"),
    ]
    assert rows[0]["votes"] == {"alice": "tree", "bob": "tree", "carol": "graph"}
    assert json.loads(splits.read_text()) == {
        "case_id": "split",
        "votes": {"alice": "chain", "bob": "tree", "carol": "graph"},
    }
    report = capsys.readouterr().out
    assert "cases labelled by every rater: 3" in report
    assert "rater alice: 4 labelled (1 outside the common set)" in report
    assert "Fleiss kappa (3 raters)" in report
    assert "settled by majority: 2" in report and "needing arbitration: 1" in report


def test_batched_rater_deduplicates_identical_votes_but_rejects_conflicts(tmp_path):
    a = labels(tmp_path, "a", {"one": "tree"})
    b = labels(tmp_path, "b", {"one": "tree", "two": "chain"})
    with open(a, "a") as stream:
        stream.write("\n")
    assert scorer.load_rater_labels([f"r={a}", f"r={b}"]) == {
        "r": {"one": "tree", "two": "chain"}
    }
    c = labels(tmp_path, "c", {"one": "graph"})
    with pytest.raises(ValueError, match="conflicting labels for one"):
        scorer.load_rater_labels([f"r={a}", f"r={c}"])


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (["x", "y"], ["x", "y"], 1),
        (["x", "y"], ["y", "x"], -1),
        (["x", "x", "y", "y"], ["x", "y", "x", "y"], 0),
    ],
)
def test_cohen_kappa_perfect_opposite_and_chance_agreement(a, b, expected):
    # Balanced labels give chance agreement 1/2; observed is 1, 0, or 1/2.
    assert scorer.cohen_kappa(a, b) == pytest.approx(expected)


def test_fleiss_matches_hand_counted_agreement():
    # Three voters, two cases. Each row has 2 agreeing out of 6 ordered pairs;
    # the balanced marginals give Pe=1/2, so kappa=(1/3-1/2)/(1-1/2)=-1/3.
    assert scorer.fleiss_kappa([["x", "x", "y"], ["y", "y", "x"]]) == pytest.approx(
        -1 / 3
    )
    assert scorer.fleiss_kappa([["x"] * 3, ["y"] * 3]) == pytest.approx(1)


@pytest.mark.parametrize("rows", [[], [["x"]], [["x", "y"], ["x"]], [["x", "x"]]])
def test_fleiss_undefined_samples_do_not_claim_agreement(rows):
    assert math.isnan(scorer.fleiss_kappa(rows))


@pytest.mark.parametrize("a,b", [([], []), (["x"], ["x"])])
def test_cohen_undefined_samples_do_not_claim_agreement(a, b):
    assert math.isnan(scorer.cohen_kappa(a, b))


def test_routability_counts_do_not_hide_shape_disagreement_behind_none():
    assert scorer.routable_split(
        ["none", "tree", "tree", "none"],
        ["none", "tree", "graph", "chain"],
    ) == {
        "both_none": 1,
        "routable_by_either": 3,
        "routable_by_both": 2,
        "shape_agreed": 1,
    }


def test_even_vote_tie_requires_arbitration_regardless_of_rater_order():
    votes = {"a": {"case": "tree"}, "b": {"case": "chain"}}
    for ordered in (votes, dict(reversed(list(votes.items())))):
        settled, splits = scorer.adjudicate(ordered, ["case"])
        assert settled == []
        assert splits == [{"case_id": "case", "votes": {"a": "tree", "b": "chain"}}]


@pytest.mark.parametrize(
    "spec", ["missing-equals", "=missing-name", "r=/nonexistent/fixture"]
)
def test_cli_rejects_unreadable_or_invalid_rater_spec(spec, capsys):
    assert scorer.main(["--rater", spec]) == 2
    assert "score_shape_labels:" in capsys.readouterr().err


def test_cli_rejects_malformed_labels_and_missing_raters(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{broken\n")
    assert scorer.main(["--rater", f"r={bad}"]) == 2
    good = labels(tmp_path, "good", {"one": "tree"})
    assert scorer.main(["--rater", f"r={good}"]) == 2
    assert "need at least two raters" in capsys.readouterr().err


def test_cli_disjoint_labels_do_not_write_adjudication(tmp_path, capsys):
    a, b = (
        labels(tmp_path, "a", {"one": "tree"}),
        labels(tmp_path, "b", {"two": "tree"}),
    )
    out = tmp_path / "settled.jsonl"
    assert (
        scorer.main(["--rater", f"a={a}", "--rater", f"b={b}", "--settled", str(out)])
        == 3
    )
    assert not out.exists()
    assert "no case labelled by every rater" in capsys.readouterr().err
    assert scorer.common_cases({}) == []


def test_none_only_report_keeps_routable_rate_defined(tmp_path, capsys):
    a = labels(tmp_path, "a", {"one": "none"})
    assert scorer.main(["--rater", f"a={a}", "--rater", f"b={a}"]) == 0
    report = capsys.readouterr().out
    assert "Cohen kappa           nan" in report
    assert "0.000 of routable" in report
    assert "Fleiss" not in report
