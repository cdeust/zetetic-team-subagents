cases += [
 ('C4 dq-$() plain delim', 'echo "$(echo "<<EOF ")";\ngit commit -m x\nEOF'),
 ('C5 dq-$() push', 'v="$(printf "%s" "<<EOF ")" && echo "$v";\ngit push origin main\nEOF'),
 ('A3 a[1<<2] && form', 'a[1<<2]=x &&\ngit commit -m x\n2]=x'),
]
