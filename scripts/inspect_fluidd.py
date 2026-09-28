with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

idx = c.find("class Xl")
if idx == -1:
    idx = c.find("var Xl=")
if idx == -1:
    idx = c.find("Xl=")
print("Xl definition:")
print(c[idx:idx+1500])
