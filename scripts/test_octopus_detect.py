#!/usr/bin/env python3
import urllib.request
import subprocess
import time
import os

MOONRAKER_URL = "http://127.0.0.1:7125"

def moonraker_service(action, service="klipper"):
    url = f"{MOONRAKER_URL}/machine/services/{action}?service={service}"
    req = urllib.request.Request(url, data=b"", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        return f"Error: {e}"

def run_cmd(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.stdout.decode('utf-8', errors='replace').strip()
    except Exception as e:
        return f"Error running {cmd}: {e}"

def main():
    log = []
    log.append("=== Starting Octopus Max EZ Flash Detection ===")
    
    try:
        # Step 1: Stop Klipper
        log.append("Stopping Klipper...")
        moonraker_service("stop")
        time.sleep(3)
        
        octo_dev = "/dev/serial/by-id/usb-Klipper_stm32h723xx_1B0017001051313236343430-if00"
        ebb_dev = "/dev/serial/by-id/usb-Klipper_stm32g0b1xx_5B002C000650505539323520-if00"
        
        # Test EBB36 Katapult detection
        log.append("\n--- Testing EBB36 Katapult ---")
        if os.path.exists(ebb_dev):
            log.append("Device exists. Testing Katapult query:")
            out = run_cmd(f"python3 /home/pi/klipper/katapult/scripts/flashtool.py -d {ebb_dev} -s", timeout=8)
            log.append(out)
        else:
            log.append(f"{ebb_dev} not found!")

        # Test Octopus Max EZ
        log.append("\n--- Testing Octopus Max EZ ---")
        if os.path.exists(octo_dev):
            log.append(f"Device exists: {octo_dev}")
            
            # Check 1: Katapult status query
            log.append("Check 1: Katapult status query:")
            out_kat = run_cmd(f"python3 /home/pi/klipper/katapult/scripts/flashtool.py -d {octo_dev} -s", timeout=8)
            log.append(out_kat)
            
            # Check 2: flash-sdcard check
            log.append("Check 2: flash-sdcard verify:")
            out_sd = run_cmd(f"/home/pi/klipper/scripts/flash-sdcard.sh -c {octo_dev} btt-octopus-max-ez", timeout=12)
            log.append(out_sd)
            
            # Check 3: DFU list
            log.append("Check 3: dfu-util -l:")
            out_dfu = run_cmd("dfu-util -l", timeout=8)
            log.append(out_dfu)
        else:
            log.append(f"{octo_dev} not found!")
            
    finally:
        # Step 2: Always restart Klipper!
        log.append("\nRestarting Klipper...")
        moonraker_service("start")
        time.sleep(3)
        log.append("Klipper restarted.")
        
        with open("/tmp/octopus_test.log", "w") as f:
            f.write("\n".join(log) + "\n")

if __name__ == "__main__":
    main()
