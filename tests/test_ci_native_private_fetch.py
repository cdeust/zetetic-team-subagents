"""The pinned claude-code-action can fetch the PR head of a private repository.

source: claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb
src/modes/tag/index.ts#L79 runs setupBranch, whose `git fetch origin <sha>`
(src/github/operations/branch.ts#L241, #L350, #L368) precedes the action's own
git authentication (index.ts#L112, #L125, #L135). With the checkout token not
persisted, that fetch is anonymous: public repositories pass, a private one
fails with "could not read Username" (cdeust/ci-autonome job 123331564638).
git-config.ts#L78-L81 then unsets the local `http.<server>/.extraheader`
before Claude runs, so the bridge header must live in that exact key.
"""
import base64
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from scripts.lib import render_ci as renderer

BRIDGE = "Authorize pinned action fetch"
WORKFLOWS = [
    (".github/workflows/claude-review.yml", "review"),
    (".github/workflows/claude.yml", "claude"),
]


def steps_of(tmp_path, relative, job):
    files = renderer.prepare_files(tmp_path, native_review=True)
    return yaml.safe_load(files[tmp_path / relative])["jobs"][job]["steps"]


def index_of(steps, predicate):
    return next(i for i, step in enumerate(steps) if predicate(step))


@pytest.mark.parametrize("relative,job", WORKFLOWS)
def test_fetch_authorization_sits_between_checkout_and_action(tmp_path, relative, job):
    steps = steps_of(tmp_path, relative, job)
    checkout = index_of(steps, lambda s: s.get("uses", "").startswith("actions/checkout@"))
    bridge = index_of(steps, lambda s: s.get("name") == BRIDGE)
    action = index_of(steps, lambda s: "claude-code-action@" in s.get("uses", ""))
    assert checkout < bridge < action
    # The checkout token is still not persisted by actions/checkout itself.
    assert steps[checkout]["with"]["persist-credentials"] is False
    assert steps[bridge]["env"] == {"FETCH_TOKEN": "${{ github.token }}"}


class Recorder(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):  # noqa: N802 - http.server dispatch name
        Recorder.seen.append(self.headers.get("Authorization"))
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        return


def ls_remote(repo, env):
    return subprocess.run(["git", "ls-remote", "origin"], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("relative,job", WORKFLOWS)
def test_bridge_authenticates_fetch_until_the_action_replaces_it(tmp_path, relative, job):
    bridge = next(s for s in steps_of(tmp_path, relative, job) if s.get("name") == BRIDGE)
    server = HTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server_url = f"http://127.0.0.1:{server.server_address[1]}"
    repo = tmp_path / "workspace"
    env = {**os.environ, "GITHUB_SERVER_URL": server_url, "FETCH_TOKEN": "tok",
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}
    try:
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        subprocess.run(["git", "remote", "add", "origin", f"{server_url}/o/r"],
                       cwd=repo, check=True, env=env)
        Recorder.seen = []
        result = subprocess.run(["bash", "-e", "-c", bridge["run"]], cwd=repo, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        ls_remote(repo, env)
        expected = base64.b64encode(b"x-access-token:tok").decode()
        assert Recorder.seen and Recorder.seen[0] == f"basic {expected}"
        # The pinned action's removal (git-config.ts#L78-L81), before Claude runs.
        subprocess.run(["git", "config", "--unset-all", f"http.{server_url}/.extraheader"],
                       cwd=repo, check=True, env=env)
        Recorder.seen = []
        ls_remote(repo, env)
        assert Recorder.seen and Recorder.seen[0] is None
    finally:
        server.shutdown()
        server.server_close()
