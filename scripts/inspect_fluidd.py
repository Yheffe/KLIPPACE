with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

idx = c.find("localTtgMap")
print("localTtgMap index:", idx)
# Find the component enclosing this
start = max(0, idx - 4000)
end = min(len(c), idx + 6000)
with open("/tmp/component.js", "w") as out:
    out.write(c[start:end])
print("Wrote /tmp/component.js, size:", end-start)
