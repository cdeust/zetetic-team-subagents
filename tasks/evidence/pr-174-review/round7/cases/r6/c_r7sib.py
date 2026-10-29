# Round-7 sibling probes (fixer). L1-L3 lexable by origin/main; I2 with git only in data.
PRE = ": <<'Q'\nit's\nQ\n"
cases = [
    ('L1 -c alias.c=commit', 'git -c alias.c=commit c -m x'),
    ('L2 -c alias quoted', "git -c alias.c='commit -m x' c"),
    ('L3 zsh alias -g nl', 'alias -g c=commit\ngit c -m x'),
    ('L3w zsh alias -g nl wrapped', PRE + 'alias -g c=commit\ngit c -m x'),
    ('I2 plain', 'x=git; y=comm; $x ${y}it -m m'),
    ('I2 git in data', ": <<'Q'\nit's git\nQ\nx=git; y=comm; $x ${y}it -m m"),
    ('I2 pre', PRE + 'x=git; y=comm; $x ${y}it -m m'),
]
