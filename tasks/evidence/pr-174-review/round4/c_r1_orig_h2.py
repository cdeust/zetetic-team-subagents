cases=[
("harmless-kept-body-comment", "cat > hook.sh <<EOF\n#!/bin/sh\n# don't git commit from here\necho $(date)\nEOF"),
("harmless-kept-body-comment-push", "cat > run.sh <<EOF\nstamp=$(date +%s)\n# we can't git push yet\nEOF\nchmod +x run.sh"),
]
