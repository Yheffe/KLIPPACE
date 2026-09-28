with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
idx = c.find("var tu=")
if idx != -1:
    print("tu definition:")
    print(c[idx:idx+2500])
else:
    # search for tu=
    for m in re.finditer(r'(?:var|let|const)\s+tu\s*=', c):
        print("MATCH:", c[m.start():m.start()+2500])
