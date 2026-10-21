#!/usr/bin/env python3
"""Wall-time of every hook in hooks/hooks.json, warm, against its configured timeout.

Usage: scripts/measure-hook-latency.py [--runs N] [--only SUBSTRING] [--markdown FILE]

Each hook runs once unmeasured (warm-up: page cache, .pyc) and then N times
measured, with a representative stdin payload for its event. State is isolated:
HOME is a scratch directory seeded with a copy of ~/.claude/memories, and the
working directory is a scratch `git clone` of this repo, so a Stop hook never
writes the real session store and the worktree sweep never touches a real
worktree. The table (median, max, configured timeout) is written to --markdown
after EACH hook so an interrupted run keeps what it measured.

source: issue-less owner request 2026-10-14, thresholds: median > 1 s on a hot
path (UserPromptSubmit / PreToolUse / PostToolUse), > 3 s at SessionStart.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOT = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"}
HOT_LIMIT_S = 1.0  # source: owner request 2026-10-14
START_LIMIT_S = 3.0  # source: owner request 2026-10-14
DEFAULT_TIMEOUT = "none (host default)"

Hook = namedtuple("Hook", "event matcher when spec")  # one hooks.json command entry
Sandbox = namedtuple("Sandbox", "home repo transcript")  # isolated HOME, cwd, transcript


def tool_input(matcher, when):
    """A representative tool call for a matcher group; `when` selects git verbs."""
    if "git push" in when:
        return "Bash", {"command": "git push origin fix/x"}
    if "git commit" in when:
        return "Bash", {"command": 'git commit -m "fix: x"'}
    first = matcher.split("|")[0] if matcher else "Bash"
    if first in ("Edit", "Write"):
        return first, {"file_path": "scratch/a.py", "old_string": "a", "new_string": "b",
                       "content": "x = 1\n"}
    if first in ("WebFetch", "WebSearch"):
        return first, {"url": "https://example.com", "query": "x"}
    return "Bash", {"command": "ls"}


def payload(hook, sandbox):
    event = hook.event
    name, tin = tool_input(hook.matcher, hook.when)
    base = {"session_id": "measure-0001", "transcript_path": str(sandbox.transcript),
            "cwd": str(sandbox.repo), "hook_event_name": event}
    if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        base.update(tool_name=name, tool_input=tin)
        if event == "PostToolUse":
            base["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
        if event == "PostToolUseFailure":
            base["error"] = "exit 1"
    elif event == "UserPromptSubmit":
        base["prompt"] = "fix the failing test in the parser"
    elif event in ("Stop", "SubagentStop"):
        base.update(stop_hook_active=False, agent_id="a1", agent_type="general-purpose",
                    last_assistant_message="done")
    elif event == "Notification":
        base.update(message="needs input", notification_type="idle_prompt")
    elif event == "SessionStart":
        base["source"] = "startup"
    return json.dumps(base)


def entries():
    spec = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    for event, groups in spec.items():
        for group in groups:
            for spec in group["hooks"]:
                yield Hook(event, group.get("matcher", ""), group.get("when", ""), spec)


def scratch(base):
    home = base / "home"
    home.mkdir()
    mem = Path.home() / ".claude" / "memories"
    if mem.is_dir():
        shutil.copytree(mem, home / ".claude" / "memories", symlinks=True)
    repo = base / "repo"
    subprocess.run(["git", "clone", "-q", "--local", str(ROOT), str(repo)], check=True)
    (repo / "scratch").mkdir()
    (repo / "scratch" / "a.py").write_text("a = 1\n")
    transcript = base / "transcript.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    return Sandbox(home, repo, transcript)


def time_once(command, stdin, env, cwd):
    start = time.perf_counter()
    done = subprocess.run(["bash", "-c", command], input=stdin, text=True,
                          capture_output=True, env=env, cwd=cwd)
    return time.perf_counter() - start, done.returncode


def row(hook, sandbox, runs):
    command = hook.spec["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
    stdin = payload(hook, sandbox)
    env = {**os.environ, "HOME": str(sandbox.home), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    time_once(command, stdin, env, sandbox.repo)  # warm-up
    samples = [time_once(command, stdin, env, sandbox.repo) for _ in range(runs)]
    secs = [t for t, _ in samples]
    limit = (START_LIMIT_S if hook.event == "SessionStart"
             else HOT_LIMIT_S if hook.event in HOT else None)
    median = statistics.median(secs)
    over = limit is not None and median > limit
    script = (command.replace(str(ROOT) + "/hooks/", "").replace('"', "")
              .replace("run-python.sh ", ""))
    label = (script + (f" [{hook.when}]" if hook.when else "")
             + (f" ({hook.matcher.replace('|', '/')})" if hook.matcher else ""))
    return (hook.event, label, median, max(secs), hook.spec.get("timeout"),
            sorted({rc for _, rc in samples}), over)


def render(rows, runs):
    out = [f"| Event | Hook | median s | max s | timeout s | rc | over limit |",
           "|---|---|---|---|---|---|---|"]
    for event, label, med, mx, timeout, rcs, over in rows:
        t = timeout if timeout is not None else DEFAULT_TIMEOUT
        out.append(f"| {event} | `{label}` | {med:.3f} | {mx:.3f} | {t} | {rcs} | "
                   f"{'YES' if over else 'no'} |")
    return f"{runs} measured runs per hook after 1 warm-up.\n\n" + "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--only", default="")
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="hook-latency.") as tmp:
        sandbox = scratch(Path(tmp))
        for hook in entries():
            if args.only not in hook.spec["command"] and args.only not in hook.event:
                continue
            rows.append(row(hook, sandbox, args.runs))
            if args.markdown:
                args.markdown.write_text(render(rows, args.runs))
    print(render(rows, args.runs))


if __name__ == "__main__":
    main()
