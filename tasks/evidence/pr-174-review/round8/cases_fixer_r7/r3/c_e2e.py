cases += [
 ('A1 a[1<<2] terminated', 'a[1<<2]=x;\ngit commit -m hi;\n2]=x'),
 ('B1 <<$(x) delim', 'cat <<$(echo);\n$(echo)\ngit commit -m x\n$'),
 ('C1 ansi-c desync', "echo $'\\' <<X ' \\';\ngit commit -m x\nX"),
 ('C2 dq-$() desync', 'echo "$(echo "<<X")";\ngit commit -m x\nX)'),
 ('C4 dq-$() plain delim', 'echo "$(echo "<<EOF ")";\ngit commit -m x\nEOF'),
 ('control plain commit', 'git commit -m x'),
]
