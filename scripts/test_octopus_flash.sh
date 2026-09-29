#!/bin/bash
set -e

echo "=== Stopping Klipper service ==="
curl -s -X POST "http://localhost:7125/machine/services/stop?service=klipper"
sleep 3

OCTO_DEV="/dev/serial/by-id/usb-Klipper_stm32h723xx_1B0017001051313236343430-if00"
EBB_DEV="/dev/serial/by-id/usb-Klipper_stm32g0b1xx_5B002C000650505539323520-if00"

echo "=== Testing EBB36 Katapult ==="
if [ -e "$EBB_DEV" ]; then
    echo "Querying EBB36 via Katapult flashtool.py:"
    python3 /home/pi/klipper/katapult/scripts/flashtool.py -d "$EBB_DEV" -s || true
fi

echo "=== Testing Octopus Max EZ flash-sdcard ==="
if [ -e "$OCTO_DEV" ]; then
    echo "Testing flash-sdcard check on Octopus:"
    /home/pi/klipper/scripts/flash-sdcard.sh -c "$OCTO_DEV" btt-octopus-max-ez || true

    echo "Testing Katapult on Octopus:"
    python3 /home/pi/klipper/katapult/scripts/flashtool.py -d "$OCTO_DEV" -s || true
fi

echo "=== DFU check ==="
dfu-util -l || true

echo "=== Restarting Klipper service ==="
curl -s -X POST "http://localhost:7125/machine/services/start?service=klipper"
sleep 3
echo "All done!"
