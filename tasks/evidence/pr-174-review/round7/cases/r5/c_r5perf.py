VERB = ' '.join(['git', 'commit'])
D = 15
cases = [
 ('P15 "$( x15 + 200 backslashes', '"$(' * D + 'echo ' + '\\' * 200 + ')"' * D + '; ' + VERB + ' -m x'),
]
