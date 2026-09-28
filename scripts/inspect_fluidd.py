with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
matches = [m.start() for m in re.finditer(r'mmu/setDialogState', c)]
print("Total occurrences of mmu/setDialogState:", len(matches))
for idx in matches:
    print("At", idx, ":", c[idx-50:idx+150])
