with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

idx = c.find("map_slicer_tools")
print("map_slicer_tools index:", idx)
if idx != -1:
    print(c[idx-300:idx+2000])
