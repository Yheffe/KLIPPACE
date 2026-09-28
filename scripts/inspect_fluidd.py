with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
# Find ConsoleBrowser component definition
for m in re.finditer(r'ConsoleBrowser.{0,100}', c):
    print("MATCH:", m.group(0))

# Or find export of D
# In ES module, find "D as ..." or "export{... D as ...}"
for m in re.finditer(r'[a-zA-Z0-9_$]+ as D[,}]', c):
    print("D is:", m.group(0))
