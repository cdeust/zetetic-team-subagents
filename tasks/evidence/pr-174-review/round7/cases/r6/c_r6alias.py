cases = [
    ('A1 zsh global alias', 'alias -g c=commit\ngit c -m x'),
    ('A2 alias built verb', 'y=comm; alias -g c=${y}it\ngit c -m x'),
    ('A3 git -c alias built', 'y=comm; git -c alias.c=${y}it c -m x'),
]
