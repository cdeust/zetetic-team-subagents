# Round-6 hunt cases. {CLEAN} = a sibling clean dir (decoy target).
cases = [
    # zsh: a word-start or =( group followed by # is one word, not a comment
    ('P1 =(..)#',        'cat =(echo a)#x; git commit -m x'),
    ('P2 [[ (a|b)# ]]',  '[[ a == (a|b)#x ]]; git commit -m x'),
    ('P3 case (a)#x)',   'case a in (a)#x) echo IN;; esac; git commit -m x'),
    ('P4 [[ (a)#x ]] nl', '[[ a == (a)#x ]]\ngit commit -m x'),
    ('P5 =(..)# push',   'cat =(echo a)#x; git push'),
    ('P6 [[ x = (a)#]]', '[[ x = (x)# ]] && git commit -m x'),
    ('P7 (a|b)# glob ok', 'touch ab; echo (ab|cd)#q; git commit -m x'),
    # variable / IFS / alias indirection (no literal verb after git)
    ('I1 var verb',      'git status; x=git; y=comm; $x ${y}it -m m'),
    ('I2 var both',      'x=git; y=comm; $x ${y}it -m m'),
    ('I3 IFS bash',      'git status; git${IFS}com""mit -m m'),
    ('I4 printf',        'git status; $(printf gi)t $(printf com)mit -m m'),
    # heredoc pending while a $( spans lines on the operator line
    ('H1 $( nl on heredoc line', 'cat <<EOF $(echo a\nEOF\n)\ngit commit -m x\nEOF'),
    ('H2 glob ( nl on heredoc line', 'cat <<EOF; echo a(\nEOF\n)\ngit commit -m x\nEOF'),
    ('H3 ${ nl on heredoc line', 'cat <<EOF ${x:-a\nEOF\n}\ngit commit -m x\nEOF'),
    ('H4 "..." nl on heredoc line', 'cat <<EOF "a\nEOF\n"\ngit commit -m x\nEOF'),
    ('H5 `..` nl on heredoc line', 'cat <<EOF `echo a\nEOF\n`\ngit commit -m x\nEOF'),
    ('H6 =( nl on heredoc line', 'cat <<EOF =(echo a\nEOF\n)\ngit commit -m x\nEOF'),
    ('H7 [[ ( nl on heredoc line', 'cat <<EOF; [[ a == (a\nEOF\n) ]]\ngit commit -m x\nEOF'),
    # <<- with joined lines and tabs
    ('J1 <<- join tab', 'cat <<-EOF\n\tEO\\\n\tF\ngit commit -m x\nEOF'),
    ('J2 <<- join',     'cat <<-EOF\n\tEO\\\nF\ngit commit -m x\nEOF'),
    ('J3 join quoted no', "cat <<'EOF'\nEO\\\nF\ngit commit -m x\nEOF"),
    ('J4 join even bs',  'cat <<EOF\nEO\\\\\nF\ngit commit -m x\nEOF'),
    ('J5 join to delim', 'cat <<EOF\nx\\\nEOF\ngit commit -m x\nEOF'),
    # delimiter word variants
    ('D1 <<$(git)',     'cat <<$(git commit -m x)\nfoo\n$(git commit -m x)'),
    ('D2 <<`git`',      'cat <<`git commit -m x`\nfoo\n`git commit -m x`'),
    ('D3 <<${x:=..}',   'cat <<${x:=$(git commit -m x)}\nfoo\n${x:=$(git commit -m x)}'),
    ('D4 <<"${x:-{} a}"', 'cat <<"${x:-{} a}"\n${x:-{} a}\ngit commit -m x\n"${x:-{}"\n${x:-{}\n}'),
    ('D5 <<$(${x:-{} a})', 'cat <<$(${x:-{} a})\n$(${x:-{} a})\ngit commit -m x\n$(${x:-{})\n}'),
    # selectors and wrappers
    ('S1 exec git',      'exec git commit -m x'),
    ('S2 env git',       'env git commit -m x'),
    ('S3 command git',   'command git commit -m x'),
    ('S4 nohup git',     'nohup git push'),
    ('S5 \\git',          '\\git commit -m x'),
    ('S6 GIT_WORK_TREE', 'GIT_WORK_TREE=. git commit -m x'),
    ('S7 --work-tree',   'git --work-tree=. commit -m x'),
    ('S8 -c core.wt',    'git -c core.worktree=. commit -m x'),
    ('S9 builtin exec',  'builtin exec git commit -m x'),
    # decoys with the new rule
    ('X7 decoy + =(..)#', 'git -C {CLEAN} commit -m y; cat =(echo a)#x; git commit -m x'),
    ('X8 decoy + [[ ]]#', 'git -C {CLEAN} commit -m y; [[ a == (a|b)#x ]]; git commit -m x'),
]
