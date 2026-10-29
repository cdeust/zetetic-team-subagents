cases += [
 ('C4', 'echo "$(echo "<<EOF ")";\ngit commit -m x\nEOF'),
 ('C5', 'v="$(printf "%s" "<<EOF ")" && echo "$v";\ngit push origin main\nEOF'),
 ('C2', 'echo "$(echo "<<X")";\ngit commit -m x\nX)'),
 ('C6', 'echo "$(echo "<<EOF ")";\ngit commit -m x\necho $\'it\\\'s\'\nEOF'),
 ('C1', "echo $'\\' <<X ' \\';\ngit commit -m x\nX"),
 ('B1', 'cat <<$(echo);\n$(echo)\ngit commit -m x\n$'),
 ('B2', 'cat <<${a;b};\n${a;b}\ngit commit -m x\n${a'),
 ('A1', 'a[1<<2]=x;\ngit commit -m hi;\n2]=x'),
 ('A2', 'a[1<<2]=x;\ngit push;\n2]=x'),
 ('A3', 'a[1<<2]=x &&\ngit commit -m x\n2]=x'),
 ('U8', 'n="$(grep -c "<<EOF" /dev/null)"\ngit commit -m x'),
]
