# Siblings of P1-P3 (zsh paren group not after a word character) and the indirection boundary.
cases = [
    ('P8 [[ a|(b)# ]]',   '[[ a == a|(b)#x ]]; git commit -m x'),
    ('P9 glob match',     ": > 'ab#q'; echo (ab|cd)#q; git commit -m x"),
    ('P10 case a|(b)#',   'case b in a|(b)#x) echo IN;; esac; git commit -m x'),
    ('P11 [[ != ]]',      '[[ a != (b)#x ]] && git commit -m x'),
    ('P12 =( && ',        'diff =(echo a)#x =(echo a) ; git push'),
    ('I2 var both',       'x=git; y=comm; $x ${y}it -m m'),
]
