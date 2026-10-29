cases=[
("control-heredoc-commit", "mkdir -p notes && cat > notes/a.txt <<'EOF'\nthe git hook won't run\nEOF\ngit commit -m fix"),
("param-exp-<<", "echo ${x//<<} &&\ngit commit -m hi"),
("param-exp-push", "x=a; echo ${x/<</y} &&\ngit push"),
("dollar-bracket", "echo $[1<<2] &&\ngit commit -m hi"),
("comment-in-kept-body", "cat <<EOF\n$( # note\ngit commit -m x\n)\nEOF"),
("comment-in-dparen-subshell", "((echo a) # c\ngit commit -m x)"),
]
