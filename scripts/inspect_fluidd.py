with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

import re
idx = c.find("class Zl")
if idx == -1:
    idx = c.find("var Zl=")
if idx == -1:
    idx = c.find("Zl=")
print("Zl definition:")
print(c[idx-50:idx+1500])
