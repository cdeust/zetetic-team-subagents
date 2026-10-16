"""Shell-ish tokenizer for the gate hooks: separate *invocations* from text that mentions them.

Not a full shell parser. Contract: ``lex(cmd)`` returns ``[("w", word) | ("op", sep)]`` with quotes
resolved, heredoc bodies, comments and redirections dropped. ``segments`` splits that stream into
simple commands; ``strip_prefix`` removes env assignments and wrappers (env, sudo, time, ...).

Pure functions: no I/O, no git, nothing that can block.
"""
from __future__ import annotations

import re

_ASSIGN_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
# Words that may precede the real command in a simple command.
PREFIX_WORDS = frozenset(
    {"sudo", "command", "nohup", "time", "exec", "builtin", "env", "!", "{", "}",
     "if", "then", "do", "else", "elif", "while", "until"}
)
# Flags of wrapper commands that consume the next word as their argument.
WRAPPER_ARG_FLAGS = {"env": {"-u", "-C", "-S"}, "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"}}
_WORD_STOP = " \t\n;&|()<>"


class _Lexer:
    """One pass over ``cmd``; each ``_take_*`` consumes input at ``self.i`` and appends to ``self.toks``."""

    def __init__(self, cmd: str) -> None:
        self.cmd, self.n, self.i = cmd, len(cmd), 0
        self.toks: list[tuple[str, str]] = []
        self.cur: list[str] | None = None  # the word being built (None: between words)
        self.pending: list[str] = []  # heredoc delimiters whose bodies start after the next newline
        self.skip_word = False  # the next completed word is a redirection target

    def run(self) -> list[tuple[str, str]]:
        # invariant: self.toks holds the tokens of cmd[:self.i]; termination: every step advances self.i
        while self.i < self.n:
            self._step()
        self._flush()
        return self.toks

    def _flush(self) -> None:
        if self.cur is not None:
            if self.skip_word:
                self.skip_word = False
            else:
                self.toks.append(("w", "".join(self.cur)))
            self.cur = None

    def _op(self, sep: str = ";") -> None:
        self._flush()
        self.toks.append(("op", sep))

    def _add(self, text: str) -> None:
        self.cur = (self.cur or []) + [text]

    def _step(self) -> None:
        c, cmd, i = self.cmd[self.i], self.cmd, self.i
        if c == "\\":
            self._take_backslash()
        elif c == "'":
            self._take_single()
        elif c == '"':
            self._take_double()
        elif c == "#" and self.cur is None:
            self._take_comment()
        elif c in " \t":
            self._flush()
            self.i += 1
        elif c == "\n":
            self._take_newline()
        elif cmd.startswith("<<<", i):
            self._flush()
            self.skip_word = True
            self.i += 3
        elif cmd.startswith("<<", i):
            self._take_heredoc()
        elif c in "<>" or cmd.startswith("&>", i):
            self._take_redirect()
        elif cmd.startswith("$(", i):
            self._op()
            self.i += 2
        elif c in ";&|()`":
            self._op(c)
            self.i += 1
        else:
            self._add(c)
            self.i += 1

    def _take_backslash(self) -> None:
        nxt = self.cmd[self.i + 1] if self.i + 1 < self.n else ""
        if nxt == "\n":  # line continuation
            self.i += 2
            return
        self._add(nxt)  # a trailing lone backslash adds an empty word part
        self.i += 2

    def _take_single(self) -> None:
        end = self.cmd.find("'", self.i + 1)
        end = self.n if end < 0 else end
        self._add(self.cmd[self.i + 1 : end])
        self.i = end + 1

    def _take_double(self) -> None:
        j, buf = self.i + 1, []
        while j < self.n and self.cmd[j] != '"':
            if self.cmd[j] == "\\" and j + 1 < self.n:
                j += 1
            buf.append(self.cmd[j])
            j += 1
        self._add("".join(buf))
        self.i = j + 1

    def _take_comment(self) -> None:
        end = self.cmd.find("\n", self.i)
        self.i = self.n if end < 0 else end

    def _take_newline(self) -> None:
        self._op()
        self.i += 1
        for delim in self.pending:  # skip heredoc bodies
            self._skip_body(delim)
        self.pending = []

    def _skip_body(self, delim: str) -> None:
        while self.i < self.n:
            end = self.cmd.find("\n", self.i)
            line = self.cmd[self.i :] if end < 0 else self.cmd[self.i : end]
            self.i = self.n if end < 0 else end + 1
            if line.strip() == delim:
                return

    def _take_heredoc(self) -> None:
        self._flush()
        self.i += 2
        if self.i < self.n and self.cmd[self.i] == "-":
            self.i += 1
        while self.i < self.n and self.cmd[self.i] in " \t":
            self.i += 1
        buf = []
        while self.i < self.n and self.cmd[self.i] not in _WORD_STOP:
            if self.cmd[self.i] not in "'\"\\":
                buf.append(self.cmd[self.i])
            self.i += 1
        if buf:
            self.pending.append("".join(buf))

    def _take_redirect(self) -> None:
        if self.cur is not None and "".join(self.cur).isdigit():
            self.cur = None  # file descriptor prefix: `2>&1`
        else:
            self._flush()
        while self.i < self.n and self.cmd[self.i] in "<>&|":
            self.i += 1
        self.skip_word = True  # the redirection target is not an argument


def lex(cmd: str) -> list[tuple[str, str]]:
    """Pre: ``cmd`` is any string. Post: tokens as described in the module docstring; never raises."""
    return _Lexer(cmd).run()


def segments(toks: list[tuple[str, str]]) -> list[list[str]]:
    """Simple commands: the words between operators, empty ones dropped."""
    segs: list[list[str]] = [[]]
    for kind, val in toks:
        if kind == "op":
            segs.append([])
        else:
            segs[-1].append(val)
    return [s for s in segs if s]


def strip_prefix(words: list[str]) -> list[str]:
    """Drop env assignments and wrappers (env, sudo, time, ...) before the real command."""
    i, wrapper = 0, None
    while i < len(words):
        w = words[i]
        if _ASSIGN_RE.match(w):
            i += 1
        elif w in PREFIX_WORDS:
            wrapper = w
            i += 1
        elif wrapper and w.startswith("-"):
            i += 2 if w in WRAPPER_ARG_FLAGS.get(wrapper, ()) else 1
        else:
            break
    return words[i:]
