"""Executed-file provenance binds successful job names to a trusted definition.

IDs, SHAs and server replies are synthetic fixtures with GitHub's API shape.
"""
import base64
from pathlib import Path

import pytest

from test_ci_native_gate import FakeGitHub, SHA, jobs, resolve, resolver
from tools import ci_workflow_proof as proof


class DefinitionAPI(FakeGitHub):
    def __init__(self):
        super().__init__(SHA, SHA, "merge")
        self.run["node_id"] = "synthetic-run-node"
        self.actual, self.installed = b"trusted definition", b"trusted definition"
        self.published = b"generated upgrade"
        self.node = {
            "databaseId": 9, "runAttempt": 1,
            "file": {"repositoryName": "o/r", "path": proof.WORKFLOW,
                     "repositoryFileUrl": f"https://github.com/o/r/blob/{SHA}/{proof.WORKFLOW}"},
        }
        self.graphql = {"data": {"node": self.node}}

    def request(self, method, path, body=None):
        if path == "/graphql":
            self.calls.append((method, path))
            assert method == "POST"
            assert body["variables"] == {"id": "synthetic-run-node"}
            return self.graphql
        if "/contents/" in path:
            self.calls.append((method, path))
            if proof.PUBLISHED in path:
                content = self.published
            else:
                content = self.installed if path.endswith("ref=refs%2Fheads%2Fmain") else self.actual
            return {"type": "file", "encoding": "base64",
                    "content": base64.b64encode(content).decode()}
        if method == "PUT":
            self.calls.append((method, path))
            self.pr.update(merged=True, merge_commit_sha="b" * 40)
            return {"merged": True, "sha": "b" * 40}
        if "/compare/" in path:
            self.calls.append((method, path))
            return {"status": "identical", "merge_base_commit": {"sha": "b" * 40}}
        return super().request(method, path, body)


def test_fake_pipeline_with_realistic_success_metadata_cannot_merge(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = DefinitionAPI()
    api.actual = b"fake pipeline emitting all expected successful job names"
    assert all(job["conclusion"] == "success" for job in api.jobs)
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        resolve(module, api)
    assert api.merges() == []


def test_normal_code_pr_uses_authoritative_executed_definition(jobs, tmp_path):
    api = DefinitionAPI()
    assert resolve(resolver(jobs, tmp_path), api)["run_tests"] == "true"
    assert len(api.merges()) == 1
    assert ("POST", "/graphql") in api.calls
    assert not any(proof.SOURCE in path for _, path in api.calls)


def test_generated_ci_upgrade_is_authorized_without_owner_intervention(jobs, tmp_path):
    api = DefinitionAPI()
    api.published = (Path(__file__).resolve().parents[1] / proof.PUBLISHED).read_bytes()
    api.actual = api.published
    assert resolve(resolver(jobs, tmp_path), api)["run_tests"] == "true"
    assert len(api.merges()) == 1
    assert any(proof.SOURCE in path for _, path in api.calls)


@pytest.mark.parametrize("changes", [
    {"databaseId": 8}, {"runAttempt": 2}, {"file": None},
    {"file": {"repositoryName": "outsider/r", "path": proof.WORKFLOW}},
    {"file": {"repositoryName": "o/r", "path": ".github/workflows/fake.yml"}},
    {"file": {"repositoryName": "o/r", "path": proof.WORKFLOW,
              "repositoryFileUrl": f"https://evil.invalid/o/r/blob/{SHA}/{proof.WORKFLOW}"}},
    {"file": {"repositoryName": "o/r", "path": proof.WORKFLOW,
              "repositoryFileUrl": f"https://github.com/o/r/blob/main/{proof.WORKFLOW}"}},
])
def test_server_provenance_must_match_exact_run_and_definition(jobs, tmp_path, changes):
    module, api = resolver(jobs, tmp_path), DefinitionAPI()
    api.node.update(changes)
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        resolve(module, api)
    assert api.merges() == []


@pytest.mark.parametrize("reply", [{}, {"errors": [{"message": "denied"}]},
                                  {"data": {"node": None}}])
def test_unreadable_provenance_fails_closed(jobs, tmp_path, reply):
    module, api = resolver(jobs, tmp_path), DefinitionAPI()
    api.graphql = reply
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        resolve(module, api)
    assert api.merges() == []


def test_missing_node_id_cannot_authorize_merge(jobs, tmp_path):
    module, api = resolver(jobs, tmp_path), DefinitionAPI()
    del api.run["node_id"]
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        resolve(module, api)
    assert api.merges() == []


def test_provenance_does_not_infer_definition_from_pr_head(jobs, tmp_path):
    api = DefinitionAPI()
    # Authoritative workflow file may identify a different immutable commit.
    api.node["file"]["repositoryFileUrl"] = f"https://github.com/o/r/blob/{'c'*40}/{proof.WORKFLOW}"
    assert resolve(resolver(jobs, tmp_path), api)["run_tests"] == "true"
    assert any("ref=" + "c" * 40 in path for _, path in api.calls)


def test_embedded_verifier_matches_reviewable_source(jobs, tmp_path):
    assert resolver(jobs, tmp_path).WORKFLOW_PROOF_SOURCE.lstrip("\n") == (
        Path(__file__).resolve().parents[1] / "tools/ci_workflow_proof.py").read_text()


def test_published_definition_matches_current_renderer():
    from scripts.lib import render_ci
    root = Path(__file__).resolve().parents[1]
    assert (root / proof.PUBLISHED).read_text() == render_ci.artifacts(native_review=True)["pipeline.yml"]


@pytest.mark.parametrize("entry", [
    {"type": "symlink", "encoding": "base64", "content": "eA=="},
    {"type": "file", "encoding": "none", "content": ""},
    {"type": "file", "encoding": "base64", "content": "not base64!!"},
])
def test_malformed_definition_content_fails_closed(jobs, tmp_path, entry):
    module, api = resolver(jobs, tmp_path), DefinitionAPI()
    request = api.request
    api.request = lambda method, path, body=None: (
        entry if "/contents/" in path else request(method, path, body))
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        resolve(module, api)
    assert api.merges() == []


def test_pr_event_cannot_override_live_executed_file(jobs, tmp_path):
    module, api = resolver(jobs, tmp_path), DefinitionAPI()
    api.actual = b"fake successful checks"
    event = {"repository": {"full_name": "o/r"}, "workflow_run": {
        **api.run, "file": {"repositoryFileUrl": "trusted"}, "node_id": "forged"}}
    with pytest.raises(module.PostMergeError, match="workflow proof"):
        module.resolve(event, "o/r", api)
    assert api.merges() == []


def test_reviewable_helper_itself_authorizes_same_fixture():
    api = DefinitionAPI()
    proof.authorize_workflow(api.run, "o/r", api, ValueError)
    api.actual = api.published
    proof.authorize_workflow(api.run, "o/r", api, ValueError)
    api.actual = b"forged"
    with pytest.raises(ValueError, match="workflow proof"):
        proof.authorize_workflow(api.run, "o/r", api, ValueError)


def test_graphql_and_contents_use_real_request_json_boundary(jobs, tmp_path, monkeypatch):
    from io import BytesIO
    import json
    from urllib.parse import urlsplit
    module, server = resolver(jobs, tmp_path), DefinitionAPI()
    server.actual = server.published
    seen = []
    def open_request(request):
        assert request.get_header("Authorization") == "Bearer synthetic-fixture-token"
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "api.github.com"
        path = url.path + ("?" + url.query if url.query else "")
        body = json.loads(request.data) if request.data else None
        seen.append((request.method, path, body))
        if "/jobs?" in path:
            response = {"jobs": list(server.records(path, "jobs"))}
        else:
            response = server.request(request.method, path, body)
        return BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(module, "urlopen", open_request)
    event = {"repository": {"full_name": "o/r"}, "workflow_run": dict(server.run)}
    assert module.resolve(event, "o/r", module.GitHub("synthetic-fixture-token"))["run_tests"] == "true"
    assert any(method == "POST" and path == "/graphql" and
               body["variables"] == {"id": "synthetic-run-node"}
               for method, path, body in seen)
    assert any(proof.SOURCE in path and path.endswith("ref=refs%2Fheads%2Fmain")
               for _, path, _ in seen)
    assert len(server.merges()) == 1


def test_hosted_probe_uses_identical_transport_and_read_only_permissions(jobs, tmp_path):
    import ast
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/workflow-definition-api.yml').read_text())
    assert workflow['permissions'] == {'contents': 'read', 'actions': 'read'}
    steps = workflow['jobs']['workflow-definition-api']['steps']
    assert not any('uses' in step for step in steps)
    script = steps[0]['run'].split("python3 - <<'API_PROBE'\n")[1].rsplit('API_PROBE', 1)[0]
    namespace = {'__name__': 'probe_fixture'}
    exec(compile(script, 'probe_fixture', 'exec'), namespace)
    assert namespace['RUN_FILE_QUERY'] == proof.RUN_FILE_QUERY
    probe_class = next(node for node in ast.parse(script).body if isinstance(node, ast.ClassDef) and node.name == 'GitHub')
    command = jobs['resolve']['steps'][0]['run']
    native = command.split("python3 - <<'PY'\n")[1].rsplit('PY', 1)[0]
    native_class = next(node for node in ast.parse(native).body if isinstance(node, ast.ClassDef) and node.name == 'GitHub')
    assert ast.dump(probe_class) == ast.dump(native_class)
