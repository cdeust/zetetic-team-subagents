# Round 9 (fixer): a residual outside the class closed in round 9. The command
# name ./x is static; the file it names is a copy of git made at run time
# (the built word is an argument of cp, not a command name). origin/main
# refused it (git followed by a blank in the data); the new head does not.
D = ": <<'Q'\nit's git\nQ\n"
cases = [
    ('R1 cp built git to ./x', D + 'cp "$(command -v $(printf gi)t)" ./x; ./x commit -m m'),
    ('R2 PATH and a static name', D + 'mkdir -p b; cp "$(command -v $(printf gi)t)" b/x; PATH=$PWD/b:$PATH; x commit -m m'),
]
