import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

for m in re.finditer(r'btn\.edit_ttg_map', c):
    idx = m.start()
    print("Match at", idx, ":", c[max(0, idx-200):min(len(c), idx+300)])
