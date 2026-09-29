#!/usr/bin/env bash
# ==============================================================================
# KLIPPACE - Automatic Post-Update Installer
# Runs automatically after Moonraker pulls KLIPPACE updates.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== KLIPPACE Update Post-Hook ==="

# 1. Update executable permissions
chmod +x "${REPO_DIR}/scripts/"*.sh 2>/dev/null || true

# 2. Symlink MCU updater script to /home/pi/scripts/
mkdir -p "${HOME}/scripts"
ln -sf "${REPO_DIR}/scripts/update_all_mcus.sh" "${HOME}/scripts/update_all_mcus.sh"

# 3. Copy MCU build configs (avoid symlinking so make doesn't dirty git repo)
mkdir -p "${HOME}/mcu_configs"
rm -f "${HOME}/mcu_configs/config.octopus_max_ez" "${HOME}/mcu_configs/config.ebb36_gen2"
cp -f "${REPO_DIR}/config/mcu/config.octopus_max_ez" "${HOME}/mcu_configs/config.octopus_max_ez"
cp -f "${REPO_DIR}/config/mcu/config.ebb36_gen2" "${HOME}/mcu_configs/config.ebb36_gen2"

# 4. Symlink Moonraker ace_status component
if [ -d "${HOME}/moonraker/moonraker/components" ]; then
    ln -sf "${REPO_DIR}/acepro-mmu-dashboard/moonraker/ace_status.py" "${HOME}/moonraker/moonraker/components/ace_status.py"
fi

# 5. Symlink macros to printer_data/config
ln -sf "${REPO_DIR}/config/voron24/ace_voron24_macros.cfg" "${HOME}/printer_data/config/ace_voron24_macros.cfg"

echo "=== KLIPPACE Post-Hook Finished Successfully ==="
