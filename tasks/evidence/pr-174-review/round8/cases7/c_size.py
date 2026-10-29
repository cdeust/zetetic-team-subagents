# Round-7 reviewer: the size-cap branches run before the round-7 refusal rule.
# Z1: input under 128 KiB, rewritten over it (each bare newline is rewritten to ' ;\n', 3 chars).
# Z2: input itself over 128 KiB. Both carry a verb built at run time (I1 tail), so no literal commit.
TAIL = 'x=git; y=comm; $x ${y}it -m m'
cases = [
    ('Z1 newlines push rewrite over cap', 'git status; ' + '\n' * 45000 + TAIL),
    ('Z2 input over cap', 'git status; ' + ': ' + 'a ' * 66000 + '\n' + TAIL),
    ('Z3 newlines, literal commit', 'git status; ' + '\n' * 45000 + 'git commit -m m'),
    ('Z4 under cap control', 'git status; ' + '\n' * 1000 + TAIL),
]
