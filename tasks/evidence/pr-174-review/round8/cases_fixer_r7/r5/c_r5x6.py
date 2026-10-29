W = ": <<'Q'\nit's\nQ\n"
G = 'git'
cases = [
 ('X6 commit inside decoy segment', W + G + ' -C {CLEAN} commit -m "$(' + G + ' commit -m x)"'),
 ('X6p plain', G + ' -C {CLEAN} commit -m "$(' + G + ' commit -m x)"'),
]
