#!/bin/bash
# Where does # start a comment? Each line runs in bash and zsh; RAN printed = the
# text after # did not swallow the rest. Usage: bash comment_audit.sh
cd "$(mktemp -d)" || exit 1
while IFS= read -r c; do
  c=${c//\\n/$'\n'}
  for sh in bash zsh; do
    printf '%-5s %-42s -> %s\n' "$sh" "${c//$'\n'/|}" "$($sh -c "$c" 2>&1 < /dev/null | tr '\n' ' ' | cut -c1-60)"
  done
done <<'CASES'
echo a;#x\necho RAN
echo a|#x\ncat\necho RAN
(#x\necho RAN)
[[ a == #x ]] && echo IN\necho RAN
case a in #x\na) echo IN;; esac; echo RAN
echo a >#x; echo RAN
((1))#x; echo RAN
(echo a)#x; echo RAN
x=(a b)#c; echo RAN
echo {#x; echo RAN
echo $#x; echo RAN
{ echo a; }#x; echo RAN
[[ a == (a|b)#x ]]; echo RAN
case a in (a)#x) echo IN;; esac; echo RAN
cat =(echo a)#x; echo RAN
CASES
