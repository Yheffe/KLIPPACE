with open("/home/pi/fluidd/assets/index-D-yWxGqL.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

idx = 174644
print("Around 174644:")
print(c[idx-1000:idx+500])
