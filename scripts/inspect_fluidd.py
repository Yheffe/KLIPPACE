import re

with open('/tmp/component.js') as f:
    c = f.read()

print("Component length:", len(c))
matches = [m.group(0) for m in re.finditer(r'MMU_[A-Z_]+', c)]
print("MMU commands found:", set(matches))

# Look for method definitions or gcode dispatch
gcode_calls = [m.start() for m in re.finditer(r'sendGcode|action|save|startPrint', c, re.I)]
for pos in gcode_calls[:10]:
    print("Match around", pos, ":", c[max(0, pos-100):min(len(c), pos+200)])
