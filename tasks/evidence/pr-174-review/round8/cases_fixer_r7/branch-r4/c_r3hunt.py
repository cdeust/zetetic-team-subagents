cases += [
 # P: over-extension of $( inside "..." by a case head counts but bash does not
 ('P1 &> then case', 'echo "$(echo &>/dev/null case)"; git commit -m x; echo ";esac)"'),
 ('P2 redirect then case', 'echo "$(>/dev/null case)"; git commit -m x; echo ";esac)"'),
 ('P3 assign then case', 'echo "$(a=1 case)"; git commit -m x; echo ";esac)"'),
 ('P4 a=1 then case', 'echo "$(a=1 then case)"; git commit -m x; echo ";esac)"'),
 ('P5 es\\nac missed', 'echo "$(case x in x) echo;; es\\\nac)"; git commit -m x; echo ";esac)"'),
 ('P6 2>x case', 'echo "$(2>/dev/null case)"; git commit -m x; echo ";esac)"'),
 ('P7 &>case push', 'v="$(echo &>/dev/null case)"; git push; echo ";esac)"'),
 # Q: under-extension: reserved case missed by head
 ('Q1 ca\\nse missed', 'echo "$(ca\\\nse x in x) echo "<<EOF";; esac)"\ngit commit -m x\nEOF'),
 ('Q2 in esac', 'echo "$(case x in esac; echo "<<EOF")"\ngit commit -m x\nEOF'),
 # R: ${...} brace / quote counting vs bash
 ('R1 ${x:-{} brace', 'echo "${x:-{}"; git commit -m x; echo "}"'),
 ('R2 ${x:-\'} in dq', 'echo "${x:-\'}"; git commit -m x; echo "\'}"'),
 ('R3 ${x:-{} unquoted', 'echo ${x:-{} <<EOF }\ngit commit -m x\nEOF'),
 ('R4 dq ${x:-\'} <<', 'echo "${x:-\'}" <<EOF "\'}"\ngit commit -m x\nEOF'),
 # S: heredoc pending at ) of $()
 ('S1 $(cat <<EOF) then heredoc', 'x="$(cat <<EOF)"\ncat <<Y\nEOF\ntrue; git commit -m x\nY'),
 ('S2 unquoted $(cat<<EOF)', 'echo $(cat <<EOF)\ncat <<Y\nEOF\ntrue; git commit -m x\nY'),
 # T: compound array subscript
 ('T1 a=([1<<2]=x)', 'a=([1<<2]=x);\ngit commit -m x\n2]=x)'),
 ('T2 a=([1<<2]=x) &&', 'a=([1<<2]=x) &&\ngit commit -m x\n2]=x)'),
 ('T3 a+=([1<<2]=x)', 'a+=([1<<2]=x);\ngit push\n2]=x)'),
 # U: comment after redirection
 ('U1 >#', 'echo >#x; git commit -m x'),
 ('U2 >#2', 'echo hi >#x\ngit commit -m x'),
 # V: let / declare / [[
 ('V1 let', 'let x=1<<2;\ngit commit -m x\n2'),
 ('V2 [[ <<', '[[ a<<b ]];\ngit commit -m x\nb'),
 ('V3 for ((', 'for ((i=1<<2;i<0;i++)); do :; done; git commit -m x'),
 # W: case word-state
 ('W1 time case', 'x=$(time case a in a) echo;; esac); git commit -m x'),
 ('W2 ! case', 'x=$(! case a in a) echo;; esac); git commit -m x'),
 ('W3 case arg in $()', 'x="$(echo case)" <<EOF\nEOF\ngit commit -m x'),
]
