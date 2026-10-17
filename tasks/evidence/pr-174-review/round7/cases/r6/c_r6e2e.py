W = ": <<'Q'\nit's\nQ\n"
cases = [
    ('P1 plain', 'cat =(echo a)#x; git commit -m x'),
    ('P1 wrapped', W + 'cat =(echo a)#x; git commit -m x'),
    ('P2 wrapped', W + '[[ a == (a|b)#x ]]; git commit -m x'),
    ('P3 wrapped', W + 'case a in (a)#x) echo IN;; esac; git commit -m x'),
    ('P5 wrapped push', W + 'cat =(echo a)#x; git push'),
    ('P1 suf-wrapped', 'cat =(echo a)#x; git commit -m x\n' + ": <<'Q'\nit's\nQ"),
    ('P1 ansi-wrapped', "echo $'\\''\ncat =(echo a)#x; git commit -m x"),
    ('I1 wrapped', W + 'git status; x=git; y=comm; $x ${y}it -m m'),
    ('I4 wrapped', W + 'git status; $(printf gi)t $(printf com)mit -m m'),
    ('C7 cost', "cat <<'EOF'\ndon't\nEOF\ngit commit -m x"),
]
