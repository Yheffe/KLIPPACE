with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
# Find components in ConsoleBrowser
idx = c.find("eb66d612")
if idx != -1:
    print("Near eb66d612:")
    start = max(0, idx - 1500)
    end = min(len(c), idx + 2000)
    print(c[start:end])
