with open('/tmp/component.js') as f:
    c = f.read()

idx = c.find("async commit()")
print("commit method:")
print(c[idx:idx+800])
