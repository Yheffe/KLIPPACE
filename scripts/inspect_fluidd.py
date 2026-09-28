with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
# Find definition of Ql
idx = c.find("var Ql=")
if idx != -1:
    print("Ql definition:")
    print(c[idx:idx+2500])
else:
    for m in re.finditer(r'(?:var|let|const)\s+Ql\s*=', c):
        print("MATCH:", c[m.start():m.start()+2500])
