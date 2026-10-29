# Round-7 reviewer: common real commit/push/gh forms agents issue. A shell "runs" the shim git.
HD = "git commit -m \"$(cat <<'EOF'\n%s\nEOF\n)\""
BODY1 = "fix(gates): don't drop # after ) (#174)\n\nThe gate's rewrite (scope) keeps `x` and $VAR text.\n## Notes\n- it's fine (#12)\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
BODY2 = "feat(x): y\n\n(see #123) and (scope)#tag; it's $(not run) `nor this`"
cases = [
    ('K1 heredoc commit body', HD % BODY1),
    ('K2 heredoc commit body2', HD % BODY2),
    ('K3 add && commit (#174)', 'git add -A && git commit -m "fix(x): y (#174)"'),
    ('K4 cd && push -u', 'cd {CLEAN} && git push -u origin HEAD'),
    ('K5 commit #123', 'git commit -m "closes #123"'),
    ('K6 commit (scope)', "git commit -m 'refactor(scope): z'"),
    ('K7 commit $VAR', 'git commit -m "bump to $VERSION"'),
    ('K8 commit backticks', 'git commit -m "use `foo` here"'),
    ('K9 gh pr create body', "gh pr create --title \"fix(x): y (#174)\" --body \"$(cat <<'EOF'\n## Summary\n- it's (#174)\n- `code` $VAR (scope)#x\n\n## Test plan\n- [ ] run\nEOF\n)\""),
    ('K10 commit -F - unquoted heredoc', "git commit -F - <<EOF\nfix(x): y (#174)\n\nit's (scope)#x\nEOF"),
    ('K11 add; commit; push', 'git add f && git commit -m "x" && git push'),
    ('K12 commit then comment', 'git commit -m x  # (#174) it\'s done'),
    ('K13 subshell push comment', '(cd {CLEAN} && git push) # push it'),
    ('K14 write then git add (apostrophe)', "cat > f.md <<'EOF'\nit's the git notes (#174)\nEOF\ngit add f.md"),
    ('K15 write then git status', "cat > f.md <<'EOF'\nthe hook won't run git\nEOF\ngit status"),
    ('K16 write then git diff', "cat > f.md <<'EOF'\ndon't\nEOF\ngit diff --stat"),
    ('K17 write then commit', "cat > f.md <<'EOF'\ndon't\nEOF\ngit add f.md && git commit -m \"docs: f (#174)\""),
    ('K18 write prose only', "mkdir -p x && cat > x/f <<'EOF'\nthe git hook won't run\nEOF"),
    ('K19 commit amend no-edit', 'git commit --amend --no-edit'),
    ('K20 git -C push', 'git -C {CLEAN} push origin HEAD:refs/heads/x'),
    ('K21 commit -m multi', 'git commit -m "fix(x): y" -m "body (#174)" -m "it\'s ok"'),
    ('K22 heredoc commit, subject with (#n)', "git add -A && git commit -m \"$(cat <<'EOF'\nfix(gates): a (#174)\nEOF\n)\" && git push -u origin HEAD"),
    ('K23 printf commit', "git commit -m \"$(printf 'a\\n\\nb (#1)')\""),
    ('K24 gh pr edit body-file', "gh pr edit 174 --body-file - <<'EOF'\nit's (#174)\nEOF"),
    ('K25 commit after cd subshell', 'cd {CLEAN} && (git add -A) && git commit -m "x (#9)"'),
    ('K26 zsh glob flag add', 'git add (#i)readme* && git commit -m x'),
    ('K27 subshell)#comment', '(git add -A)# stage\ngit commit -m x'),
    ('K28 echo note then commit', 'echo "done (#174)"; git commit -m "y"'),
]
