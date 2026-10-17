# Round-7 reviewer: blocker rows through the full hook (wrappers applied by WRAP).
G = '; git commit -m x'
TAIL = 'x=git; y=comm; $x ${y}it -m m'
cases = [
    ('S10 [[ <->#x ]]', '[[ 5 == <->#x ]]' + G),
    ('S11 case <1-9>#x', 'case 5 in <1-9>#x) echo IN;; esac' + G),
    ('S12 [[ (b|#x) ]]', '[[ a == (b|#x) ]]' + G),
    ('S13 case (b|#x)', 'case a in (b|#x) echo IN;; esac' + G),
    ('S16 ls <->#x', 'ls <->#x 2>/dev/null' + G),
    ('S17 [[ (b| #x) ]]', '[[ a == (b| #x) ]]' + G),
    ('S19 [[ (<->|#x) ]]', '[[ a == (<->|#x) ]]' + G),
    ('S21 x=<->#x', 'x=<->#x' + G),
    ('S21p x=<->#x push', 'x=<->#x; git push'),
    ('S22 delimiter git', "cat <<git\n$(x=gi; ${x}t commit -m m)\ngit"),
    ('I2d git only in data, gi${x}t', ": <<'Q'\nit's git\nQ\nx=gi; ${x}t commit -m m"),
    ('Z1 rewrite over cap', 'git status; ' + '\n' * 45000 + TAIL),
    ('Z2 input over cap', 'git status; ' + ': ' + 'a ' * 66000 + '\n' + TAIL),
    ('P1', 'cat =(echo a)#x; git commit -m x'),
    ('P2', '[[ a == (a|b)#x ]]; git commit -m x'),
    ('P3', 'case a in (a)#x) echo IN;; esac; git commit -m x'),
    ('P5', 'cat =(echo a)#x; git push'),
    ('P10', 'case b in a|(b)#x) echo IN;; esac; git commit -m x'),
    ('P11', '[[ a != (b)#x ]] && git commit -m x'),
    ('P12', 'diff =(echo a)#x =(echo a) ; git push'),
    ('I1', 'git status; x=git; y=comm; $x ${y}it -m m'),
    ('I4', 'git status; $(printf gi)t $(printf com)mit -m m'),
]
