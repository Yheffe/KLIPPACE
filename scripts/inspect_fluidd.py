with open("/home/pi/fluidd/assets/ConsoleCard-D57rnBpM.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

for i in range(3000, len(c), 150):
    print(c[i:i+150])
