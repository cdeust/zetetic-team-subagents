W = ": <<'Q'\nit's\nQ\n"
cases += [
 ('Z1 plain', 'echo ${x:-{} <<EOF }\ngit commit -m x\nEOF'),
 ('Z1 wrapped', W + 'echo ${x:-{} <<EOF }\ngit commit -m x\nEOF'),
 ('Z2 wrapped push', W + 'echo ${x:-{} <<EOF }\ngit push\nEOF'),
 ('Z7 plain', 'echo "$(case x { x) echo ;; })"; git commit -m x; echo ";esac)"'),
 ('Z7 wrapped', W + 'echo "$(case x { x) echo ;; })"; git commit -m x; echo ";esac)"'),
]
