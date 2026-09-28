import re

for fname in ["/home/pi/fluidd/assets/ConsoleCard-D57rnBpM.js", "/home/pi/fluidd/assets/Console-tguDUHtD.js"]:
    with open(fname, 'r', encoding='utf-8', errors='ignore') as fp:
        c = fp.read()
    print("=== FILE:", fname)
    # Search for any style, class, svg, color, warning, yellow, border, stroke
    matches = re.findall(r'class:"[^"]+"', c)
    print("Classes:", set(matches))
    for m in re.finditer(r'\{[^\}]*(?:border|stroke|fill|color|background)[^\}]*\}', c):
        print("Style match:", m.group(0)[:120])
