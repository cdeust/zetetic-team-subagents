# Round 9 (fixer): I2d and its siblings, a command name built at run time with
# git only in here-document data (origin/main refused all of these), plus
# controls: the same data with a built argument, never a built command name.
# A glob command name (/usr/bin/gi?) would run the real git, not the shim:
# it is pinned by tests/test_gate_targets.py only.
D = ": <<'Q'\nit's git\nQ\n"
cases = [
    ('I2d ${x}t', D + 'x=gi; ${x}t commit -m m'),
    ('N1 $(printf gi)t', D + '$(printf gi)t commit -m m'),
    ('N2 `echo gi`t', D + '`echo gi`t commit -m m'),
    ('N3 exec ${x}t', D + 'x=gi; exec ${x}t commit -m m'),
    ('N4 && ${x}t', D + 'x=gi; true && ${x}t commit -m m'),
    ('N5 then ${x}t', D + 'x=gi; if true; then ${x}t commit -m m; fi'),
    ('N6 A=1 ${x}t', D + 'x=gi; A=1 ${x}t commit -m m'),
    ('N7 env ${x}t', D + 'x=gi; env PATH="$PATH" ${x}t commit -m m'),
    ('N8 sh -c', D + "sh -c 'x=gi; ${x}t commit -m m'"),
    ('N10 {gi,}t', D + '{gi,}t commit -m m'),
    ('N11 xargs @t', D + 'echo gi | xargs -I@ @t commit -m m'),
    ('N12 suffix data', 'x=gi; ${x}t commit -m m' + "\n" + D.rstrip('\n')),
    ('N13 push', D + 'x=gi; ${x}t push'),
    ('N14 >f ${x}t', D + 'x=gi; >/dev/null ${x}t commit -m m'),
    ('N15 case a) ${x}t', D + 'x=gi; case a in a) ${x}t commit -m m;; esac'),
    ('N16 noglob ${x}t', D + 'x=gi; noglob ${x}t commit -m m 2>/dev/null || ${x}t commit -m m'),
    ('N18 <(${x}t)', D + 'x=gi; cat <(${x}t commit -m m)'),
    ('C5 echo $(date) $x', D + 'x=a; echo "$(date) $x" > /dev/null'),
    ('C1 echo $x', D + 'x=a; echo $x'),
    ('C2 gh body $(cat)', D + 'gh pr create --title t --body "$(cat /dev/null)" 2>/dev/null; true'),
    ('C3 for *.py', D + 'for f in *.py; do echo "$f"; done'),
    ('C4 x=$(date)', D + 'x=$(date); echo "$x" > /dev/null'),
]
