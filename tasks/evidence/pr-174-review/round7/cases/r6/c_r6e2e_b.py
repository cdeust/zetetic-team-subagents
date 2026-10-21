PRE = ": <<'Q'\nit's\nQ\n"
SUF = "\n: <<'Q'\nit's\nQ"
ANSI = "echo $'\\''\n"
base = [
    ('P2', '[[ a == (a|b)#x ]]; git commit -m x'),
    ('P3', 'case a in (a)#x) echo IN;; esac; git commit -m x'),
    ('P5', 'cat =(echo a)#x; git push'),
    ('P10', 'case b in a|(b)#x) echo IN;; esac; git commit -m x'),
    ('P11', '[[ a != (b)#x ]] && git commit -m x'),
    ('P12', 'diff =(echo a)#x =(echo a) ; git push'),
    ('I1', 'git status; x=git; y=comm; $x ${y}it -m m'),
    ('I4', 'git status; $(printf gi)t $(printf com)mit -m m'),
]
cases = []
for n, c in base:
    cases += [(n + ' plain', c), (n + ' pre', PRE + c), (n + ' suf', c + SUF), (n + ' ansi', ANSI + c)]
