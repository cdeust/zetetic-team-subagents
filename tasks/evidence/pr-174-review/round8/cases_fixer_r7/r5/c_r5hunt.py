cases = [
 # comment recognition: head treats # after these as a comment
 ('H1 >#x', 'echo a >#x; git commit -m x'),
 ('H2 <#x', 'echo a <#x; git commit -m x'),
 ('H3 zsh glob (#', 'x=a(#b); git commit -m x'),
 ('H4 zsh glob (# echo', 'echo a(|#b)(N); git commit -m x'),
 ('H5 )#', '(true)#x; git commit -m x'),
 ('H6 ((x))#', '((1))#x; git commit -m x'),
 ('H7 <<<#', 'cat <<<#x; git commit -m x'),
 ('H8 &#', 'true &#x; git commit -m x'),
 ('H9 |#', 'true |#x; git commit -m x'),
 ('H10 zsh *(#q', 'echo *(#qN); git commit -m x'),
 ('H11 >|#', 'echo a >|#x; git commit -m x'),
 ('H12 2>#', 'echo a 2>#x; git commit -m x'),
 ('H13 zsh x(#)', 'echo x(N#); git commit -m x'),
 # heredoc delimiter after backslash-newline join in body
 ('B1 EO\\nF', 'cat <<EOF\nhello\nEO\\\nF\ngit commit -m x\nEOF'),
 ('B2 EOF\\n', 'cat <<EOF\nEOF\\\n\ngit commit -m x\nEOF'),
 ('B3 quoted EO\\nF', "cat <<'EOF'\nhello\nEO\\\nF\ngit commit -m x\nEOF"),
 # outer pending heredoc and newline inside $(...)
 ('S1 pending outer, nl in $(', 'cat <<EOF $(echo a\nEOF\n)\ngit commit -m x\nEOF'),
 ('S2 pending outer, nl in "$(', 'cat <<EOF "$(echo a\nEOF\n)"\ngit commit -m x\nEOF'),
 ('S3 pending outer, nl in `', 'cat <<EOF `echo a\nEOF\n`\ngit commit -m x\nEOF'),
 ('S4 pending outer, nl in ${', 'cat <<EOF ${x:-a\nEOF\n}\ngit commit -m x\nEOF'),
 ('S5 pending outer, nl in "', 'cat <<EOF "a\nEOF\n"\ngit commit -m x\nEOF'),
 ('S6 pending outer, nl in ((', 'cat <<EOF; ((1\nEOF\n))\ngit commit -m x\nEOF'),
 ('S7 pending outer, nl in <(', 'cat <<EOF <(echo a\nEOF\n)\ngit commit -m x\nEOF'),
 # zsh heredoc delimiter word with ${...} that zsh ends later
 ('Y1 zsh delim ${x:-{} a}', 'cat <<${x:-{} a}\n${x:-{} a}\ngit commit -m x\n${x:-{}\n}'),
 ('Y2 zsh delim ${x:-{} a} b', 'cat <<${x:-{}a}\n${x:-{}a}\ngit commit -m x\n${x:-{}\n'),
]
