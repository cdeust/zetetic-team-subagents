msgs = ["fix: handle edge case", "fix: don't crash on \"empty\" input", "fix #12: it's done", "docs: explain <<EOF usage in shell", 
        "feat: add `x` flag", "fix: quote \"a\" and 'b'", "chore: bump to v1.2 (see #34)", "fix: say \"hi", "fix: c'est \"bon\" #1",
        "fix: a \"<<EOF \" b", "feat: \"$(date)\" in msg"]
for i, m in enumerate(msgs):
    cases.append((f'P{i} commit heredoc idiom', f"git commit -m \"$(cat <<'EOF'\n{m}\n\nCo-Authored-By: X <x@y>\nEOF\n)\""))
    cases.append((f'Q{i} add&&commit idiom', f"git add -A && git commit -m \"$(cat <<'EOF'\n{m}\nEOF\n)\" && git push"))
    cases.append((f'R{i} commit -F-', f"git commit -F - <<'EOF'\n{m}\nEOF"))
    cases.append((f'S{i} gh pr create', f"git push -u origin b && gh pr create --title t --body \"$(cat <<'EOF'\n## Summary\n- {m}\nEOF\n)\""))
    cases.append((f'T{i} cat > file', f"cat > /dev/null <<'EOF'\n{m}\ngit commit -am wip\nEOF\ngit status"))
cases += [
 ('U1 comment lines', '# stage everything\ngit add -A\n# commit\ngit commit -m x'),
 ('U2 for loop', 'for f in a b; do\n  echo "$f" # note it\'s\ndone\ngit push'),
 ('U3 python heredoc', "python3 - <<'PY'\nprint(\"it's #1 <<x\")\nPY\ngit commit -m done"),
 ('U4 unquoted heredoc w/ vars', 'cat > /dev/null <<EOF\nVersion: $(git describe)\nit\'s fine\nEOF\ngit push'),
 ('U5 dq subst nested quotes', 'cd "$(git rev-parse --show-toplevel)" && git commit -m "$(printf "%s" "x")"'),
 ('U6 dirname nested', 'd="$(dirname "$0")"; git -C "$d" push'),
 ('U7 heredoc in $() unquoted', 'msg=$(cat <<EOF\nhello it\'s\nEOF\n)\ngit commit -m "$msg"'),
 ('U8 grep for heredoc', 'n="$(grep -c "<<EOF" /dev/null)"\ngit commit -m x'),
 ('U9 arith shift', 'echo $(( 1 << 3 ))\ngit push'),
 ('U10 here-string', 'read a <<< "x y"\ngit push'),
 ('U11 tabs <<-', 'if true; then\n\tcat <<-EOF\n\tit\'s\n\tEOF\nfi\ngit commit -m x'),
 ('U12 jq with #', "echo '{}' | jq '.a # c'\ngit push"),
 ('U13 url #', 'curl -s https://x/y#frag >/dev/null; git push'),
 ('U14 $# arg', 'echo $# ${#x}; git commit -m x'),
 ('U15 case in subst', 'x=$(case a in a) echo y;; esac); git commit -m "$x"'),
]
