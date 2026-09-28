with open("/home/pi/fluidd/assets/ConsoleCard-D57rnBpM.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

print("ConsoleCard length:", len(c))

# Search for any SVGs or icons or border in ConsoleCard
import re
print("ConsoleCard SVGs:")
for m in re.finditer(r'<svg[^>]*>.*?</svg>', c):
    print("SVG:", m.group(0)[:150])

print("ConsoleCard keywords:")
for kw in ['bracket', 'border', 'yellow', 'warning', 'corner', 'frame', 'box', 'round', 'color', 'canvas']:
    matches = list(re.finditer(kw, c, re.I))
    print(f"Keyword '{kw}': {len(matches)} matches")
    for m in matches[:5]:
        start = max(0, m.start() - 40)
        end = min(len(c), m.end() + 40)
        print("  ...", c[start:end].replace('\n', ' '), "...")
