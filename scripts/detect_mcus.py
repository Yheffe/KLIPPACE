#!/usr/bin/env python3
import urllib.request
import subprocess
import time
import sys
import os

MOONRAKER_URL = "http://127.0.0.1:7125"

def moonraker_service(action, service="klipper"):
    url = f"{MOONRAKER_URL}/machine/services/{action}?service={service}"
    req = urllib.request.Request(url, data=b"", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        return f"Error: {e}"

def run_cmd(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.stdout.decode('utf-8', errors='replace').strip()
    except Exception as e:
        return f"Error running {cmd}: {e}"

def main():
    print("=== Step 1: Stopping Klipper via Moonraker ===")
    res = moonraker_service("stop")
    print("Stop response:", res)
    time.sleep(3)

    print("\n=== Step 2: Checking Serial Ports ===")
    print(run_cmd("ls -la /dev/serial/by-id/"))

    print("\n=== Step 3: Testing EBB36 Katapult Status ===")
    ebb_dev = "/dev/serial/by-id/usb-Klipper_stm32g0b1xx_5B002C000650505539323520-if00"
    if os.path.exists(ebb_dev):
        print("Querying Katapult on EBB36:")
        out = run_cmd(f"python3 /home/pi/klipper/katapult/scripts/flashtool.py -d {ebb_dev} -s", timeout=10)
        print(out)
    else:
        print("EBB36 device path not found!")

    print("\n=== Step 4: Testing Octopus Max EZ SDCard / Bootloader ===")
    octo_dev = "/dev/serial/by-id/usb-Klipper_stm32h723xx_1B0017001051313236343430-if00"
    if os.path.exists(octo_dev):
        print("Testing flash-sdcard check on Octopus Max EZ:")
        out = run_cmd(f"/home/pi/klipper/scripts/flash-sdcard.sh -c {octo_dev} btt-octopus-max-ez", timeout=15)
        print(out)
        print("Testing Katapult query on Octopus Max EZ:")
        out_kat = run_cmd(f"python3 /home/pi/klipper/katapult/scripts/flashtool.py -d {octo_dev} -s", timeout=10)
        print(out_kat)
    else:
        print("Octopus device path not found!")

    print("\n=== Step 5: Checking DFU devices ===")
    print(run_cmd("dfu-util -l"))

    print("\n=== Step 6: Restarting Klipper ===")
    res_start = moonraker_service("start")
    print("Start response:", res_start)
    time.sleep(3)
    print("Klipper status:", moonraker_service("status"))

if __name__ == "__main__":
    main()
