import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

# Let's see what calls or opens uy (MmuTtgMap dialog)
print("Searching references to component uy...")
for m in re.finditer(r'<mmu-ttg-map|MmuTtgMap', c):
    idx = m.start()
    print("Match at", idx, ":", c[max(0, idx-200):min(len(c), idx+300)])
