cases = [
("herestring-hash-semi", "cat <<<#x; git commit -m x"),
("herestring-sp-hash-semi", "cat <<< #x; git commit -m x"),
("redir-out-hash-semi", "echo a >#x; git commit -m x"),
("redir-in-hash-semi", "cat <#x; git commit -m x"),
("redir-append-hash", "echo a >>#x; git commit -m x"),
("redir-fd-hash", "echo a 2>#x; git commit -m x"),
("heredoc-op-then-hash-word", "cat <<#x\nbody\n#x\ngit commit -m x"),
("amp-hash", "echo a&#x\ngit commit -m x"),
("dparen-comment-heredoc", "((1))#a <<EOF\ngit commit -m x\nEOF"),
]
