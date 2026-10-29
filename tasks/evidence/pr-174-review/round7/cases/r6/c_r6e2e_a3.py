C = 'y=comm; git -c alias.c=${y}it c -m x'
cases = [('A3 plain', C), ('A3 pre', ": <<'Q'\nit's\nQ\n" + C), ('A3 suf', C + "\n: <<'Q'\nit's\nQ"), ('A3 ansi', "echo $'\\''\n" + C)]
