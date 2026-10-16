"""Rewrite a shell command so that a lexer sees only the commands it runs.

Sources, POSIX Shell Command Language (IEEE Std 1003.1-2017, XCU ch. 2):
- §2.7.4 Here-Document: the body is the lines after the operator's line up to
  a line holding only the delimiter, with leading tabs removed for <<-. When
  any part of the delimiter word is quoted the body is not expanded: it is
  data. Otherwise it undergoes parameter expansion, command substitution and
  arithmetic expansion, a backslash quoting only $ ` \\ and newline; quotes
  and # there are data. Only the commands of its $(...) and `...` are kept.
- §2.6.2 Parameter Expansion, §2.6.4 Arithmetic Expansion: inside ${...} and
  $((...)), and bash's $[...] and ((...)) command, << and # are word or
  operator text, not a redirection or a comment. Only a command substitution
  there holds commands; it is rewritten like any other.
- bash parse.y parse_arith_cmd (beyond §2.6.4): (( and $(( are arithmetic
  only when the ) matching the inner ( is directly followed by ); otherwise
  they open nested subshells, which are commands.
- §2.9.4.3 case: a pattern's ) inside $(...) does not end the substitution.
  A word case anywhere a word starts is counted as one: counting too many
  only keeps a substitution open, so its text is still read as commands.
- §2.6.3: a $(...) holds a whole script, so it reads its own here-documents;
  a body still pending at its ) is dropped and the next lines are read as
  commands (zsh; bash reads them as the body), so neither shell hides a
  command from the lexer.
- §2.7.4, §2.2: the delimiter is the word after quote removal; $'...'
  (bash, zsh) and $"..." (bash) quote it too. A body whose delimiter line
  never comes raises ValueError: the operator may have been misread (bash
  reads a[1<<2]=x as a subscript, zsh as a here-document) and hidden what
  follows.
- §2.3 rule 9: # begins a comment only at the start of a word, so not right
  after a $(...), $((...)), bash's <(...) or a removed backslash-newline.
- §2.2.1: a backslash-newline is removed before the line is read.
- §2.9.3: an unquoted newline separates commands, like ;.
Quoted text is copied unchanged, including a $(...) inside double quotes, so a
command whose quoting is malformed still fails to lex afterwards.
An expansion that bash does not read as arithmetic is read again as commands,
so each rewrite is cached for the duration of one shell_lines call: without
the cache every nesting level doubles the work.
"""
from functools import lru_cache
import re

WORD_END = ' \t\n;&|()<>'
# Pieces after which the next character starts a word: a blank, an operator
# character, or the space that replaces a here-document operator.
SEPARATING = {' ', '\t', ';', '&', '|', '(', ')', '<', '>', '<<<'}
CLOSERS = {'{': '}', '[': ']', '(': ')'}


def unquoted(text):
    """Drop quote and backslash characters; joins g'it' into git."""
    return text.replace("'", '').replace('"', '').replace('\\', '')


def _quoted_end(text, start):
    """Index just past the quoted string opening at start, or len(text)."""
    quote, index = text[start], start + 1
    while index < len(text) and text[index] != quote:
        index += 2 if quote == '"' and text[index] == '\\' else 1
    return min(index + 1, len(text))


def _substitution(text, index):
    """Rewrite the $(...), <(...) or >(...) at index: (end, text)."""
    end, inner = _command(text, index + 2, ')')
    return end + 1, text[index:index + 2] + inner + ')'


def _span_piece(text, index):
    """(end, text) for one piece of an expansion: << and # stay text."""
    char = text[index]
    if char in '\'"':
        end = _quoted_end(text, index)
        return end, text[index:end]
    if char == '\\':
        return index + 2, text[index:index + 2]
    if char == '$' and text.startswith(('$((', '${', '$['), index):
        found = _expansion(text, index)
        if found:
            return found
    if text.startswith('$(', index):
        return _substitution(text, index)
    return index + 1, char


@lru_cache(maxsize=None)
def _span(text, start):
    """Rewrite the expansion opening at text[start] through its closer:
    (end, text), or None when it never closes."""
    opener, out, depth, index = text[start], [], 0, start
    while index < len(text):
        char = text[index]
        if char in (opener, CLOSERS[opener]):
            depth += 1 if char == opener else -1
            out.append(char)
            index += 1
            if depth == 0:
                return index, ''.join(out)
            continue
        index, piece = _span_piece(text, index)
        out.append(piece)
    return None


@lru_cache(maxsize=None)
def _arithmetic(text, start):
    """(end, text) for the (( at start when bash reads it as arithmetic."""
    inner = _span(text, start + 1) if text.startswith('((', start) else None
    if inner is None or not text.startswith(')', inner[0]):
        return None
    return inner[0] + 1, '(' + inner[1] + ')'


def _expansion(text, index):
    """(end, text) for ${...}, $[...], $((...)) or ((...)) at index, or None
    when bash would not read one there."""
    dollar = text[index] == '$'
    start = index + dollar
    if text.startswith('((', start):
        found = _arithmetic(text, start)
    else:
        found = _span(text, start)
    return found and (found[0], '$' * dollar + found[1])


def _delimiter(word):
    """Quote removal on a here-document word: (delimiter, quoted)."""
    out, quoted, index = [], False, 0
    while index < len(word):
        char = word[index]
        if char == '$' and word.startswith(('$\'', '$"'), index):
            index += 1
        elif char in '\'"':
            end = _quoted_end(word, index)
            inner = word[index + 1:end - 1]
            if char == '"':
                inner = re.sub(r'\\([$`"\\])', r'\1', inner.replace('\\\n', ''))
            out.append(inner)
            quoted, index = True, end
        elif word.startswith('\\\n', index):
            index += 2
        else:
            escaped = char == '\\'
            out.append(word[index + escaped:index + escaped + 1])
            quoted, index = quoted or escaped, index + 1 + escaped
    return ''.join(out), quoted


def _heredoc_word(text, start):
    """Parse the word after <<: (end, delimiter, quoted, strip_tabs)."""
    strip_tabs = text.startswith('-', start)
    index = start + strip_tabs
    while index < len(text) and (text[index] in ' \t' or text.startswith('\\\n', index)):
        index += 1 + (text[index] == '\\')
    word_start = index
    while index < len(text) and text[index] not in WORD_END:
        if text[index] in '\'"':
            index = _quoted_end(text, index)
        else:
            index += 2 if text[index] == '\\' else 1
    return (index, *_delimiter(text[word_start:index]), strip_tabs)


def _heredoc_body(text, start, delimiter, strip_tabs):
    """Read body lines from start through the delimiter line: (end, body).
    Raises ValueError when no line holds the delimiter."""
    index, lines = start, []
    while index < len(text):
        newline = text.find('\n', index)
        end = len(text) if newline < 0 else newline + 1
        line = text[index:end].removesuffix('\n')
        index = end
        if (line.lstrip('\t') if strip_tabs else line) == delimiter:
            return index, '\n'.join(lines)
        lines.append(line)
    raise ValueError('Here-document never ends: ' + delimiter)


def _body_commands(body):
    """The commands of the substitutions in an unquoted body (§2.7.4)."""
    commands, index = [], 0
    while index < len(body):
        if body[index] == '\\':
            index += 2
        elif body.startswith('$(', index) and not _arithmetic(body, index + 1):
            index, inner = _command(body, index + 2, ')')
            commands.append(inner)
            index += 1
        elif body[index] == '`':
            index, inner = _command(body, index + 1, '`')
            commands.append(inner)
            index += 1
        else:
            index += 1
    return ' ;\n'.join(commands)


def _next_piece(text, index, pending, word_start):
    """Return (end, replacement) for the shell syntax starting at index."""
    char = text[index]
    if char in '\'"':
        end = _quoted_end(text, index)
        return end, text[index:end]
    if char == '\\':
        piece = text[index:index + 2]
        return index + 2, '' if piece == '\\\n' else piece
    if text.startswith('<<<', index):
        # A here-string, not a here-document. Equivalent mutant: without this
        # branch << reads an empty word (< ends it) and records nothing.
        return index + 3, '<<<'
    if text.startswith('<<', index):
        end, delimiter, quoted, strip_tabs = _heredoc_word(text, index + 2)
        if delimiter:
            pending.append((delimiter, quoted, strip_tabs))
        return end, ' '
    if text.startswith(('((', '$((', '${', '$['), index):
        found = _expansion(text, index)
        if found:
            return found
    if text.startswith(('$(', '<(', '>('), index):
        return _substitution(text, index)
    if char == '#' and word_start:
        end = text.find('\n', index)
        return (len(text) if end < 0 else end), ''
    return index + 1, char


def _heredocs(text, index, pending, out):
    """At an unquoted newline, consume the pending bodies: the next index."""
    out.append(' ;\n')
    for delimiter, quoted, strip_tabs in pending:
        index, body = _heredoc_body(text, index, delimiter, strip_tabs)
        out.append(('' if quoted else _body_commands(body)) + ' ;\n')
    pending.clear()
    return index


def _is_word(text, index, word):
    """True when the text at index is word followed by a word end."""
    end = index + len(word)
    return text.startswith(word, index) and text[end:end + 1] in ('', *WORD_END)


def _reserved(text, index, word):
    """True when word is a reserved word in command position at index."""
    if not _is_word(text, index, word):
        return False
    return text[:index].rstrip(' \t')[-1:] in ('', ';', '&', '|', '(', '\n')


@lru_cache(maxsize=None)
def _command(text, index, closer=None):
    """Rewrite commands from index up to an unmatched closer, ) or `:
    (index of the closer or len(text), text)."""
    out, pending, depth, cases, word_start = [], [], 0, 0, True
    while index < len(text):
        char = text[index]
        if char == '\n':
            index, word_start = _heredocs(text, index + 1, pending, out), True
            continue
        if char == closer and depth == 0 and not (cases and closer == ')'):
            break
        if word_start and _is_word(text, index, 'case'):
            cases += 1
        elif cases and _reserved(text, index, 'esac'):
            cases -= 1
        index, piece = _next_piece(text, index, pending, word_start)
        if piece:
            # The )) of an arithmetic command ends a word; that of $((...)) does not.
            word_start = piece in SEPARATING or piece.startswith('((')
        if piece == '(':
            depth, piece = depth + 1, '( '
        elif piece == ')':
            depth = max(depth - 1, 0)
        out.append(piece)
    return index, ''.join(out)


_CACHED = (_command, _span, _arithmetic)


def shell_lines(command):
    """Return command with here-document data and comments removed and each
    unquoted newline turned into a ; separator. Raises ValueError when a
    here-document never ends or the nesting is deeper than the interpreter's
    recursion limit."""
    try:
        return _command(command, 0)[1]
    except RecursionError as error:
        raise ValueError('Shell nesting too deep to inspect') from error
    finally:
        for cached in _CACHED:
            cached.cache_clear()
