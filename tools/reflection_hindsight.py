#!/usr/bin/env python3
"""reflection_hindsight.py -- retain a subagent run into Hindsight, visibly.

Hindsight is configured per working directory in ``~/.hindsight/coding-agent.json``
(override: ``HINDSIGHT_CONFIG``, the variable the Hindsight coding-agent plugin
itself honours): ``optInOnly`` + ``optInPaths`` decide whether a directory takes
part, ``mapPathToBank`` names its bank, ``apiUrl`` the server (override:
``HINDSIGHT_API_URL``), ``apiToken`` an optional bearer token (override:
``HINDSIGHT_API_TOKEN``).

Retain endpoint, read from the live server's /openapi.json on 2026-10-13:
``POST {apiUrl}/v1/default/banks/{bank_id}/memories`` with a RetainRequest body
``{"items": [MemoryItem], "async": bool, "operation_id": str}``; a MemoryItem
carries content, timestamp, context, metadata (string map), document_id and
item-level tags (``document_tags`` is deprecated).

Contract (no silent fallback). ``retain`` returns an Outcome whose status is
exactly one of:
  * ``retained``       the server answered 2xx;
  * ``not_configured`` the directory does not take part, and ``detail`` says why;
  * ``error``          the server was unreachable or refused; ``detail`` says how.
It never raises for those three; the caller writes the outcome to stderr and to
the ledger row. A non-HTTP programming error is not caught.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import ipaddress
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

CONFIG_ENV = "HINDSIGHT_CONFIG"
URL_ENV = "HINDSIGHT_API_URL"
TOKEN_ENV = "HINDSIGHT_API_TOKEN"
DEFAULT_CONFIG = os.path.join("~", ".hindsight", "coding-agent.json")
RETAINED, NOT_CONFIGURED, ERROR = "retained", "not_configured", "error"
# Total wall time the whole Hindsight step may take, DNS and every socket
# operation included. Budget: the SubagentStop hook timeout is 15 s
# (hooks/hooks.json); the ledger append that precedes this step may spend up to
# reflection_ledger.GIT_TIMEOUT_S = 8 s in git; 15 - 8 = 7 s remain, minus 3 s for
# interpreter start and the outcome append = 4 s. A test asserts the sum stays
# under the hooks.json timeout. A retain is queued with async=true, so the
# server only has to accept it.
HINDSIGHT_DEADLINE_S = 4
LOOPBACK_NAMES = ("localhost",)
# Namespace for the deterministic operation_id: re-firing the same SubagentStop
# returns the original operation instead of queueing a duplicate (RetainRequest
# schema). source: RFC 4122 section 4.3 name-based UUID; the namespace is this
# module's own constant and carries no meaning beyond being fixed.
_OPERATION_NS = uuid.UUID("5d0c7b1e-6f1a-4c53-9a0e-2f7a1b9d4c10")


@dataclass
class Outcome:
    status: str
    detail: str
    bank: Optional[str] = None
    document_id: Optional[str] = None

    def as_row(self) -> Dict:
        return {"status": self.status, "detail": self.detail,
                "bank": self.bank, "document_id": self.document_id}


def _load_config(env: Dict[str, str]):
    """(config dict, None) or (None, reason it is unavailable)."""
    path = os.path.expanduser(env.get(CONFIG_ENV) or DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, f"no Hindsight config at {path}"
    except (OSError, ValueError) as exc:
        return None, f"Hindsight config {path} unreadable: {exc.__class__.__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"Hindsight config {path} is not a JSON object"
    return data, None


def _contains(root: str, cwd: str) -> bool:
    root, cwd = os.path.realpath(root), os.path.realpath(cwd)
    return cwd == root or cwd.startswith(root.rstrip(os.sep) + os.sep)


def _longest_match(table: Dict[str, str], cwd: str) -> Optional[str]:
    hits = [root for root in table if _contains(root, cwd)]
    return table[max(hits, key=len)] if hits else None


def resolve_bank(config: Dict, cwd: str):
    """(bank, None) when ``cwd`` takes part, else (None, reason)."""
    opt_in = [p for p in config.get("optInPaths") or [] if isinstance(p, str)]
    if config.get("optInOnly") and not any(_contains(p, cwd) for p in opt_in):
        return None, f"{cwd} is under no optInPaths entry (optInOnly is true)"
    mapping = config.get("mapPathToBank")
    bank = _longest_match(mapping, cwd) if isinstance(mapping, dict) else None
    if not bank:
        return None, f"{cwd} is opted in but mapPathToBank names no bank for it"
    return bank, None


def build_item(run: Dict) -> Dict:
    """The MemoryItem for one run, stamped now. ``run`` is Run.as_row()."""
    agent_type, agent_id = run["agent_type"], run["agent_id"]
    content = (f"Subagent run of type {agent_type}.\n"
               f"Task description: {run.get('description') or '(none recorded)'}\n"
               f"Transcript: {run.get('transcript_path') or '(unknown)'}\n"
               f"Final message:\n{run.get('excerpt') or '(none recovered)'}")
    return {"content": content, "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "context": "subagent run",
            "document_id": f"subagent-{agent_id}",
            "tags": [f"agent_type:{agent_type}", "source:subagent"],
            "metadata": {"agent_id": agent_id, "agent_type": agent_type,
                         "session_id": run.get("session_id") or ""}}


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_api_url(api_url: str) -> Optional[str]:
    """None when ``api_url`` may receive the bearer token, else why not.

    Pre: none. Post: https anywhere, http only to a loopback host; every other
    scheme (file://, ftp://, no scheme) and a host-less URL is refused.
    """
    parts = urllib.parse.urlsplit(api_url)
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return None
    if parts.scheme == "http" and _is_loopback(host):
        return None
    return (f"apiUrl {api_url!r} refused: only https, or http to a loopback host, "
            "may be sent the bearer token; no request was sent")


def _post(url: str, token: str, body: Dict) -> Outcome:
    """_post_blocking under one total deadline (DNS has no timeout of its own)."""
    box: list = []

    def work() -> None:
        try:
            box.append((True, _post_blocking(url, token, body)))
        except Exception as exc:  # re-raised below in the caller's thread
            box.append((False, exc))

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(HINDSIGHT_DEADLINE_S)
    alive = worker.is_alive()  # read before box: a dead worker's box is final
    if not box and alive:
        return Outcome(ERROR, f"{url} gave no answer within {HINDSIGHT_DEADLINE_S} s "
                              "(the hook budget); the retain was abandoned")
    if not box:  # a non-Exception (SystemExit, KeyboardInterrupt) ended the worker
        return Outcome(ERROR, f"{url}: the retain worker died without an outcome")
    done, value = box[0]
    if not done:
        raise value
    return value


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the bearer token to the
    target (and re-send a 301/302/303 POST as a GET), and the target is a host
    check_api_url never saw. The redirect surfaces as an HTTPError naming it."""

    def redirect_request(self, req, fp, code, *rest):
        _msg, headers, newurl = rest  # urllib's fixed override signature
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirect to {newurl} refused, nothing forwarded", headers, fp)


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _post_blocking(url: str, token: str, body: Dict) -> Outcome:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with _OPENER.open(request, timeout=HINDSIGHT_DEADLINE_S) as resp:
            return Outcome(RETAINED, f"HTTP {resp.status} from {url}")
    except urllib.error.HTTPError as exc:
        return Outcome(ERROR, f"HTTP {exc.code} from {url}: {exc.reason}")
    except (urllib.error.URLError, OSError) as exc:
        return Outcome(ERROR, f"{url} unreachable: {exc.__class__.__name__}: {exc}")


def retain(cwd: str, run: Dict, env: Optional[Dict[str, str]] = None) -> Outcome:
    """Retain ``run`` for the bank ``cwd`` maps to.

    Pre: ``run`` is Run.as_row(). Post: an Outcome per the module contract.
    """
    env = dict(os.environ if env is None else env)
    config, why = _load_config(env)
    if config is None:
        return Outcome(NOT_CONFIGURED, why or "no config")
    bank, why = resolve_bank(config, cwd)
    if bank is None:
        return Outcome(NOT_CONFIGURED, why or "no bank")
    api_url = env.get(URL_ENV) or config.get("apiUrl")
    if not isinstance(api_url, str) or not api_url:
        return Outcome(NOT_CONFIGURED, "bank resolved but no apiUrl in the config", bank)
    refusal = check_api_url(api_url)
    if refusal:
        return Outcome(ERROR, refusal, bank)
    item = build_item(run)
    body = {"items": [item], "async": True,
            "operation_id": str(uuid.uuid5(_OPERATION_NS, run["agent_id"]))}
    url = f"{api_url.rstrip('/')}/v1/default/banks/{urllib.parse.quote(bank, safe='')}/memories"
    outcome = _post(url, env.get(TOKEN_ENV) or str(config.get("apiToken") or ""), body)
    outcome.bank, outcome.document_id = bank, item["document_id"]
    return outcome
