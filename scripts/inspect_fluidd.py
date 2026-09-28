import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

for m in re.finditer(r'\$typedState\.mmu|\$typedCommit\(`mmu/', c):
    idx = m.start()
    print("Match at", idx, ":", c[max(0, idx-100):min(len(c), idx+150)])
