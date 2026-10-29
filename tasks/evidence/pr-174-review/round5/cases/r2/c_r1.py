cases += [
 ('r1-1 ${x//<<}', 'echo ${x//<<} &&\ngit commit -m hi'),
 ('r1-2 ${x/<</y}', 'x=a; echo ${x/<</y} &&\ngit push'),
 ('r1-3 $[1<<2]', 'echo $[1<<2] &&\ngit commit -m hi'),
 ('r1-4 heredoc $( # note', 'cat <<EOF\n$( # note\ngit commit -m x\n)\nEOF'),
 ('r1-5 ((echo a) # c', '((echo a) # c\ngit commit -m x)'),
 ('r1-h1 body # git commit', "cat > f <<EOF\n# don't git commit here\necho $(date)\nEOF"),
 ('r1-h2 body # git push', "cat > f <<EOF\n# then git push it\nEOF"),
 ('r1-h3 quoted body', "mkdir -p x && cat > f <<'EOF'\nthe git hook won't run\nEOF"),
 ('r1-h4 unquoted body', "cat > f <<EOF\nthe git hook won't run, git commit later\nEOF"),
]
