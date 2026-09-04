"""Build the two condition prompts for a task. Only the representation
changes between conditions (design doc, constraint 5): the same fixture,
the same task instruction, and the same tool grant are held constant; the
prompt tells the session either to perform the procedure itself (inline
skill) or to dispatch it via the Agent tool to the named subagent
(full subagent spawn).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPromptSpec:
    """Parameter object for the two prompt builders below (coding-standards
    §4.4: more than 4 parameters is a missing data type)."""
    repo_root: str
    skill_name: str
    primary_agent: str
    task_instruction: str
    fixture_path: str


def skill_procedure_text(repo_root: str, skill_name: str) -> str:
    """Precondition: tools/skill-runner.sh exists at repo_root and resolves
    skill_name. Postcondition: returns the printed procedure + zetetic
    gates exactly as skill-runner.sh emits them -- this benchmark never
    hand-copies a skill's procedure, since a hand-copy could drift from
    what a real /skill:run invocation would show a calling session.

    ZETETIC_SKILLS/ZETETIC_AGENTS are pinned to repo_root's own skills/
    and agents/ dirs -- skill-runner.sh's default resolution order checks
    ~/.claude/skills BEFORE the git root, which would silently read the
    installed plugin's skills instead of the worktree under test."""
    env = dict(os.environ)
    env["ZETETIC_SKILLS"] = os.path.join(repo_root, "skills")
    env["ZETETIC_AGENTS"] = os.path.join(repo_root, "agents")
    result = subprocess.run(
        ["tools/skill-runner.sh", skill_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout


def build_inline_prompt(spec: TaskPromptSpec) -> str:
    procedure = skill_procedure_text(spec.repo_root, spec.skill_name)
    return (
        f"{procedure}\n\n"
        "---\n"
        "Apply the procedure above yourself, in this current session, to the following task. "
        "Do not use the Agent tool to delegate any part of this to a subagent -- perform the "
        "work directly.\n\n"
        f"Task:\n{spec.task_instruction}\n\n"
        f"The relevant file is at: {spec.fixture_path}\n"
    )


def build_subagent_prompt(spec: TaskPromptSpec) -> str:
    return (
        f"Use the Agent tool to delegate the following task to the `{spec.primary_agent}` subagent. "
        "Do not perform the analysis yourself in this session -- dispatch it and return the "
        "subagent's output verbatim.\n\n"
        f"Task:\n{spec.task_instruction}\n\n"
        f"The relevant file is at: {spec.fixture_path}\n"
    )
