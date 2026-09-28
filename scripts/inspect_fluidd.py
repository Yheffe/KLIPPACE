import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

# Search for where startPrint or mmu dialog is shown when clicking print on a file
for m in re.finditer(r'mmu/setDialogState|\.show=true|dialog\.show\s*=', c):
    idx = m.start()
    print("Match at", idx, ":", c[max(0, idx-100):min(len(c), idx+150)])

# Also search for "print" button click in file list:
for m in re.finditer(r'printerPrintStart', c):
    idx = m.start()
    print("printerPrintStart at", idx, ":", c[max(0, idx-150):min(len(c), idx+200)])
