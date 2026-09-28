with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

idx = c.find("onOpenChanged")
print("onOpenChanged:")
print(c[idx-500:idx+300])
