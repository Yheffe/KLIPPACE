with open("/home/pi/fluidd/assets/Console-tguDUHtD.js", 'r', encoding='utf-8', errors='ignore') as fp:
    c = fp.read()

print("Console-tguDUHtD length:", len(c))
print("Console-tguDUHtD content preview:")
for chunk in [c[i:i+400] for i in range(0, min(len(c), 4000), 400)]:
    print("--- CHUNK ---")
    print(chunk)
