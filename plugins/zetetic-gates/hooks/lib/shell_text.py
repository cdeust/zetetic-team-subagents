"""Rewrite a shell command so that a lexer sees only the commands it runs.

Sources, POSIX Shell Command Language (IEEE Std 1003.1-2017, XCU ch. 2):
- §2.7.4 Here-Document: the body is the lines after the operator's line up to
  a line holding only the delimiter, with leading tabs removed for <<-. When
  any part of the delimiter word is quoted the body is not expanded, so it is
  data. Otherwise it undergoes command substitution, so $(...) and `...` in
  it run; such a body is kept for the lexer.
- §2.3 rule 9: # at the start of a word begins a comment to the end of line.
- §2.2.1: a backslash-newline is removed before the line is read.
- §2.9.3: an unquoted newline separates commands, like ;.
Quoted text is copied unchanged, including a $(...) inside double quotes, so a
command whose quoting is malformed still fails to lex afterwards.
"""

WORD_END = ' \t\n;&|()<>'


def unquoted(text):
    """Drop quote and backslash characters; joins g'it' into git."""
    return text.replace("'", '').replace('"', '').replace('\\', '')


def _quoted_end(text, start):
    """Index just past the quoted string opening at start, or len(text)."""
    quote, index = text[start], start + 1
    while index < len(text) and text[index] != quote:
        index += 2 if quote == '"' and text[index] == '\\' else 1
    return min(index + 1, len(text))


def _arithmetic_end(text, start):
    """Index just past the ((...)) opening at start: << there is a shift."""
    depth, index = 0, start
    while index < len(text):
        depth += {'(': 1, ')': -1}.get(text[index], 0)
        index += 1
        if depth == 0:
            break
    return index


def _heredoc_word(text, start):
    """Parse the word after <<: (end, delimiter, quoted, strip_tabs)."""
    strip_tabs = text.startswith('-', start)
    index = start + strip_tabs
    while index < len(text) and text[index] in ' \t':
        index += 1
    word_start = index
    while index < len(text) and text[index] not in WORD_END:
        if text[index] in '\'"':
            index = _quoted_end(text, index)
        else:
            index += 2 if text[index] == '\\' else 1
    word = text[word_start:index]
    delimiter = unquoted(word)
    return index, delimiter, delimiter != word, strip_tabs


def _heredoc_body(text, start, delimiter, strip_tabs):
    """Read body lines from start through the delimiter line: (end, body)."""
    index, lines = start, []
    while index < len(text):
        newline = text.find('\n', index)
        end = len(text) if newline < 0 else newline + 1
        line = text[index:end].removesuffix('\n')
        index = end
        if (line.lstrip('\t') if strip_tabs else line) == delimiter:
            break
        lines.append(line)
    return index, '\n'.join(lines)


def _next_piece(text, index, pending):
    """Return (end, replacement) for the shell syntax starting at index."""
    char = text[index]
    if char in '\'"':
        end = _quoted_end(text, index)
        return end, text[index:end]
    if char == '\\':
        piece = text[index:index + 2]
        return index + 2, '' if piece == '\\\n' else piece
    if text.startswith('<<<', index):
        return index + 3, '<<<'
    if text.startswith('<<', index):
        end, delimiter, quoted, strip_tabs = _heredoc_word(text, index + 2)
        if delimiter:
            pending.append((delimiter, quoted, strip_tabs))
        return end, ' '
    if text.startswith('((', index):
        end = _arithmetic_end(text, index)
        return end, text[index:end]
    if char == '#' and (index == 0 or text[index - 1] in WORD_END):
        end = text.find('\n', index)
        return (len(text) if end < 0 else end), ''
    return index + 1, char


def shell_lines(command):
    """Return command with here-document data and comments removed and each
    unquoted newline turned into a ; separator. Never raises."""
    out, pending, index = [], [], 0
    while index < len(command):
        if command[index] != '\n':
            index, piece = _next_piece(command, index, pending)
            out.append(piece)
            continue
        out.append(' ;\n')
        index += 1
        for delimiter, quoted, strip_tabs in pending:
            index, body = _heredoc_body(command, index, delimiter, strip_tabs)
            runs = not quoted and ('$(' in body or '`' in body)
            out.append((body if runs else '') + ' ;\n')
        pending.clear()
    return ''.join(out)
