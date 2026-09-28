import re

with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

# Search for CONSOLE_RECEIVE_PREFIX or console rendering
for m in re.finditer(r'CONSOLE_RECEIVE_PREFIX.{0,300}', c):
    print("PREFIX:", m.group(0))

# Search for where console message type is handled
for m in re.finditer(r'console(?:Log|Message|Item|Entry|\/onGcodeStore).{0,200}', c):
    print("HANDLER:", m.group(0))
