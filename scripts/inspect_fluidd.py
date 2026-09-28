import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

# Search for printerPrintStart or where startPrint / dialog is triggered
calls = [m.start() for m in re.finditer(r'printerPrintStart', c)]
print("printerPrintStart occurrences:", len(calls))
for idx in calls:
    print("--- Occurrence at", idx)
    print(c[max(0, idx-200):min(len(c), idx+400)])
