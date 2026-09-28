import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

# Search for where mmu/setDialogState is called with show: !0 or show: true
for m in re.finditer(r'mmu/setDialogState', c):
    idx = m.start()
    print("mmu/setDialogState at", idx, ":", c[max(0, idx-500):min(len(c), idx+300)])
