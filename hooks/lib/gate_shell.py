"""Shell-ish tokenizer for the gate hooks: separate *invocations* from text that mentions them.

Not a full shell parser. Contract: ``lex(cmd)`` returns tokens with quotes resolved, heredoc bodies and comments
dropped:

  ("w", word)          a word of a simple command
  ("op", sep)          a separator: ";" (also a newline), "&", "&&", "||", "|", and "(" / ")" around a subshell
  ("redir>", target)   the target of an output redirection (`>`, `>>`, `&>`, `>|`, `<>`); never an argument
  ("redir<", target)   the target of an input redirection

Command substitution (`$(...)`, a backtick pair, `<(...)`, `>(...)`) is a command bash RUNS, wherever it is
written, double quotes included: `out="$(git commit -m x)"` commits. Its content is lexed recursively and emitted
as its own simple command(s), between "(" and ")" (it runs in a subshell), BEFORE the simple command that holds
it, because bash runs it first; the word that holds it keeps the literal text. A heredoc inside it is skipped by
the inner lexer, so a `"` in the message body (an inch mark) does not end the outer string.

``segments`` splits a token stream into simple commands; ``events`` yields the same commands with their output
redirections, whether they are part of a pipeline, and the subshell boundaries; ``strip_prefix`` removes env
assignments and wrappers (env, sudo, time, ...). Not modelled: `case` patterns inside a substitution (a `)` there
ends it early), `eval`, `bash -c`, aliases.

Pure functions: no I/O, no git, nothing that can block.
"""
from __future__ import annotations

import re
from typing import NamedTuple

_ASSIGN_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
# Words that may precede the real command in a simple command.
PREFIX_WORDS = frozenset(
    {"sudo", "command", "nohup", "time", "exec", "builtin", "env", "!", "{", "}",
     "if", "then", "do", "else", "elif", "while", "until"}
)
# Flags of wrapper commands that consume the next word as their argument.
WRAPPER_ARG_FLAGS = {"env": {"-u", "-C", "-S"}, "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"}}
_WORD_STOP = " \t\n;&|()<>"
_PAIR_OPS = ("&&", "||", "|&")
_SUBSTITUTIONS = ("$(", "<(", ">(")
_DOUBLE_ESCAPES = '$`"\\\n'  # source: bash(1) QUOTING: inside double quotes a backslash escapes only these


class _Lexer:
    """One pass over ``cmd`` from ``start``; each ``_take_*`` consumes input at ``self.i`` and appends to
    ``self.toks``. ``nested``: the content of a `$(`, which an unmatched `)` ends."""

    def __init__(self, cmd: str, start: int = 0, nested: bool = False) -> None:
        self.cmd, self.n, self.i = cmd, len(cmd), start
        self.toks: list[tuple[str, str]] = []
        self.cur: list[str] | None = None  # the word being built (None: between words)
        self.pending: list[str] = []  # heredoc delimiters whose bodies start after the next newline
        self.skip_word = False  # the next completed word is here-string data
        self.redirect: str | None = None  # the next completed word is this redirection's target
        self.nested, self.depth, self.done = nested, 0, False
        self.seg = 0  # where the current simple command's tokens start: substitutions are emitted there

    def run(self) -> list[tuple[str, str]]:
        # invariant: self.toks holds the tokens of cmd[start:self.i]; termination: every step advances self.i
        while self.i < self.n and not self.done:
            self._step()
        self._flush()
        return self.toks

    def _flush(self) -> None:
        if self.cur is None:
            return
        word, self.cur = "".join(self.cur), None
        if self.skip_word:
            self.skip_word = False
        elif self.redirect:
            kind, self.redirect = self.redirect, None
            if kind == "redir&":  # `>&2`, `2>&-`: a descriptor; `>&file` writes the file
                kind = None if word.isdigit() or word == "-" else "redir>"
            if kind:
                self.toks.append((kind, word))
        else:
            self.toks.append(("w", word))

    def _op(self, sep: str = ";") -> None:
        self._flush()
        self.toks.append(("op", sep))
        self.seg = len(self.toks)

    def _add(self, text: str) -> None:
        self.cur = (self.cur or []) + [text]

    def _hoist(self, inner: list) -> None:
        """Emit a substitution's commands before the simple command being read, as a subshell."""
        block = [("op", "("), *inner, ("op", ")")]
        self.toks[self.seg:self.seg] = block
        self.seg += len(block)

    def _step(self) -> None:
        c, cmd, i = self.cmd[self.i], self.cmd, self.i
        if c in "\\'\"`" or (c == "#" and self.cur is None):
            self._take_quoted(c)
        elif c in " \t":
            self._flush()
            self.i += 1
        elif c == "\n":
            self._take_newline()
        elif cmd.startswith(_SUBSTITUTIONS, i):
            self.i = self._paren_substitution(i, False)
        elif cmd.startswith("<<", i):
            self._take_heredoc()
        elif c in "<>" or cmd.startswith("&>", i):
            self._take_redirect()
        else:
            self._take_plain(c)

    def _take_quoted(self, c: str) -> None:
        if c == "\\":
            self._take_backslash()
        elif c == "'":
            self._take_single()
        elif c == '"':
            self._take_double()
        elif c == "`":
            self.i = self._backtick_substitution(self.i, False)
        else:
            self._take_comment()

    def _take_plain(self, c: str) -> None:
        pair = self.cmd[self.i:self.i + 2]
        if pair in _PAIR_OPS:
            self._op("|" if pair == "|&" else pair)
            self.i += 2
        elif c == ")" and self.nested and self.depth == 0:
            self.i += 1
            self.done = True  # the end of the enclosing `$(`
        elif c in ";&|()":
            if c == "(":
                self.depth += 1
            elif c == ")" and self.depth:
                self.depth -= 1
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
            j = self._double_part(j, buf)
        self._add("".join(buf))
        self.i = j + 1

    def _double_part(self, j: int, buf: list) -> int:
        """Read one part of a double-quoted string at ``j`` into ``buf``; return where the next part starts."""
        c = self.cmd[j]
        if c == "\\" and j + 1 < self.n:
            nxt = self.cmd[j + 1]
            buf.append("" if nxt == "\n" else nxt if nxt in _DOUBLE_ESCAPES else c + nxt)
            return j + 2
        if self.cmd.startswith("$(", j):
            end = self._paren_substitution(j, True)
        elif c == "`":
            end = self._backtick_substitution(j, True)
        else:
            end = j + 1
        buf.append(self.cmd[j:end])
        return end

    def _paren_substitution(self, at: int, quoted: bool) -> int:
        """Lex the substitution opened at ``at`` (`$(`, `<(`, `>(`) to its matching `)`; emit its commands; return
        the index after it. Outside a double-quoted string its literal text joins the current word here (inside
        one, the caller adds it to the string)."""
        inner = _Lexer(self.cmd, at + 2, nested=True)
        self._hoist(inner.run())
        self.pending += inner.pending
        if not quoted:
            self._add(self.cmd[at:inner.i])
        return inner.i

    def _backtick_substitution(self, at: int, quoted: bool) -> int:
        """Lex the backtick pair opened at ``at``; emit its commands; return the index after the closing one."""
        k, body = at + 1, []
        while k < self.n and self.cmd[k] != "`":
            if self.cmd[k] == "\\" and k + 1 < self.n:
                nxt = self.cmd[k + 1]
                body.append(nxt if nxt in ("`\\$" + ('"' if quoted else "")) else "\\" + nxt)
                k += 2
                continue
            body.append(self.cmd[k])
            k += 1
        self._hoist(_Lexer("".join(body)).run())
        end = min(k + 1, self.n)
        if not quoted:
            self._add(self.cmd[at:end])
        return end

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
        if self.cmd.startswith("<<<", self.i):
            self.skip_word = True
            self.i += 3
            return
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
        start = self.i
        while self.i < self.n and self.cmd[self.i] in "<>&|":
            self.i += 1
        op = self.cmd[start:self.i]
        self.redirect = "redir&" if op.endswith("&") else "redir>" if ">" in op else "redir<"


def lex(cmd: str) -> list[tuple[str, str]]:
    """Pre: ``cmd`` is any string. Post: tokens as described in the module docstring; never raises."""
    return _Lexer(cmd).run()


def segments(toks: list[tuple[str, str]]) -> list[list[str]]:
    """Simple commands: the words between operators, empty ones dropped (redirection targets are not words)."""
    segs: list[list[str]] = [[]]
    for kind, val in toks:
        if kind == "op":
            segs.append([])
        elif kind == "w":
            segs[-1].append(val)
    return [s for s in segs if s]


class Command(NamedTuple):
    words: list  # the words, prefix included (strip_prefix removes it)
    writes: list  # the targets of its output redirections
    piped: bool  # a pipeline element: bash runs it in a subshell, so a `cd` in it changes nothing after it


def events(cmd: str) -> list:
    """The simple commands of ``cmd`` in the order bash runs them, as ("cmd", Command), and the subshell boundaries
    as ("open", None) / ("close", None): a `cd` inside a subshell does not outlive it."""
    out: list = []
    words: list = []
    writes: list = []
    after_pipe = False
    for kind, val in lex(cmd) + [("op", ";")]:
        if kind == "w":
            words.append(val)
        elif kind == "redir>":
            writes.append(val)
        elif kind == "op":
            if words or writes:
                out.append(("cmd", Command(words, writes, after_pipe or val == "|")))
            words, writes, after_pipe = [], [], val == "|"
            out += [("open", None)] if val == "(" else [("close", None)] if val == ")" else []
    return out


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
