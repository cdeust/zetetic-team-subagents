"""The once-only bootstrap controller is limited to the owner's explicit inventory."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ci_codex_review_controller.py"
SHA = "a" * 40  # Synthetic immutable head fixture.


def load():
    spec = importlib.util.spec_from_file_location("review_controller", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControllerTests(unittest.TestCase):
    def invoke(self, inventory, flags=()):
        module = load()
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory.json"
            path.write_text(json.dumps(inventory))
            with (
                patch.object(module.reconcile, "discover", return_value=[dict(number=7, sha=SHA)]) as discover,
                patch.object(module.reconcile.events, "resume", return_value=dict(action="request")) as resume,
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
            ):
                code = module.main(["--once", "--inventory", str(path), *flags])
        return code, out.getvalue(), err.getvalue(), discover.call_args_list, resume.call_args_list

    def test_once_dry_run_is_explicit_and_never_authorizes_writes(self):
        result = self.invoke(dict(owner="cdeust", repositories=["cdeust/Cortex"]), ["--dry-run"])
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(result[3][0].args, ("cdeust/Cortex",))
        self.assertEqual(result[4][0].kwargs, dict(dry_run=True))
        self.assertEqual(result[4][0].args[1], dict(number=7, sha=SHA, run_id=None))

    def test_inventory_rejects_foreign_repos_duplicates_and_malformed_names(self):
        for repos in (["other/Cortex"], ["cdeust/Cortex", "cdeust/Cortex"], ["cdeust/.."]):
            result = self.invoke(dict(owner="cdeust", repositories=repos))
            self.assertEqual(result[0], 1)
            self.assertEqual(result[3], [])
            self.assertEqual(result[4], [])

    def test_one_repo_api_error_does_not_starve_other_inventory_repos(self):
        module = load()
        with patch.object(module.reconcile, "discover", side_effect=[module.EvidenceError("api"), []]):
            result = module.once(["cdeust/Cortex", "cdeust/claude-mods"], dry_run=True)
        self.assertEqual(result, [dict(repository="cdeust/Cortex", error="api")])

    def test_worker_environment_is_restored_after_each_server_derived_pr(self):
        with patch.dict(os.environ, {"EXPECTED_PR": "original"}):
            result = self.invoke(dict(owner="cdeust", repositories=["cdeust/Cortex"]))
            self.assertEqual(result[0], 0, result[2])
            self.assertEqual(os.environ["EXPECTED_PR"], "original")
        self.assertEqual(result[4][0].kwargs, dict(dry_run=False))


if __name__ == "__main__":
    unittest.main()
