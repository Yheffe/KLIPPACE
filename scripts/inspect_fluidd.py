import glob, re

for f in glob.glob("/home/pi/fluidd/assets/*.js"):
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        c = fp.read()
    if "gcode_store" in c:
        print("gcode_store in:", f)
        # Search for around gcode_store
        for m in re.finditer(r'gcode_store.{0,200}', c):
            print("  snippet:", m.group(0))
