import glob
import os
import re

print("=== SEARCHING FOR BORDER-WARNING ===")
for f in glob.glob("/home/pi/fluidd/assets/*"):
    if f.endswith(('.js', '.css')):
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
            if "border-warning" in content:
                print(f"FOUND IN: {os.path.basename(f)}")
                for m in re.finditer(r'([^{;,\n]{0,80}border-warning[^{;,\n]{0,80})', content):
                    print("  -->", m.group(1))

print("=== SEARCHING FOR [data-v-e901643b] ===")
for f in glob.glob("/home/pi/fluidd/assets/*"):
    if f.endswith(('.js', '.css')):
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
            if "e901643b" in content:
                print(f"FOUND IN: {os.path.basename(f)}")
                for m in re.finditer(r'([^{;,\n]{0,100}e901643b[^{;,\n]{0,100})', content):
                    print("  -->", m.group(1))
