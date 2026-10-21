cases += [
 ('P1 &> then case', 'echo "$(echo &>/dev/null case)"; git commit -m x; echo ";esac)"'),
 ('P3 assign then case', 'echo "$(a=1 case)"; git commit -m x; echo ";esac)"'),
 ('P4 a=1 then case', 'echo "$(a=1 then case)"; git commit -m x; echo ";esac)"'),
 ('P5 es\\nac missed', 'echo "$(case x in x) echo;; es\\\nac)"; git commit -m x; echo ";esac)"'),
 ('P7 &>case push', 'v="$(echo &>/dev/null case)"; git push; echo ";esac)"'),
 ('P8 in esac', 'echo "$(case x in esac)"; git commit -m x; echo ";esac)"'),
 ('R1 ${x:-{} brace', 'echo "${x:-{}"; git commit -m x; echo "}"'),
 ('R5 ${x#{} brace', 'y="${x#{}"; git push; echo "}"'),
 ('R2 ${x:-\'} in dq (zsh)', 'echo "${x:-\'}"; git commit -m x; echo "\'}"'),
 ('S1 $(cat <<EOF) then heredoc', 'x="$(cat <<EOF)"\ncat <<Y\nEOF\ntrue; git commit -m x\nY'),
 ('S2 unquoted $(cat<<EOF)', 'echo $(cat <<EOF)\ncat <<Y\nEOF\ntrue; git commit -m x\nY'),
 ('S3 $(cat<<EOF) push', 'x=$(cat <<EOF)\ncat <<Y\nEOF\nls && git push origin main\nY'),
]
