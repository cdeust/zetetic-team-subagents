# Round 9 (fixer): the residual that does run. R1 and R2 in c_r9_residual.py
# are refused only because `command` inside $(...) is a prefix word. Here the
# built word is an argument of which, cp or ln, and the command name ./x or x
# is static: no command name is built at run time, yet x is a copy of git.
# origin/main refused all three (data git followed by a blank).
D = ": <<'Q'\nit's git\nQ\n"
cases = [
    ('R3 which, cp, ./x', D + 'p=$(printf gi)t; cp "$(which "$p")" ./x; ./x commit -m m'),
    ('R4 which, ln, ./x', D + 'p=gi; ln -sf "$(which "${p}t")" ./x; ./x commit -m m'),
    ('R5 which, cp, PATH, x', D + 'p=gi; mkdir -p b; cp "$(which "${p}t")" b/x; PATH=$PWD/b:$PATH x commit -m m'),
]
