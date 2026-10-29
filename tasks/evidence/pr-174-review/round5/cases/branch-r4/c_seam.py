# Round-3 seam probe: case positions not in OPENERS, and the still-open forms.
cases += [
 ('P1 time -p case', 'cat <<EOF\n$(time -p case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P2 coproc case', 'cat <<EOF\n$(coproc case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P3 function brace case', 'cat <<EOF\n$(f() { case x in a) echo;; esac; }; git commit -m x)\nEOF'),
 ('P4 newline case', 'cat <<EOF\n$(echo\ncase x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P5 top-level time -p case', 'x=$(time -p case x in a) echo;; esac)#y; git commit -m x'),
 ('O1 if then git', 'if true; then git commit -m x; fi'),
 ('O2 nohup git', 'nohup git push'),
 ('O3 dq subst git', 'echo "$(git commit -m x)"'),
]
cases += [
 ('P6 assignment case', 'cat <<EOF\n$(A=1 case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P7 pipe case', 'cat <<EOF\n$(echo | case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P8 and case', 'cat <<EOF\n$(true && case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P9 while case', 'cat <<EOF\n$(while case x in a) false;; esac; do :; done; git commit -m x)\nEOF'),
 ('P10 time -p -- case', 'cat <<EOF\n$(time -p -- case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P11 echo then case', 'echo $(echo then case)#x; git commit -m y'),
 ('P12 command case', 'echo $(command case)#x; git commit -m y'),
 ('P13 time echo case', 'echo $(time echo case)#x; git commit -m y'),
 ('P14 redir case', 'cat <<EOF\n$(>/dev/null case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P15 esac arg', 'cat <<EOF\n$(case x in a) echo esac;; esac; git commit -m x)\nEOF'),
 ('P16 nested case', 'cat <<EOF\n$(case x in a) case y in b) :;; esac;; esac; git commit -m x)\nEOF'),
]
cases += [
 ('P17 io-number redir case', 'cat <<EOF\n$(2>/dev/null case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P18 redir after cmd', 'echo $(echo >/dev/null case)#x; git commit -m y'),
 ('P19 herestring case', 'cat <<EOF\n$(<<<x case x in a) echo;; esac; git commit -m x)\nEOF'),
 ('P20 fd dup case', 'cat <<EOF\n$(2>&1 case x in a) echo;; esac; git commit -m x)\nEOF'),
]
cases += [
 ('P21 >&2 arg case', 'echo $(echo >&2 case)#x; git commit -m y'),
 ('P22 >| arg case', 'echo $(echo >|/dev/null case)#x; git commit -m y'),
 ('P23 &> case', 'cat <<EOF\n$(&>/dev/null case x in a) echo;; esac; git commit -m x)\nEOF'),
]
