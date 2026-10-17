"""Rewrite a shell command so that a lexer sees only the commands it runs.

Sources: POSIX Shell Command Language (IEEE Std 1003.1-2017, XCU ch. 2),
bash parse.y, zsh 5.9. Where bash and zsh read different commands, this
raises ValueError (the caller refuses when the command may commit or push).
The audit of every place text is dropped: tasks/evidence/pr-174-review/
round7/analysis.txt.
- §2.7.4 Here-document: the body runs from the line after the operator's
  line to the delimiter line (<<- strips tabs; an unquoted body joins
  backslash-newlines first). A quoted delimiter makes the body data; else
  only the commands of its $(...) and `...` are kept. The delimiter is the
  word after quote removal ($'...' decoded, $"..."); a $(...), ${...} or
  `...` in it is one unit. A body that never ends, or that is still pending
  where a $(...) ends (bash reads the next lines, zsh not), raises.
- §2.6.2, §2.6.4: inside ${...}, $((...)), $[...] and ((...)), << and # are
  text; a $(...) there is rewritten like any other. ${...} ends at the first
  unquoted } outside nested units (a bare { is text in bash, and in zsh only
  inside "..."); where zsh ends it later past text that could change which
  lines are commands, or a ' sits inside "${...}", this raises.
- bash parse_arith_cmd: (( is arithmetic only when the ) matching its inner
  ( is directly followed by ); otherwise it opens nested subshells.
- §2.9.4.3: a case pattern's ) does not end a $(...). case counts only in
  command position (§2.4, §2.9.1, §2.7: after operators, assignments not
  followed by a reserved word, OPENERS, time and its options, redirections
  and their targets; &> and &>> are redirections); esac also ends an empty
  case right after in. zsh's case WORD { ... } (no in) raises.
- bash: << in an assignment subscript NAME[...]= is a shift, zsh reads a
  here-document: a word NAME[...] holding << raises.
- §2.3 rule 9: # begins a comment only at the start of a word. zsh reads a
  ( after a word character as a glob group (a(#b), *.py(N)), and (a|b)#x,
  (a)#x) and =(cmd)#x as words: a # right after ( or ) is kept as text,
  and raises when the rest of its line could open a unit or here-document.
- §2.2.1, §2.9.3: a backslash-newline is removed; an unquoted newline
  separates commands, like ;.
- §2.2.3: inside "...", a $(...), ${...}, $((...)) or `...` is a unit, so a
  " inside it does not close the string; bash's $'...' ends at the first '
  not escaped by a backslash; a top-level `...` is one unit too.
Quoted text keeps its words for the lexer ("..." with nested units unquoted;
$'...' and `...` as a "..." word); commands inside quotes are not read, and
an unclosed quote is copied as is, so the lexer fails on it. Each rewrite of
an expansion is cached for one shell_lines call, so nesting does not
multiply the work.
"""
from functools import lru_cache
import re

WORD_END = ' \t\n;&|()<>'
SUBSCRIPT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\[')
# Pieces after which the next character starts a word: a blank, an operator
# character, or the space that replaces a here-document operator.
HASH_UNSAFE = re.compile('[\'"`$\\\\<()]')
SEPARATING = {' ', '\t', ';', '&', '|', '(', ')', '<', '>', '<<<'}
CLOSERS = {'{': '}', '[': ']', '(': ')'}


def unquoted(text):
    """Drop quote and backslash characters; joins g'it' into git."""
    return text.replace("'", '').replace('"', '').replace('\\', '')


def _escaped(text):
    """text written as the inside of a double-quoted lexer word."""
    return text.replace('\\', '\\\\').replace('"', '\\"')


def _closer(text, index, closer):
    """Index just past the closer at or after index, a backslash escaping the
    next character, or None when it never comes."""
    while index < len(text) and text[index] != closer:
        index += 2 if text[index] == '\\' else 1
    return index + 1 if index < len(text) else None


def _nested(text, index):
    """(end, text) for the $(...), ${...}, $[...], $((...)) or `...` at index:
    a unit, so a quote or # inside it belongs to it (§2.6.3, §2.2.3)."""
    if text[index] == '`':
        end = _closer(text, index + 1, '`') or len(text)
        return end, text[index:end]
    if text.startswith(('$((', '${', '$['), index):
        found = _expansion(text, index)
        if found:
            return found
    if text.startswith('$(', index):
        return _substitution(text, index)
    return index + 1, text[index]


def _dquote(text, start):
    """(end, word) for the "..." at start. A $(...), ${...}, $((...)) or
    `...` inside is a unit whose quotes do not close it (§2.2.3). Its
    rewritten text goes in without quotes or backslashes: commands inside
    quotes are not read, its words stay visible, and no nesting level
    multiplies the escaping. Unclosed, the text is copied so the lexer fails."""
    out, index = ['"'], start + 1
    while index < len(text) and text[index] != '"':
        if text[index] == '\\':
            piece, index = text[index:index + 2], index + 2
        elif text[index] == '`' or text.startswith(('$(', '${', '$['), index):
            end, unit = _nested(text, index)
            if text.startswith('${', index) and "'" in text[index:end]:
                raise ValueError("' inside \"${...}\": bash reads a quote, zsh a literal")
            index, piece = end, unquoted(unit)
        else:
            piece, index = text[index], index + 1
        out.append(piece)
    if index >= len(text):
        return len(text), text[start:]
    return index + 1, ''.join(out) + '"'


def _quoted(text, index):
    """(end, word) for the quoted unit at index: '...', "...", `...` or bash's
    $'...', where a backslash escapes the next character, \\' too. The last
    two are given to the lexer as a double-quoted word."""
    char = text[index]
    if char == '"':
        return _dquote(text, index)
    if char == "'":
        end = text.find("'", index + 1)
        end = len(text) if end < 0 else end + 1
        return end, text[index:end]
    opening = 1 if char == '`' else 2
    end = _closer(text, index + opening, "'" if opening == 2 else '`')
    if end is None:
        return len(text), text[index:]
    inner = text[index + opening:end - 1] if opening == 2 else text[index:end]
    return end, '"' + _escaped(inner) + '"'


def _quote_start(text, index):
    """True when a quoted unit opens at index."""
    return text[index] in '\'"`' or text.startswith("$'", index)


def _substitution(text, index):
    """Rewrite the $(...), <(...) or >(...) at index: (end, text)."""
    end, inner = _command(text, index + 2, ')')
    return end + 1, text[index:index + 2] + inner + ')'


def _span_piece(text, index):
    """(end, text) for one piece of an expansion: << and # stay text."""
    if _quote_start(text, index):
        return _quoted(text, index)
    if text[index] == '\\':
        return index + 2, text[index:index + 2]
    return _nested(text, index)


@lru_cache(maxsize=None)
def _span(text, start):
    """Rewrite the expansion opening at text[start] through its closer:
    (end, text), or None when it never closes."""
    opener, out, index = text[start], [text[start]], start + 1
    while index < len(text):
        char = text[index]
        if char == CLOSERS[opener]:
            out.append(char)
            return index + 1, ''.join(out)
        # A nested [ or ( is its own span, cached, so each character is read
        # once however many spans open before it. A bare { inside ${...} is
        # text for bash; _zsh_brace_check covers zsh.
        if char == opener and opener != '{':
            found = _span(text, index)
            if found is None:
                return None
            index, piece = found
        else:
            index, piece = _span_piece(text, index)
        out.append(piece)
    return None


def _zsh_brace_end(text, start):
    """End of the ${...} opening at text[start] as zsh reads it unquoted:
    every bare { and } counts. len(text) when it never closes."""
    depth, index = 0, start
    while index < len(text):
        char = text[index]
        if char in '{}':
            depth += 1 if char == '{' else -1
            index += 1
            if depth == 0:
                return index
        elif _quote_start(text, index):
            index = _quoted(text, index)[0]
        elif char == '\\':
            index += 2
        elif text.startswith(('$(', '$[', '$(('), index):
            index = _nested(text, index)[0]
        else:
            index += 1
    return len(text)


def _zsh_brace_check(text, index, end):
    """Raise when bash ends the unquoted ${...} at index at end and zsh,
    counting bare braces, ends it later past text that could hide or make a
    command: an operator, quote, newline, comment, $ or backslash."""
    later = text[end:_zsh_brace_end(text, index + 1)]
    if re.search(r'[;&|()<>\n\'"`#$\\]', later):
        raise ValueError('bare { inside ${...}: bash and zsh end it at different braces')


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


ANSI_C = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n',
          'r': '\r', 't': '\t', 'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}
ANSI_ESCAPE = re.compile(r'\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|c.|[0-7]{1,3}|.)', re.S)


def _ansi_escape(match):
    code = match.group(1)
    if code in ANSI_C:
        return ANSI_C[code]
    try:
        if code[0] in 'xuU':
            return chr(int(code[1:], 16))
        if code[0] == 'c' and len(code) == 2:
            return chr(ord(code[1]) & 31)
        return chr(int(code, 8))
    except ValueError:
        return match.group(0)


def _ansi_c(body):
    """The text of bash's $'...' with its backslash escapes decoded."""
    return ANSI_ESCAPE.sub(_ansi_escape, body)


def _delimiter(word):
    """Quote removal on a here-document word: (delimiter, quoted)."""
    out, quoted, index = [], False, 0
    while index < len(word):
        char = word[index]
        if word.startswith("$'", index):
            end = _quoted(word, index)[0]
            out.append(_ansi_c(word[index + 2:end - 1]))
            quoted, index = True, end
        elif word.startswith('$"', index):
            index += 1
        elif char in '\'"':
            end = _quoted(word, index)[0]
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
        if _quote_start(text, index):
            index = _quoted(text, index)[0]
        elif text[index] == '\\':
            index += 2
        else:
            # A $(...) or ${...} is one unit of the word, ; or ( inside too.
            end = _nested(text, index)[0]
            # Any later zsh end changes the delimiter word itself.
            if text.startswith('${', index) and _zsh_brace_end(text, index + 1) != end:
                raise ValueError('bare { inside a heredoc delimiter: bash and zsh read different words')
            index = end
    return (index, *_delimiter(text[word_start:index]), strip_tabs)


def _body_line(text, index, joined):
    """(end, line) for the body line at index. When joined (an unquoted
    delimiter), a line ending in an odd run of backslashes continues on the
    next one, as bash and zsh read it before matching the delimiter."""
    parts = []
    while True:
        newline = text.find('\n', index)
        end = len(text) if newline < 0 else newline + 1
        line = text[index:end].removesuffix('\n')
        index = end
        odd = (len(line) - len(line.rstrip('\\'))) % 2
        if not (joined and odd and newline >= 0):
            return index, ''.join(parts) + line
        parts.append(line[:-1])


def _heredoc_body(text, start, delimiter, quoting):
    """Read body lines from start through the delimiter line: (end, body).
    quoting is (quoted, strip_tabs). Raises ValueError when no line holds
    the delimiter."""
    (quoted, strip_tabs), index, lines = quoting, start, []
    while index < len(text):
        index, line = _body_line(text, index, not quoted)
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
    if _quote_start(text, index):
        return _quoted(text, index)
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
        if found and text.startswith('${', index):
            _zsh_brace_check(text, index, found[0])
        if found:
            return found
    if text.startswith(('$(', '<(', '>('), index):
        return _substitution(text, index)
    if char == '(' and not word_start and index and text[index - 1] not in WORD_END + '=' \
            and not text.startswith('()', index):
        # zsh reads a(#b) and *.py(N) as one word: no # in it is a comment.
        found = _span(text, index)
        if found:
            return found
    if char == '#' and word_start:
        end = text.find('\n', index)
        end = len(text) if end < 0 else end
        if text[index - 1:index] in ('(', ')'):
            return _hash_after_paren(text, index, end)
        return end, ''
    return index + 1, char


def _hash_after_paren(text, index, end):
    """(end, text) for a # right after ( or ). zsh reads (a|b)#x, (a)#x and
    =(cmd)#x as one word; bash and zsh read ((1))#x as a comment. The rest of
    the line is kept as text, which reads at least the commands the comment
    reading would, unless it holds a quote, $, `, \\, <, ( or ): kept, those
    could open a here-document or a unit that hides the next lines, so the
    command is uninspectable."""
    if HASH_UNSAFE.search(text, index + 1, end):
        raise ValueError('# after ( or ): bash may read a comment, zsh a word')
    return index + 1, '#'


def _heredocs(text, index, pending, out):
    """At an unquoted newline, consume the pending bodies: the next index."""
    out.append(' ;\n')
    for delimiter, quoted, strip_tabs in pending:
        index, body = _heredoc_body(text, index, delimiter, (quoted, strip_tabs))
        out.append(('' if quoted else _body_commands(body)) + ' ;\n')
    pending.clear()
    return index


def _word_at(text, index):
    """The word starting at index, its backslash-newlines removed (§2.2.1)."""
    out = []
    while index < len(text) and text[index] not in WORD_END:
        if text.startswith('\\\n', index):
            index += 2
            continue
        out.append(text[index])
        index += 1
    return ''.join(out)



# Reserved words after which the next word is again in command position.
OPENERS = {'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!', '{', 'coproc'}
ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=')
# Operator pieces after which a new command starts.
RESETS = {';', '&', '|', '(', ')'}
# Pieces after which the next word is a redirection target (§2.7).
REDIRECTS = {'<', '>', '<<<'}


def _previous_word(text, index):
    """(last character, word, scanned) before index, skipping blanks and
    backslash-newlines. It reads only the blanks and the one word between
    the previous word and index, so over all the words of a text the
    characters scanned sum to at most twice its length."""
    i = index - 1
    while i >= 0 and (text[i] in ' \t' or (text[i] == '\n' and i and text[i - 1] == '\\')):
        i -= 1 + (text[i] == '\n')
    last, chars = (text[i] if i >= 0 else ''), []
    while i >= 0 and text[i] not in ' \t\n;&|()<>':
        chars.append(text[i])
        i -= 1
        if i > 0 and text[i] == '\n' and text[i - 1] == '\\':
            i -= 2
    return last, ''.join(reversed(chars)), index - 1 - i


def _after_separator(text, index):
    """True when the word at index follows an operator or an OPENERS word."""
    last, word, _scanned = _previous_word(text, index)
    return last in ('', ';', '&', '|', '(', '\n') or word in OPENERS


def _case_step(cases, header, word, separated):
    """(cases, header) after a word that opens no case. An open header reads
    the subject, then in; esac ends a case in the first pattern position (an
    empty case, §2.9.4.3) or when separated: after an operator or OPENERS."""
    if header == 'subject':
        return cases, 'in'
    if header == 'in' and word == 'in':
        return cases, 'pattern'
    if header == 'in':
        raise ValueError('case without in: zsh reads case WORD { ... }, bash does not')
    if cases and word == 'esac' and (header == 'pattern' or separated):
        return cases - 1, None
    return cases, None


def _redirection_word(text, index, word, redirect):
    """True when word at index is a redirection's target or IO number (§2.7):
    it leaves the command position as it was."""
    return redirect or (word.isdigit() and text[index + len(word):index + len(word) + 1] in ('<', '>'))


def _word_state(state, word):
    """(in command position, next state) for a word read in state (§2.4,
    §2.9.1): 'command' expects a command name, which assignments, the
    reserved words in OPENERS and time (with its -p options) leave expected;
    after an assignment ('assigned') no word is reserved, as in bash;
    'args' reads the arguments of a command."""
    if state == 'time' and word.startswith('-'):
        return False, 'time'
    if state == 'args':
        return False, 'args'
    if ASSIGNMENT.match(word):
        return False, 'assigned'
    if state == 'assigned':
        return False, 'args'
    if word == 'time':
        return True, 'time'
    if word in OPENERS:
        return True, 'command'
    return True, 'args'


def _subscript_heredoc(text, index):
    """True when a word NAME[...] opening at index holds <<. bash reads the
    subscript of an assignment as arithmetic, zsh reads a here-document: the
    shells disagree on which lines are commands."""
    match = SUBSCRIPT.match(text, index)
    if not match:
        return False
    found = _span(text, match.end() - 1)
    if found is None:
        # Unclosed: any << after it may be read either way. find() keeps
        # this linear in the number of words.
        return text.find('<<', match.end()) >= 0
    return '<<' in _bare(text, match.end(), found[0])


def _bare(text, index, end):
    """text[index:end] without its quotes and nested units."""
    out = []
    while index < end:
        if _quote_start(text, index):
            index = _quoted(text, index)[0]
        elif text[index] == '\\':
            index += 2
        elif text.startswith(('$(', '${', '$['), index):
            index = _nested(text, index)[0]
        else:
            out.append(text[index])
            index += 1
    return ''.join(out)


@lru_cache(maxsize=None)
def _command(text, index, closer=None):
    """Rewrite commands from index up to an unmatched closer, ) or `:
    (index of the closer or len(text), text)."""
    out, pending, depth, cases, word_start, state = [], [], 0, 0, True, 'command'
    redirect, last, header = False, '', None
    while index < len(text):
        char = text[index]
        if char == '\n':
            index, word_start = _heredocs(text, index + 1, pending, out), True
            state = 'command'
            continue
        if char == closer and depth == 0 and not (cases and closer == ')'):
            if pending:
                # bash reads the next lines as the body, zsh as commands.
                raise ValueError('here-document still pending where a substitution ends')
            break
        if word_start and _subscript_heredoc(text, index):
            raise ValueError('<< inside a subscript: bash and zsh read different commands')
        if word_start and char not in WORD_END:
            word = _word_at(text, index)
            if not _redirection_word(text, index, word, redirect):
                command_word, state = _word_state(state, word)
                opens = command_word and word == 'case'
                separated = word == 'esac' and _after_separator(text, index)
                cases, header = (cases + 1, 'subject') if opens else _case_step(
                    cases, header, word, separated)
            redirect = False
        index, piece = _next_piece(text, index, pending, word_start)
        # The & of >& and >|, and of &> and &>>, belong to a redirection.
        joined = last in ('<', '>') or (piece == '&' and text.startswith('>', index))
        if piece in RESETS and not (joined and piece in ('&', '|')):
            state = 'command'
        redirect = redirect or piece in REDIRECTS
        last = piece or last
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
