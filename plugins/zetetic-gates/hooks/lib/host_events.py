"""Translate host edits into gate inputs, never applying them to the filesystem.

Patch grammar follows Codex apply_patch (Begin/End Patch, file operations,
@@ context anchors and End of File). Ambiguous or non-exact preimages fail closed:
this adapter must not approve content different from the prospective edit.
"""
from pathlib import Path


class HostEventError(ValueError):
    """The host event cannot be translated without losing edit information."""


def _path(value, cwd):
    if not isinstance(value, str) or not value.strip():
        raise HostEventError("Missing file path")
    path = Path(value)
    return str((Path(cwd) / path).resolve())


def _event(event, name, path, **fields):
    return {**event, "tool_name": name, "tool_input": {"file_path": path, **fields}}


def _read(path, state):
    if path not in state:
        try:
            state[path] = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise HostEventError(f"Cannot read patch preimage {path}: {exc}") from exc
    if state[path] is None:
        raise HostEventError(f"Patch references deleted file: {path}")
    return state[path]


def _match(lines, expected, start, end=False):
    positions = [
        i for i in range(start, len(lines) - len(expected) + 1)
        if lines[i:i + len(expected)] == expected
        and (not end or i + len(expected) == len(lines))
    ]
    if len(positions) != 1:
        reason = "ambiguous" if positions else "missing"
        raise HostEventError(f"Patch preimage is {reason}; exact unique context required")
    return positions[0]


def _hunk(body, index):
    old, new = [], []
    while index < len(body) and not body[index].startswith(("@@", "***")):
        line = body[index]
        if not line or line[0] not in " +-":
            raise HostEventError(f"Invalid patch hunk line: {line!r}")
        if line[0] in " -":
            old.append(line[1:])
        if line[0] in " +":
            new.append(line[1:])
        index += 1
    if not old and not new:
        raise HostEventError("Empty patch hunk")
    end = index < len(body) and body[index] == "*** End of File"
    return old, new, index + int(end), end


def _updated(original, body):
    lines = original.splitlines()
    output, cursor, index = [], 0, 0
    if body and body[0].startswith((" ", "+", "-")):
        body = ["@@", *body]
    if not body:
        raise HostEventError("Update contains no hunks")
    while index < len(body):
        anchor = body[index]
        if anchor != "@@" and not anchor.startswith("@@ "):
            raise HostEventError(f"Expected @@ patch anchor, got {anchor!r}")
        start = cursor
        if anchor != "@@":
            start = _match(lines, [anchor[3:]], cursor) + 1
        old, new, index, end = _hunk(body, index + 1)
        position = _match(lines, old, start, end) if old else len(lines)
        if not old and start > position:
            raise HostEventError("Insertion outside file")
        output.extend(lines[cursor:position])
        output.extend(new)
        cursor = position + len(old)
    output.extend(lines[cursor:])
    return "\n".join(output) + ("\n" if output else "")


def _destination(path, state):
    exists = state[path] is not None if path in state else Path(path).exists()
    if exists:
        raise HostEventError(f"Patch destination already exists: {path}")


def _operation(event, header, body, state):
    cwd = event.get("cwd") or str(Path.cwd())
    kind, separator, raw_path = header.removeprefix("*** ").partition(": ")
    if not separator or kind not in {"Add File", "Delete File", "Update File"}:
        raise HostEventError(f"Unsupported patch operation: {header!r}")
    path = _path(raw_path, cwd)
    if kind == "Add File":
        _destination(path, state)
        if any(not line.startswith("+") for line in body):
            raise HostEventError("Add File accepts only + lines")
        content = "".join(line[1:] + "\n" for line in body)
        state[path] = content
        return [_event(event, "Write", path, content=content)]
    old = _read(path, state)
    if kind == "Delete File":
        if body:
            raise HostEventError("Delete File cannot contain hunks")
        state[path] = None
        return [_event(event, "Edit", path, old_string=old, new_string="")]
    return _update_events(event, path, body, state)


def _update_events(event, path, body, state):
    old = _read(path, state)
    cwd = event.get("cwd") or str(Path.cwd())
    destination = path
    if body and body[0].startswith("*** Move to: "):
        destination = _path(body[0][len("*** Move to: "):], cwd)
        body = body[1:]
        if destination != path:
            _destination(destination, state)
    new = _updated(old, body)
    state[destination] = new
    if destination != path:
        state[path] = None
        return [_event(event, "Edit", path, old_string=old, new_string=""),
                _event(event, "Write", destination, content=new)]
    return [_event(event, "Edit", path, old_string=old, new_string=new)]


def _patch_events(event, command):
    if not isinstance(command, str):
        raise HostEventError("apply_patch tool_input.command must be a string")
    lines = command.splitlines()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise HostEventError("Invalid Begin Patch / End Patch envelope")
    result, state, index = [], {}, 1
    while index < len(lines) - 1:
        header = lines[index]
        index += 1
        body = []
        while index < len(lines) - 1:
            line = lines[index]
            if line.startswith(("*** Add File:", "*** Delete File:", "*** Update File:")):
                break
            body.append(line)
            index += 1
        result.extend(_operation(event, header, body, state))
    return result


def normalize_event(event):
    """Return ordered Claude-shaped gate events; raise on unsafe patch translation.

    Unknown tools pass through. Relative paths resolve against event cwd; shell
    workdir overrides cwd. Payloads and target files are never modified.
    """
    if not isinstance(event, dict):
        raise HostEventError("Hook event must be an object")
    name = event.get("tool_name")
    if name not in {"apply_patch", "Edit", "Write", "Bash", "exec_command", "shell_command"}:
        return [event]
    tin = event.get("tool_input")
    if not isinstance(tin, dict):
        raise HostEventError(f"{name} tool_input must be an object")
    if name == "apply_patch":
        return _patch_events(event, tin.get("command"))
    if name in {"Bash", "exec_command", "shell_command"}:
        command = tin.get("cmd", tin.get("command"))
        if not isinstance(command, str):
            raise HostEventError("Shell command must be a string")
        base = event.get("cwd") or str(Path.cwd())
        cwd = str((Path(base) / (tin.get("workdir") or tin.get("cwd") or base)).resolve())
        return [{**event, "tool_name": "Bash", "cwd": cwd,
                 "tool_input": {**tin, "command": command}}]
    path = _path(tin.get("file_path"), event.get("cwd") or str(Path.cwd()))
    return [{**event, "tool_input": {**tin, "file_path": path}}]
