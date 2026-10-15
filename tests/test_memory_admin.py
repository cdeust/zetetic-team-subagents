"""tools/lib/memory_admin.py: the ttl-sweep and audit helpers of memory-tool.sh.

They were heredocs inside two 100+ line shell functions; the report must stay
byte-for-byte what the heredoc printed.
"""

from pathlib import Path
import datetime
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import memory_admin  # noqa: E402

EPOCH_2026 = 1767225600  # source: 2026-01-01T00:00:00Z, computed with `date -u -d`


def _line(epoch, **fields):
    """One audit-log line; `fields` override agent, scope, cmd, result, size."""
    f = {"agent": "a", "scope": "s", "cmd": "create", "result": "ok", "size": 10, **fields}
    stamp = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "\t".join([stamp, f["agent"], f["scope"], f["cmd"], f"/memories/{f['scope']}/f",
                      str(f["size"]), "", f["result"]])


def _report(tmp_path, lines, cutoff=0, capsys=None):
    log = tmp_path / "audit.log"
    log.write_text("\n".join(lines) + "\n")
    memory_admin.audit_report(str(log), cutoff)
    return capsys.readouterr().out


@pytest.mark.parametrize("value, expected", [
    ("2026-01-01T00:00:00Z", EPOCH_2026),
    ("2026-01-01", EPOCH_2026),
    ("2026-01-01T00:00:00+00:00", EPOCH_2026),
    ("2026-01-01T00:00:00", EPOCH_2026),
    ("garbage", None),
    ("", None),
])
def test_since_epoch(value, expected):
    assert memory_admin.since_epoch(value) == expected


def test_ttl_pairs_lists_explicit_ttls_then_unlisted_scopes_under_a_default(tmp_path, monkeypatch, capsys):
    (tmp_path / "mem" / "kept").mkdir(parents=True)
    (tmp_path / "mem" / "listed").mkdir()
    (tmp_path / "mem" / ".hidden").mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "defaults": {"ttl_days": 30},
        "scopes": {"listed": {"ttl_days": 7}, "forever": {"ttl_days": None}, "silent": {}},
    }))
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "mem"))
    memory_admin.ttl_pairs(str(registry))
    assert capsys.readouterr().out.splitlines() == ["listed 7", "kept 30"]


def test_audit_report_empty_window(tmp_path, capsys):
    out = _report(tmp_path, [_line(100)], cutoff=200, capsys=capsys)
    assert out == "No audit entries in the requested window.\n"


def test_audit_report_skips_malformed_lines_and_filters_by_cutoff(tmp_path, capsys):
    out = _report(tmp_path, ["short\tline", "", "not-a-date\ta\ts\tc\tv\t1\t\tok",
                             _line(EPOCH_2026 - 1), _line(EPOCH_2026, agent="kept")],
                  cutoff=EPOCH_2026, capsys=capsys)
    assert "=== Audit log (1 entries) ===" in out
    assert "kept" in out


def test_audit_report_counts_writes_denials_and_top_agents(tmp_path, capsys):
    lines = [_line(EPOCH_2026, agent="big", size=500), _line(EPOCH_2026 + 1, agent="big", cmd="view"),
             _line(EPOCH_2026 + 2, agent="bad", result="acl_denied")]
    out = _report(tmp_path, lines, capsys=capsys)
    assert "Total writes in window : 2" in out  # the view is read-only
    assert "ACL denials            : 1" in out
    assert "agent=bad scope=s : 1" in out
    assert out.index("big") < out.index("bytes", out.index("Top 5 agents"))
    assert "No anomalies detected." in out


def test_burst_anomaly_needs_more_than_fifty_writes_in_an_hour():
    fifty = [{"cmd": "create", "scope": "s", "epoch": EPOCH_2026 + i} for i in range(50)]
    assert memory_admin.burst_anomalies(fifty) == []
    found = memory_admin.burst_anomalies(fifty + [{"cmd": "create", "scope": "s", "epoch": EPOCH_2026 + 50}])
    assert found == ["  [ANOMALY] scope 's': 51 writes in 1-hour window starting 00:00:00Z"]
    spread = [{"cmd": "create", "scope": "s", "epoch": EPOCH_2026 + 3601 * i} for i in range(60)]
    assert memory_admin.burst_anomalies(spread) == []  # one write per window


def test_burst_anomaly_ignores_read_only_commands():
    reads = [{"cmd": "view", "scope": "s", "epoch": EPOCH_2026 + i} for i in range(60)]
    assert memory_admin.burst_anomalies(reads) == []


def test_spread_anomaly_needs_more_than_three_scopes():
    def writes(n):
        return [{"cmd": "create", "agent": "a", "scope": f"s{i}"} for i in range(n)]
    assert memory_admin.spread_anomalies(writes(3)) == []
    assert memory_admin.spread_anomalies(writes(4)) == [
        "  [ANOMALY] agent 'a' wrote to 4 scopes: ['s0', 's1', 's2', 's3']"]


def test_denial_anomaly_fires_on_the_fifth_consecutive_denial_only():
    def run(results):
        return [{"agent": "a", "epoch": i, "result": r} for i, r in enumerate(results)]
    assert memory_admin.denial_anomalies(run(["acl_denied"] * 4)) == []
    assert len(memory_admin.denial_anomalies(run(["acl_denied"] * 5))) == 1
    assert memory_admin.denial_anomalies(run(["acl_denied"] * 4 + ["ok"] + ["acl_denied"] * 4)) == []


def test_files_near_limit_reports_files_at_ninety_percent(tmp_path, monkeypatch):
    (tmp_path / "mem" / "s").mkdir(parents=True)
    (tmp_path / "mem" / "s" / "big").write_bytes(b"x" * 1850)
    (tmp_path / "mem" / "s" / "small").write_bytes(b"x" * 1800)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"scopes": {"s": {"max_file_kb": 2}, "absent": {}}}))
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "mem"))
    monkeypatch.setenv("MEMORY_REGISTRY", str(registry))
    assert memory_admin.files_near_limit() == [("s", "big", 1850 / 1024, 2)]


def test_files_near_limit_is_empty_without_a_readable_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_REGISTRY", str(tmp_path / "absent.json"))
    assert memory_admin.files_near_limit() == []
    (tmp_path / "broken.json").write_text("{")
    monkeypatch.setenv("MEMORY_REGISTRY", str(tmp_path / "broken.json"))
    assert memory_admin.files_near_limit() == []


def test_burst_window_includes_a_write_exactly_one_hour_later():
    writes = [{"cmd": "create", "scope": "s", "epoch": EPOCH_2026 + i} for i in range(50)]
    writes.append({"cmd": "create", "scope": "s", "epoch": EPOCH_2026 + 3600})
    assert len(memory_admin.burst_anomalies(writes)) == 1


def test_denial_anomaly_is_reported_once_per_streak():
    streak = [{"agent": "a", "epoch": i, "result": "acl_denied"} for i in range(6)]
    assert len(memory_admin.denial_anomalies(streak)) == 1


def test_a_file_exactly_at_ninety_percent_is_near_the_limit(tmp_path, monkeypatch):
    (tmp_path / "mem" / "s").mkdir(parents=True)
    (tmp_path / "mem" / "s" / "f").write_bytes(b"x" * 9216)  # 9.0 KB of a 10 KB cap
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"scopes": {"s": {"max_file_kb": 10}}}))
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "mem"))
    monkeypatch.setenv("MEMORY_REGISTRY", str(registry))
    assert memory_admin.files_near_limit() == [("s", "f", 9.0, 10)]


def test_scope_cap_defaults_to_one_hundred_kb(tmp_path, monkeypatch):
    (tmp_path / "mem" / "s").mkdir(parents=True)
    (tmp_path / "mem" / "s" / "f").write_bytes(b"x" * 9728)  # 9.5 KB: near a 10 KB cap, far from 100
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"scopes": {"s": {}}}))
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "mem"))
    monkeypatch.setenv("MEMORY_REGISTRY", str(registry))
    assert memory_admin.files_near_limit() == []


def test_top_agents_are_the_five_largest(tmp_path, capsys):
    lines = [_line(EPOCH_2026 + i, agent=f"agent{i}", size=1000 - i) for i in range(6)]
    out = _report(tmp_path, lines, capsys=capsys)
    top = out[out.index("Top 5 agents"):]
    assert "agent4" in top and "agent5" not in top


def test_entry_needs_eight_fields_and_an_empty_size_counts_as_zero(tmp_path, capsys):
    seven = "\t".join(_line(EPOCH_2026, agent="seven").split("\t")[:7])
    empty_size = "\t".join(_line(EPOCH_2026, agent="empty").split("\t")[:5] + ["", "", "ok"])
    out = _report(tmp_path, [seven, empty_size], capsys=capsys)
    assert "=== Audit log (1 entries) ===" in out
    assert "empty" in out and "seven" not in out
    assert "empty" in out[out.index("Top 5 agents"):] and " 0 bytes" in out


def test_main_reports_an_invalid_since_value_with_a_failing_status(capsys):
    assert memory_admin.main(["since", "garbage"]) == 1
    assert capsys.readouterr().err == "error\n"
    assert memory_admin.main(["since", "2026-01-01"]) == 0
    assert capsys.readouterr().out == f"{EPOCH_2026}\n"
