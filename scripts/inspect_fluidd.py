import glob
import os
import re

print("=== SEARCHING FLUIDD ASSETS ===")
js_files = glob.glob("/home/pi/fluidd/assets/*.js")
css_files = glob.glob("/home/pi/fluidd/assets/*.css")

for f in css_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        content = fp.read()
        matches = re.findall(r'[^{}]*\{[^{}]*(?:border|outline|box-shadow)[^{}]*\}', content)
        for m in matches:
            if any(k in m for k in ['console', 'warning', 'amber', 'yellow', 'gold', 'orange', 'card', 'group']):
                print(f"[{os.path.basename(f)}] {m[:150]}")

print("=== SEARCHING JS FOR CONSOLE CARD / PRINT BORDER ===")
for f in js_files:
    if "Console" in f or "Dashboard" in f or "index" in f:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
            for m in re.finditer(r'(?:border|outline|bracket|highlight|group|print_stats)[^;,\{\}]{0,50}', content, re.I):
                s = m.group(0)
                if any(k in s.lower() for k in ['color', 'warning', 'style', 'class', 'console']):
                    print(f"[{os.path.basename(f)}] {s}")
