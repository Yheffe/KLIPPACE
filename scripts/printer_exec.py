import urllib.request
import json
import time
import sys

def exec_cmd(cmd):
    # Escape internal double quotes for Klipper gcode string parameter
    safe_cmd = cmd.replace('"', '\\"')
    payload = json.dumps({"script": f'_ACE_SYS_EXEC CMD="{safe_cmd}"'}).encode('utf-8')
    req = urllib.request.Request("http://192.168.1.168/printer/gcode/script", data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    time.sleep(1.5)
    req2 = urllib.request.Request("http://192.168.1.168/server/gcode_store?count=40")
    with urllib.request.urlopen(req2) as resp:
        store = json.loads(resp.read().decode('utf-8'))["result"]["gcode_store"]
    found = False
    for item in store:
        msg = item["message"]
        if '_ACE_SYS_EXEC' in msg:
            found = True
            continue
        if found:
            print(msg)

def send_gcode(gcode):
    payload = json.dumps({"script": gcode}).encode('utf-8')
    req = urllib.request.Request("http://192.168.1.168/printer/gcode/script", data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    time.sleep(1.0)
    req2 = urllib.request.Request("http://192.168.1.168/server/gcode_store?count=20")
    with urllib.request.urlopen(req2) as resp:
        store = json.loads(resp.read().decode('utf-8'))["result"]["gcode_store"]
    found = False
    for item in store:
        msg = item["message"]
        if gcode in msg:
            found = True
            continue
        if found:
            print(msg)

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--gcode":
        send_gcode(sys.argv[2])
    else:
        exec_cmd(sys.argv[1])
