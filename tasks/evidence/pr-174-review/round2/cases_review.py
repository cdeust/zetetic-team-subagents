cases = [
("1 param-exp-//<<", "echo ${x//<<} &&\ngit commit -m hi"),
("2 param-exp-/<<", "x=a; echo ${x/<</y} &&\ngit push"),
("3 dollar-bracket", "echo $[1<<2] &&\ngit commit -m hi"),
("4 comment-in-kept-body", "cat <<EOF\n$( # note\ngit commit -m x\n)\nEOF"),
("5 comment-in-dparen-subsh", "((echo a) # c\ngit commit -m x)"),
("6 harmless-body-comment", "cat > hook.sh <<EOF\n#!/bin/sh\n# don't git commit from here\necho $(date)\nEOF"),
("7 harmless-body-push", "cat > run.sh <<EOF\nstamp=$(date +%s)\n# we can't git push yet\nEOF\nchmod +x run.sh"),
]
