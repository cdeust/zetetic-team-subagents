"""Replay SEC-010 in a disposable Ubuntu checkout with RUNNER_TEMP set.

Requires Git history, ShellCheck 0.11.0, zizmor 1.31.1, OpenSSH and ci.json's runner dependencies.
Run with python3 tests/replay_release_credentials.py from the repository root.
"""

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
# source: SEC-010 candidate baseline recorded in the upstream port note.
BEFORE = "30b13ce81c60727fd3f206052a98f757baea0fdc"
PUBLISH_TEST = Path("tests/test_ci_tag_publish.py")
WORKFLOW = Path(".github/workflows/pipeline.yml")


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def verify_before(python, runner_temp):
    with tempfile.TemporaryDirectory(dir=runner_temp) as tmp:
        before = Path(tmp)
        for path in (PUBLISH_TEST, WORKFLOW):
            (before / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / PUBLISH_TEST, before / PUBLISH_TEST)
        (before / WORKFLOW).write_bytes(subprocess.check_output(["git", "show", f"{BEFORE}:{WORKFLOW}"]))
        report = before / "junit.xml"
        args = [python, "-m", "pytest", "-q", str(PUBLISH_TEST), "-k", "release_credential_lifetime",
                "--junitxml", str(report)]
        result = subprocess.run(args, cwd=before, capture_output=True, text=True)
        cases = ET.parse(report).findall(".//testcase")
        failures = {c.get("name"): c.find("failure") for c in cases}
        expected = {f"test_release_credential_lifetime[{code}]" for code in (0, 1)}
        if result.returncode != 1 or set(failures) != expected or any(f is None for f in failures.values()):
            raise RuntimeError(f"Expected both lifetime cases to fail on {BEFORE}\n{result.stdout}")
        if any("write identity available outside publication" not in f.get("message", "")
               or "Fetch the tested commit into a bare repository" not in f.get("message", "")
               for f in failures.values()):
            raise RuntimeError(f"The baseline failed for an unexpected reason\n{result.stdout}")
        print(f"Baseline {BEFORE}: both credential lifetime cases failed as expected (pytest exit 1).", flush=True)


def workflow_findings(directory, files):
    command = ["zizmor", "--offline", "--no-config", "--no-exit-codes", "--format", "json", *files]
    findings = json.loads(subprocess.check_output(command, cwd=directory))
    # Locations move when the workflow grows. The symbolic route identifies the affected step.
    counts = Counter()
    for item in findings:
        routes = [loc["symbolic"] for loc in item["locations"]]
        counts[item["ident"], item["determinations"]["severity"], json.dumps(routes, sort_keys=True)] += 1
    return counts


def verify_static(files, runner_temp):
    actionlint = runner_temp / "venv/bin/actionlint"
    if subprocess.check_output([actionlint, "-version"], text=True).splitlines()[0] != "1.7.12":
        raise RuntimeError("Expected hash-locked actionlint-py to supply actionlint 1.7.12")
    if "version: 0.11.0" not in subprocess.check_output(["shellcheck", "--version"], text=True).splitlines():
        raise RuntimeError("Expected ShellCheck 0.11.0")
    run([actionlint, "-shellcheck", "shellcheck", *files])
    if subprocess.check_output(["zizmor", "--version"], text=True).strip() != "zizmor 1.31.1":
        raise RuntimeError("Expected zizmor 1.31.1")
    with tempfile.TemporaryDirectory(dir=runner_temp) as tmp:
        before = Path(tmp)
        for path in files:
            (before / path).parent.mkdir(parents=True, exist_ok=True)
            (before / path).write_bytes(subprocess.check_output(["git", "show", f"{BEFORE}:{path}"]))
        old = workflow_findings(before, files)
    current = workflow_findings(ROOT, files)
    if current - old:
        raise RuntimeError(f"New zizmor findings: {current - old}")
    print(f"zizmor: {old.total()} baseline, {current.total()} current, 0 new.", flush=True)


def main():
    os.chdir(ROOT)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    commands = json.loads((ROOT / "ci.json").read_text())
    run(["bash", "-eo", "pipefail", "-c", commands["unit"]])
    python = runner_temp / "venv/bin/python"
    verify_before(python, runner_temp)
    run([python, "-m", "pytest", "-q", str(PUBLISH_TEST), "-k", "release_credential_lifetime"])
    files = [Path(".github/workflows") / (name + ".yml") for name in
             ("codeql", "release", "pipeline", "pipeline-post-merge")]
    verify_static([*files, *sorted(Path("templates/ci").rglob("pipeline.yml"))], runner_temp)
    run(["bash", "-eo", "pipefail", "-c", commands["regression"]])


if __name__ == "__main__":
    main()
