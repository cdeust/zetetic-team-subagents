"""Subagent reflection, Hindsight retain: configured / not configured / down / refused / bounded (#153)."""
# ruff: noqa: F811  (fixtures imported from reflection_support reappear as test arguments)
from __future__ import annotations

import http.server
import json
import threading

import pytest

from reflection_support import (  # noqa: F401  (fixtures are used by name)
    REPO_ROOT,
    closed_port_url,
    configure,
    fire,
    hindsight_server,
    ledger,
    no_real_hindsight,
    reflection_hindsight,
    repo,
    rows,
    server_url,
)


def test_hindsight_configured_retains_with_agent_type_and_source_tags(
        repo, fire, configure, hindsight_server):
    configure(server_url(hindsight_server))
    err = fire()
    ((path, body),) = hindsight_server.received
    assert path == "/v1/default/banks/bank-x/memories"
    (item,) = body["items"]
    assert item["tags"] == ["agent_type:engineer", "source:subagent"]
    assert item["document_id"] == "subagent-a1b2c3"
    assert "Done: fixed the bug in parser.py" in item["content"]
    assert body["async"] is True and body["operation_id"]
    assert "hindsight retained" in err
    assert rows(repo)[0]["hindsight"]["status"] == "retained"
    assert rows(repo)[0]["hindsight"]["bank"] == "bank-x"


def test_hindsight_absent_config_is_said_on_stderr_and_in_the_ledger(repo, fire):
    err = fire()
    assert "hindsight not_configured: no Hindsight config at" in err
    assert rows(repo)[0]["hindsight"]["status"] == "not_configured"


def test_hindsight_config_without_this_cwd_is_not_configured(repo, tmp_path, fire, configure):
    configure(closed_port_url(), opt_in=[str(tmp_path / "other")])
    err = fire()
    assert "under no optInPaths entry" in err
    assert rows(repo)[0]["hindsight"]["status"] == "not_configured"


def test_hindsight_server_down_is_an_error_not_silence(repo, fire, configure):
    configure(closed_port_url())
    err = fire()
    assert "hindsight error:" in err and "unreachable" in err
    row = rows(repo)[0]
    assert row["hindsight"]["status"] == "error"
    assert row["agent_id"] == "a1b2c3"  # the pending entry survives the Hindsight failure


def test_hindsight_refusal_is_an_error_naming_the_http_status(repo, fire, configure, hindsight_server):
    hindsight_server.status = 500
    configure(server_url(hindsight_server))
    assert "hindsight error: HTTP 500" in fire()
    assert rows(repo)[0]["hindsight"]["status"] == "error"


def test_hindsight_token_from_the_environment_is_sent_as_a_bearer(
        fire, configure, hindsight_server, monkeypatch):
    configure("http://127.0.0.1:1")
    monkeypatch.setenv("HINDSIGHT_API_URL", server_url(hindsight_server))
    monkeypatch.setenv("HINDSIGHT_API_TOKEN", "tok-1")
    fire()
    assert hindsight_server.auth == ["Bearer tok-1"]


@pytest.mark.parametrize("config, expected", [
    ('{"optInOnly": false, "apiUrl": "http://x"}', "names no bank"),
    ('{"optInOnly": false, "mapPathToBank": "a-string"}', "names no bank"),
    ("[]", "not a JSON object"),
    ("{not json", "unreadable"),
])
def test_hindsight_incomplete_config_is_reported_not_guessed(fire, no_real_hindsight, config, expected):
    no_real_hindsight.write_text(config, encoding="utf-8")
    err = fire()
    assert "hindsight not_configured" in err and expected in err


def test_hindsight_bank_without_an_api_url_is_reported(repo, fire, no_real_hindsight):
    no_real_hindsight.write_text(json.dumps({"mapPathToBank": {str(repo): "b"}}), encoding="utf-8")
    assert "no apiUrl in the config" in fire()


def test_the_longest_matching_path_chooses_the_bank(repo, fire, no_real_hindsight, hindsight_server):
    nested = repo / "sub"
    nested.mkdir()
    no_real_hindsight.write_text(json.dumps({
        "apiUrl": server_url(hindsight_server),
        "mapPathToBank": {str(repo): "outer", str(nested): "inner"}}), encoding="utf-8")
    fire(cwd=nested)
    assert hindsight_server.received[0][0] == "/v1/default/banks/inner/memories"


def test_a_worktree_under_an_opted_in_repo_maps_to_its_bank(repo, fire, configure, hindsight_server):
    configure(server_url(hindsight_server))
    nested = repo / ".claude" / "worktrees" / "w"
    nested.mkdir(parents=True)
    fire(cwd=nested)
    assert hindsight_server.received[0][0] == "/v1/default/banks/bank-x/memories"


def test_A_the_hindsight_step_fits_the_hook_budget_and_a_hung_post_is_abandoned(
        repo, fire, configure, monkeypatch):
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    budget = hooks["SubagentStop"][-1]["hooks"][0]["timeout"]
    assert reflection_hindsight.HINDSIGHT_DEADLINE_S + ledger.GIT_TIMEOUT_S < budget
    never = threading.Event()  # a DNS lookup that never answers: only the deadline ends the wait
    monkeypatch.setattr(reflection_hindsight, "_post_blocking", lambda *a: never.wait())
    monkeypatch.setattr(reflection_hindsight, "HINDSIGHT_DEADLINE_S", 0.05)
    configure("http://127.0.0.1:1")
    err = fire()
    never.set()
    assert "hindsight error:" in err and "no answer within" in err
    assert rows(repo)[0]["hindsight"]["status"] == "error"


@pytest.mark.parametrize("api_url", [
    "http://example.com", "http://10.0.0.5:8888", "file:///etc/passwd", "ftp://127.0.0.1",
    "127.0.0.1:8888", "https://", "http://localhost.evil.example"])
def test_D_a_non_loopback_http_or_foreign_scheme_url_is_refused_and_nothing_is_sent(
        repo, fire, configure, monkeypatch, api_url):
    def sent(*args, **kwargs):
        raise AssertionError("a request was sent")

    monkeypatch.setattr(reflection_hindsight.urllib.request, "urlopen", sent)
    monkeypatch.setenv("HINDSIGHT_API_TOKEN", "s3cret")
    configure(api_url)
    err = fire()
    assert "hindsight error:" in err and "refused" in err and "no request was sent" in err
    assert rows(repo)[0]["hindsight"]["status"] == "error"


@pytest.mark.parametrize("api_url", [
    "https://hindsight.example.com", "http://127.0.0.1:8888", "http://localhost:8888", "http://[::1]:8888"])
def test_D_https_and_loopback_http_urls_are_accepted(api_url):
    assert reflection_hindsight.check_api_url(api_url) is None


def test_D_the_bank_is_quoted_as_one_path_segment(repo, fire, no_real_hindsight, hindsight_server):
    no_real_hindsight.write_text(json.dumps({
        "apiUrl": server_url(hindsight_server), "optInOnly": False,
        "mapPathToBank": {str(repo): "a b/../c?d"}}), encoding="utf-8")
    fire()
    ((path, _),) = hindsight_server.received
    assert path == "/v1/default/banks/a%20b%2F..%2Fc%3Fd/memories"


class _Sink(http.server.BaseHTTPRequestHandler):
    """Records ANY request, any verb: the redirect target must receive none."""

    def _hit(self):
        self.server.hits.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(200)
        self.end_headers()

    do_GET = do_POST = do_PUT = _hit  # noqa: N815  (http.server API)

    def log_message(self, *args):
        pass


class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802  (http.server API)
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(self.server.code)
        self.send_header("Location", self.server.location)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def redirect_pair():
    """(redirector, sink): the redirector answers every POST with a redirect to the sink."""
    sink = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
    sink.hits = []
    redirector = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    redirector.location = server_url(sink) + "/target"
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (sink, redirector)]
    for thread in threads:
        thread.start()
    yield redirector, sink
    for server, thread in zip((sink, redirector), (threads[0], threads[1])):
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_D_a_redirect_is_refused_never_followed_and_never_gets_the_token(
        repo, fire, configure, monkeypatch, redirect_pair, code):
    redirector, sink = redirect_pair
    redirector.code = code
    monkeypatch.setenv("HINDSIGHT_API_TOKEN", "s3cret")
    configure(server_url(redirector))
    err = fire()
    assert sink.hits == []  # not even a GET: nothing was forwarded, token included
    assert "hindsight error:" in err
    outcome = rows(repo)[0]["hindsight"]
    assert outcome["status"] == "error"
    assert f"HTTP {code}" in outcome["detail"]
    assert f"redirect to {server_url(sink)}/target refused" in outcome["detail"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # SystemExit in the worker is the point
def test_a_worker_killed_by_a_non_exception_is_reported_as_dead_not_as_a_timeout(
        repo, fire, configure, monkeypatch):
    def dies(*args):
        raise SystemExit(3)

    monkeypatch.setattr(reflection_hindsight, "_post_blocking", dies)
    configure("http://127.0.0.1:1")
    err = fire()
    assert "hindsight error:" in err and "worker died without an outcome" in err
    assert "no answer within" not in err


def test_an_exception_in_the_worker_reaches_the_caller_not_the_ledger_as_a_timeout(
        repo, fire, configure, monkeypatch):
    def bug(*args):
        raise ZeroDivisionError("programming error")

    monkeypatch.setattr(reflection_hindsight, "_post_blocking", bug)
    configure("http://127.0.0.1:1")
    with pytest.raises(ZeroDivisionError):
        fire()
