#!/bin/bash

# =============================================================================
# ACE Pro / KLIPPACE - Clean Uninstaller Script
# =============================================================================
# Safely removes acepro-any-klipper / KLIPPACE extensions, dashboard files,
# Moonraker component, KlipperScreen panels, and configuration includes.
#
# Usage: ./uninstaller.sh
# =============================================================================

set -u

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_info() {
    echo -e "${BLUE}ℹ ${1}${NC}"
}

print_success() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

print_error() {
    echo -e "${RED}✗ ${1}${NC}"
}

prompt_yes_no() {
    local prompt="$1"
    local response
    while true; do
        read -p "$(echo -e ${BLUE}${prompt}${NC} [y/N]: )" response
        case "$response" in
            [yY][eE][sS]|[yY]) return 0 ;;
            [nN][oO]|[nN]|"") return 1 ;;
            *) echo "Please answer y or n" ;;
        esac
    done
}

INSTALL_USER="${SUDO_USER:-$(id -un)}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" 2>/dev/null | cut -d: -f6 || true)"
if [ -z "$INSTALL_HOME" ]; then
    INSTALL_HOME="$HOME"
fi

KLIPPER_DIR="$INSTALL_HOME/klipper"
CONFIG_DIR="$INSTALL_HOME/printer_data/config"
MOONRAKER_DIR="$INSTALL_HOME/moonraker"
MAINSAIL_DIR="$INSTALL_HOME/mainsail"
FLUIDD_DIR="$INSTALL_HOME/fluidd"
KLIPPERSCREEN_DIR="$INSTALL_HOME/KlipperScreen"

print_header "ACE Pro / KLIPPACE Clean Uninstaller"

echo "This script will remove ACE Pro files and symlinks from your system:"
echo " - Klipper extras (ace, virtual_pins.py, temperature_ace.py)"
echo " - Moonraker ace_status component"
echo " - Mainsail / Fluidd dashboard files"
echo " - KlipperScreen acepro panel & menu entries"
echo " - printer.cfg include lines"
echo ""

if ! prompt_yes_no "Do you want to proceed with uninstallation?"; then
    print_info "Uninstallation cancelled."
    exit 0
fi

# 1. Klipper Extras
print_header "Step 1: Removing Klipper Extras Symlinks"
for item in "ace" "virtual_pins.py" "temperature_ace.py"; do
    target="$KLIPPER_DIR/klippy/extras/$item"
    if [ -L "$target" ] || [ -e "$target" ]; then
        rm -rf "$target"
        print_success "Removed: $target"
    else
        print_info "Not found: $target (already clean)"
    fi
done

# 2. Moonraker Component
print_header "Step 2: Removing Moonraker Component"
mr_comp="$MOONRAKER_DIR/moonraker/components/ace_status.py"
if [ -L "$mr_comp" ] || [ -e "$mr_comp" ]; then
    rm -f "$mr_comp"
    print_success "Removed: $mr_comp"
else
    print_info "Not found: $mr_comp"
fi

# Remove [ace_status] from moonraker.conf
mr_conf="$CONFIG_DIR/moonraker.conf"
if [ -f "$mr_conf" ]; then
    if grep -q "\[ace_status\]" "$mr_conf"; then
        cp "$mr_conf" "${mr_conf}.backup_$(date +%Y%m%d_%H%M%S)"
        sed -i '/\[ace_status\]/,+3d' "$mr_conf"
        print_success "Cleaned [ace_status] from $mr_conf (backup created)"
    fi
fi

# 3. Mainsail Dashboard Files
print_header "Step 3: Removing Mainsail Dashboard Files"
if [ -d "$MAINSAIL_DIR" ]; then
    for f in ace.html ace-dashboard.js ace-dashboard.css ace-dashboard-config.js; do
        target="$MAINSAIL_DIR/$f"
        if [ -L "$target" ] || [ -e "$target" ]; then
            rm -f "$target"
            print_success "Removed: $target"
        fi
    done
fi

# 4. Fluidd Dashboard Files
print_header "Step 4: Removing Fluidd Dashboard Files"
if [ -d "$FLUIDD_DIR" ]; then
    for f in ace.html ace-dashboard.js ace-dashboard.css ace-dashboard-config.js; do
        target="$FLUIDD_DIR/$f"
        if [ -L "$target" ] || [ -e "$target" ]; then
            rm -f "$target"
            print_success "Removed: $target"
        fi
    done
fi

# 5. KlipperScreen Integration
print_header "Step 5: Removing KlipperScreen Panel"
ks_panel="$KLIPPERSCREEN_DIR/panels/acepro.py"
if [ -L "$ks_panel" ] || [ -e "$ks_panel" ]; then
    rm -f "$ks_panel"
    print_success "Removed: $ks_panel"
fi

ks_conf="$CONFIG_DIR/KlipperScreen.conf"
if [ -f "$ks_conf" ]; then
    if grep -q "acepro" "$ks_conf"; then
        cp "$ks_conf" "${ks_conf}.backup_$(date +%Y%m%d_%H%M%S)"
        sed -i '/\[menu __main acepro\]/,+3d' "$ks_conf"
        sed -i '/\[menu __print acepro\]/,+3d' "$ks_conf"
        print_success "Cleaned acepro menu from $ks_conf (backup created)"
    fi
fi

# 6. Configuration files and includes
print_header "Step 6: Cleaning printer.cfg & Config Directory"
PRINTER_CFG="$CONFIG_DIR/printer.cfg"
if [ -f "$PRINTER_CFG" ]; then
    if grep -qE '^\s*\[include\s+acepro\.cfg\]' "$PRINTER_CFG" || grep -qE '^\s*\[include\s+ace_voron24\.cfg\]' "$PRINTER_CFG"; then
        cp "$PRINTER_CFG" "${PRINTER_CFG}.backup_$(date +%Y%m%d_%H%M%S)"
        sed -i '/\[include acepro\.cfg\]/d' "$PRINTER_CFG"
        sed -i '/\[include ace_voron24\.cfg\]/d' "$PRINTER_CFG"
        print_success "Removed ACE includes from $PRINTER_CFG (backup created)"
    fi
fi

if prompt_yes_no "Remove old ACE configuration files from $CONFIG_DIR?"; then
    for cfg in "acepro.cfg" "acepro_macros.cfg" "acepro_setting.cfg" "acepro_printer_macros.cfg" "printer_macros_generic.cfg"; do
        target="$CONFIG_DIR/$cfg"
        if [ -f "$target" ] || [ -L "$target" ]; then
            rm -f "$target"
            print_success "Removed: $target"
        fi
    done
fi

# 7. Service Restarts
print_header "Step 7: Restarting Services"
if prompt_yes_no "Restart Klipper and Moonraker now?"; then
    sudo systemctl restart klipper 2>/dev/null && print_success "Restarted Klipper"
    sudo systemctl restart moonraker 2>/dev/null && print_success "Restarted Moonraker"
    if [ -d "$KLIPPERSCREEN_DIR" ]; then
        sudo systemctl restart KlipperScreen 2>/dev/null && print_success "Restarted KlipperScreen"
    fi
fi

echo ""
print_success "Uninstallation complete!"
print_info "If you have an old repository directory at ~/acepro-any-klipper, you can remove it with:"
echo "  rm -rf ~/acepro-any-klipper"
echo ""
