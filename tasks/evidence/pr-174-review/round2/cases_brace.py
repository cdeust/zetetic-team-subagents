cases = [
("brace-group-semicolon", "{ echo a; }; git commit -m x"),
("brace-group-and", "{ echo a; } && git commit -m x"),
("body-brace-case", "cat <<EOF\n$({ case x in a) echo;; esac; }; git commit -m x)\nEOF"),
("body-brace-case-spaced", "cat <<EOF\n$({ case x in a) echo;; esac; } ; git commit -m x)\nEOF"),
]
