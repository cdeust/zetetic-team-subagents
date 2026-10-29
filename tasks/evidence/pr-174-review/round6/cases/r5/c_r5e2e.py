W = ": <<'Q'\nit's\nQ\n"
cases = [
 ('X1 decoy+if/then', W + 'git -C {CLEAN} commit -m y; if true; then git commit -m x; fi'),
 ('X2 decoy+"$(git commit)"', W + 'git -C {CLEAN} commit -m y; echo "$(git commit -m x)"'),
 ('X3 decoy+backtick', W + 'git -C {CLEAN} commit -m y; echo `git commit -m x`'),
 ('X4 decoy+nohup push', W + 'git -C {CLEAN} commit -m y; nohup git push'),
 ('X5 decoy+bash -c', W + 'git -C {CLEAN} commit -m y; bash -c "git commit -m x"'),
 ('X1p decoy+if/then plain', 'git -C {CLEAN} commit -m y; if true; then git commit -m x; fi'),
 ('B1w EO\\nF join', W + 'cat <<EOF\nhello\nEO\\\nF\ngit commit -m x\nEOF'),
 ('B2w EOF\\ + empty line', W + 'cat <<EOF\nEOF\\\n\ngit commit -m x\nEOF'),
 ('H3w zsh x=a(#b)', W + 'x=a(#b); git commit -m x'),
 ('Y1w zsh <<${x:-{} a}', W + 'cat <<${x:-{} a}\n${x:-{} a}\ngit commit -m x\n${x:-{}\n}'),
 ('B1p plain', 'cat <<EOF\nhello\nEO\\\nF\ngit commit -m x\nEOF'),
]
