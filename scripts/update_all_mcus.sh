#!/usr/bin/env bash
# ==============================================================================
# KLIPPACE - Automated MCU Firmware Update & Flashing Script
# Targets:
#   1. Mainboard: BigTreeTech Octopus Max EZ (STM32H723, Katapult 128KiB @ 0x8020000)
#   2. Toolhead:  BigTreeTech EBB36 GEN2      (STM32G0B1, Katapult 8KiB   @ 0x8002000)
# ==============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
KLIPPER_DIR="${HOME}/klipper"
KATAPULT_TOOL="${KLIPPER_DIR}/katapult/scripts/flashtool.py"
LOG_DIR="${HOME}/printer_data/logs"
LOG_FILE="${LOG_DIR}/mcu_update.log"
LOCK_FILE="/tmp/mcu_update.lock"
MOONRAKER_URL="http://127.0.0.1:7125"

mkdir -p "${LOG_DIR}"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$*"
    echo "${msg}" >> "${LOG_FILE}"
}

# Locking to prevent concurrent update processes
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    log "ERROR: Another MCU update process is currently running. Exiting."
    exit 1
fi

cleanup() {
    log "Cleaning up and ensuring Klipper is running..."
    curl -s -X POST "${MOONRAKER_URL}/machine/services/start?service=klipper" >/dev/null 2>&1 || true
    rm -f "${LOCK_FILE}"
}
trap cleanup EXIT

log "========================================================"
log "           KLIPPACE Automated MCU Update                "
log "========================================================"

# Step 1: Pre-flight Safety Checks
log "Checking printer state..."
PRINTER_INFO=$(curl -s --max-time 5 "${MOONRAKER_URL}/printer/info" 2>/dev/null || true)
if echo "${PRINTER_INFO}" | grep -q '"state":"printing"'; then
    log "ERROR: Printer is actively printing! Aborting MCU update for safety."
    exit 1
fi
if echo "${PRINTER_INFO}" | grep -q '"state":"paused"'; then
    log "ERROR: A print job is currently paused! Aborting MCU update for safety."
    exit 1
fi

# Step 2: Build Firmware Binaries
OCTO_CFG="${REPO_DIR}/config/mcu/config.octopus_max_ez"
EBB_CFG="${REPO_DIR}/config/mcu/config.ebb36_gen2"
BUILD_DIR="/tmp/klipper_mcu_build"
mkdir -p "${BUILD_DIR}"
OCTO_BIN="${BUILD_DIR}/klipper_octopus.bin"
EBB_BIN="${BUILD_DIR}/klipper_ebb36.bin"

if [ ! -f "${OCTO_CFG}" ]; then
    log "ERROR: Octopus config not found at ${OCTO_CFG}"
    exit 1
fi
if [ ! -f "${EBB_CFG}" ]; then
    log "ERROR: EBB36 config not found at ${EBB_CFG}"
    exit 1
fi

log "--- [1/4] Compiling Octopus Max EZ Firmware ---"
cd "${KLIPPER_DIR}"
make clean >> "${LOG_FILE}" 2>&1
cp -f "${OCTO_CFG}" "${BUILD_DIR}/kconfig_octopus"
if make KCONFIG_CONFIG="${BUILD_DIR}/kconfig_octopus" -j"$(nproc)" >> "${LOG_FILE}" 2>&1; then
    cp out/klipper.bin "${OCTO_BIN}"
    log "Octopus Max EZ firmware compiled successfully ($(wc -c < "${OCTO_BIN}") bytes)."
else
    log "ERROR: Failed to compile Octopus Max EZ firmware! Check ${LOG_FILE}"
    exit 1
fi

log "--- [2/4] Compiling EBB36 GEN2 Firmware ---"
cd "${KLIPPER_DIR}"
make clean >> "${LOG_FILE}" 2>&1
cp -f "${EBB_CFG}" "${BUILD_DIR}/kconfig_ebb36"
if make KCONFIG_CONFIG="${BUILD_DIR}/kconfig_ebb36" -j"$(nproc)" >> "${LOG_FILE}" 2>&1; then
    cp out/klipper.bin "${EBB_BIN}"
    log "EBB36 GEN2 firmware compiled successfully ($(wc -c < "${EBB_BIN}") bytes)."
else
    log "ERROR: Failed to compile EBB36 GEN2 firmware! Check ${LOG_FILE}"
    exit 1
fi

# Step 3: Stop Klipper Service
log "--- [3/4] Preparing Flashing Environment ---"
log "Stopping Klipper service to release serial interfaces..."
curl -s -X POST "${MOONRAKER_URL}/machine/services/stop?service=klipper" >> "${LOG_FILE}" 2>&1
sleep 2

# Helper function to flash an MCU via Katapult
flash_device() {
    local board_name="$1"
    local chip_pattern="$2"
    local bin_file="$3"

    log "Checking device state for ${board_name}..."
    local kat_dev=""
    local klip_dev=""

    # 1. Check if device is already in Katapult
    kat_dev=$(find /dev/serial/by-id -name "*katapult*${chip_pattern}*" 2>/dev/null | head -n1 || true)
    
    # 2. If not, check if in Klipper mode and trigger bootloader jump
    if [ -z "${kat_dev}" ]; then
        klip_dev=$(find /dev/serial/by-id -name "*Klipper*${chip_pattern}*" 2>/dev/null | head -n1 || true)
        if [ -n "${klip_dev}" ]; then
            log "Requesting Katapult bootloader on ${board_name} (${klip_dev})..."
            python3 "${KATAPULT_TOOL}" -d "${klip_dev}" -r >> "${LOG_FILE}" 2>&1 || true
            sleep 2
        fi
        
        # Wait up to 8s for Katapult serial port to enumerate
        local count=0
        while [ ${count} -lt 8 ]; do
            kat_dev=$(find /dev/serial/by-id -name "*katapult*${chip_pattern}*" 2>/dev/null | head -n1 || true)
            if [ -n "${kat_dev}" ]; then
                break
            fi
            sleep 1
            count=$((count + 1))
        done
    fi

    if [ -z "${kat_dev}" ]; then
        log "ERROR: Katapult device for ${board_name} (pattern: ${chip_pattern}) not found in /dev/serial/by-id/!"
        return 1
    fi

    log "Flashing ${board_name} on ${kat_dev}..."
    if python3 "${KATAPULT_TOOL}" -d "${kat_dev}" -f "${bin_file}" >> "${LOG_FILE}" 2>&1; then
        log "${board_name} successfully programmed and verified!"
        return 0
    else
        log "ERROR: Flashing ${board_name} failed! See ${LOG_FILE}"
        return 1
    fi
}

OCTO_PATTERN="stm32h723xx_1B0017001051313236343430"
EBB_PATTERN="stm32g0b1xx_5B002C000650505539323520"

FLASH_FAILED=0
if ! flash_device "Octopus Max EZ" "${OCTO_PATTERN}" "${OCTO_BIN}"; then
    FLASH_FAILED=1
fi
sleep 2

if ! flash_device "EBB36 GEN2" "${EBB_PATTERN}" "${EBB_BIN}"; then
    FLASH_FAILED=1
fi
sleep 2

# Step 4: Restart Klipper and Verify
log "--- [4/4] Starting Klipper & Verifying Status ---"
curl -s -X POST "${MOONRAKER_URL}/machine/services/start?service=klipper" >> "${LOG_FILE}" 2>&1

log "Waiting for Klipper to initialize..."
READY=0
for i in $(seq 1 20); do
    sleep 1
    STATUS=$(curl -s --max-time 2 "${MOONRAKER_URL}/printer/info" 2>/dev/null || true)
    if echo "${STATUS}" | grep -q '"state":"ready"'; then
        READY=1
        break
    fi
done

if [ ${READY} -eq 1 ]; then
    log "Klipper connection established: State is READY."
    
    # Query MCU versions
    MCU_QUERY=$(curl -s --max-time 3 "${MOONRAKER_URL}/printer/objects/query?mcu&mcu%20EBB" 2>/dev/null || true)
    OCTO_VER=$(echo "${MCU_QUERY}" | grep -o '"mcu_version":"[^"]*"' | head -n1 | cut -d'"' -f4 || echo "unknown")
    EBB_VER=$(echo "${MCU_QUERY}" | grep -o '"mcu_version":"[^"]*"' | tail -n1 | cut -d'"' -f4 || echo "unknown")
    
    log "========================================================"
    log "  Update Complete!"
    log "  Octopus Max EZ version: ${OCTO_VER}"
    log "  EBB36 GEN2 version:     ${EBB_VER}"
    log "========================================================"
else
    log "WARNING: Klipper did not reach READY state within 20 seconds. Check klippy.log."
fi

if [ ${FLASH_FAILED} -ne 0 ]; then
    log "WARNING: One or more MCUs encountered errors during flash. Check ${LOG_FILE}."
    exit 1
fi

log "MCU update completed successfully!"
exit 0
