#!/bin/bash

# =============================================================================
# KLIPPACE / ACE Pro - Clean Uninstaller Script
# =============================================================================
# Safely removes KLIPPACE / ACE Pro extensions, dashboard files, Moonraker
# components and update manager, KlipperScreen panels, and configuration files.
#
# Compatible with: Raspberry Pi OS, Debian, Ubuntu, macOS
# Usage: ./uninstaller.sh [OPTIONS]
# =============================================================================

set -u

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Resolve installation user/home for defaults (works when run via sudo)
INSTALL_USER="${SUDO_USER:-$(id -un)}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" 2>/dev/null | cut -d: -f6 || true)"
if [ -z "$INSTALL_HOME" ]; then
    INSTALL_HOME="$HOME"
fi

FLAG_ASSUME_YES=0

# ============================================================================
# Helper Functions
# ============================================================================

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

# Yes/No prompt (respects --yes flag)
prompt_yes_no() {
    local prompt="$1"
    if [ "${FLAG_ASSUME_YES:-0}" -eq 1 ]; then
        echo -e "${BLUE}${prompt}${NC} [y/N]: y (auto)"
        return 0
    fi
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

# Prompt for input with default (respects --yes flag)
prompt_input() {
    local prompt="$1"
    local default="$2"
    local response=""
    if [ "${FLAG_ASSUME_YES:-0}" -eq 1 ]; then
        echo "$default"
        return 0
    fi
    read -p "$(echo -e ${BLUE}${prompt}${NC} [${default}]: )" response
    echo "${response:-$default}"
}

# Create backup with timestamp
backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        local timestamp
        timestamp=$(date +"%Y%m%d_%H%M%S")
        local backup="${file}.backup_${timestamp}"
        cp "$file" "$backup"
        print_success "Backed up: $file → $backup"
        return 0
    fi
    return 1
}

# ============================================================================
# Main Script
# ============================================================================

main() {
    local klipper_dir_override=""
    local config_dir_override=""
    local moonraker_dir_override=""
    local mainsail_dir_override=""
    local fluidd_dir_override=""
    local klipperscreen_dir_override=""

    # Parse CLI options
    while [ $# -gt 0 ]; do
        case "$1" in
            --klipper-dir)
                klipper_dir_override="$2"
                shift 2
                ;;
            --config-dir)
                config_dir_override="$2"
                shift 2
                ;;
            --moonraker-dir)
                moonraker_dir_override="$2"
                shift 2
                ;;
            --mainsail-dir)
                mainsail_dir_override="$2"
                shift 2
                ;;
            --fluidd-dir)
                fluidd_dir_override="$2"
                shift 2
                ;;
            --klipperscreen-dir)
                klipperscreen_dir_override="$2"
                shift 2
                ;;
            -y|--yes)
                FLAG_ASSUME_YES=1
                shift
                ;;
            -h|--help)
                echo "Usage: ./uninstaller.sh [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --klipper-dir <dir>       Path to Klipper installation directory"
                echo "  --config-dir <dir>        Path to Klipper config directory (e.g. ~/printer_data/config)"
                echo "  --moonraker-dir <dir>     Path to Moonraker directory"
                echo "  --mainsail-dir <dir>      Path to Mainsail directory"
                echo "  --fluidd-dir <dir>        Path to Fluidd directory"
                echo "  --klipperscreen-dir <dir> Path to KlipperScreen directory"
                echo "  -y, --yes                 Non-interactive mode (assume yes to prompts)"
                echo "  -h, --help                Show this help message"
                exit 0
                ;;
            *)
                print_warning "Unknown option: $1"
                shift
                ;;
        esac
    done

    print_header "KLIPPACE / ACE Pro Clean Uninstaller"

    # Resolve directories
    KLIPPER_DIR="${klipper_dir_override:-$INSTALL_HOME/klipper}"
    CONFIG_DIR="${config_dir_override:-$INSTALL_HOME/printer_data/config}"
    MOONRAKER_DIR="${moonraker_dir_override:-$INSTALL_HOME/moonraker}"
    MAINSAIL_DIR="${mainsail_dir_override:-$INSTALL_HOME/mainsail}"
    FLUIDD_DIR="${fluidd_dir_override:-$INSTALL_HOME/fluidd}"
    KLIPPERSCREEN_DIR="${klipperscreen_dir_override:-$INSTALL_HOME/KlipperScreen}"

    echo "This script will safely remove KLIPPACE components:"
    echo "  - Klipper extras symlinks (ace, virtual_pins.py, temperature_ace.py)"
    echo "  - Moonraker component (ace_status.py) & [ace_status] / [update_manager KLIPPACE] configs"
    echo "  - Mainsail & Fluidd dashboard files (ace.html, scripts, styles, favicon.svg)"
    echo "  - KlipperScreen panel (acepro.py) & menu entries in KlipperScreen.conf"
    echo "  - printer.cfg includes ([include ace_voron24.cfg], [include acepro.cfg], [include blobifier.cfg])"
    echo "  - (Optional) Voron 2.4 and Generic KLIPPACE configuration files in $CONFIG_DIR"
    echo ""

    if ! prompt_yes_no "Do you want to proceed with uninstallation?"; then
        print_info "Uninstallation cancelled."
        exit 0
    fi

    # ========================================================================
    # Step 1: Klipper Extras Symlinks
    # ========================================================================
    print_header "Step 1: Removing Klipper Extras Symlinks"
    for item in "ace" "virtual_pins.py" "temperature_ace.py"; do
        local target="$KLIPPER_DIR/klippy/extras/$item"
        if [ -L "$target" ] || [ -e "$target" ]; then
            rm -rf "$target"
            print_success "Removed: $target"
        else
            print_info "Not found: $target (already clean)"
        fi
    done

    # ========================================================================
    # Step 2: Moonraker Component & Configuration
    # ========================================================================
    print_header "Step 2: Removing Moonraker Component & Configuration"
    local mr_comp="$MOONRAKER_DIR/moonraker/components/ace_status.py"
    if [ -L "$mr_comp" ] || [ -e "$mr_comp" ]; then
        rm -f "$mr_comp"
        print_success "Removed: $mr_comp"
    else
        print_info "Not found: $mr_comp (already clean)"
    fi

    # Clean moonraker.conf
    local mr_conf="$CONFIG_DIR/moonraker.conf"
    if [ -f "$mr_conf" ]; then
        if grep -qiE '\[(ace_status|update_manager[[:space:]]+KLIPPACE)\]' "$mr_conf"; then
            backup_file "$mr_conf"
            local tmpfile
            tmpfile=$(mktemp)
            awk '
                BEGIN { in_section = 0 }
                /^#[[:space:]]*(ACE status extension|KLIPPACE update manager)/ { next }
                /^\[[[:space:]]*(ace_status|update_manager[[:space:]]+KLIPPACE)[[:space:]]*\]/ { in_section = 1; next }
                /^\[/ { in_section = 0 }
                !in_section { print }
            ' "$mr_conf" > "$tmpfile" && mv "$tmpfile" "$mr_conf"
            print_success "Cleaned [ace_status] and [update_manager KLIPPACE] from $mr_conf"
        else
            print_info "moonraker.conf does not contain KLIPPACE sections"
        fi
    fi

    # ========================================================================
    # Step 3: Mainsail Dashboard Files
    # ========================================================================
    print_header "Step 3: Removing Mainsail Dashboard Files"
    if [ -d "$MAINSAIL_DIR" ]; then
        for f in ace.html ace-dashboard.js ace-dashboard.css ace-dashboard-config.js favicon.svg; do
            local target="$MAINSAIL_DIR/$f"
            if [ -L "$target" ] || [ -e "$target" ]; then
                rm -f "$target"
                print_success "Removed: $target"
            fi
        done
    else
        print_info "Mainsail directory not found: $MAINSAIL_DIR"
    fi

    # ========================================================================
    # Step 4: Fluidd Dashboard Files
    # ========================================================================
    print_header "Step 4: Removing Fluidd Dashboard Files"
    if [ -d "$FLUIDD_DIR" ]; then
        for f in ace.html ace-dashboard.js ace-dashboard.css ace-dashboard-config.js favicon.svg; do
            local target="$FLUIDD_DIR/$f"
            if [ -L "$target" ] || [ -e "$target" ]; then
                rm -f "$target"
                print_success "Removed: $target"
            fi
        done
    else
        print_info "Fluidd directory not found: $FLUIDD_DIR"
    fi

    # ========================================================================
    # Step 5: KlipperScreen Integration
    # ========================================================================
    print_header "Step 5: Removing KlipperScreen Integration"
    local ks_panel="$KLIPPERSCREEN_DIR/panels/acepro.py"
    if [ -L "$ks_panel" ] || [ -e "$ks_panel" ]; then
        rm -f "$ks_panel"
        print_success "Removed: $ks_panel"
    else
        print_info "Not found: $ks_panel"
    fi

    local ks_conf="$CONFIG_DIR/KlipperScreen.conf"
    if [ -f "$ks_conf" ]; then
        if grep -qiE '\[menu[[:space:]]+__(main|print)[[:space:]]+acepro\]' "$ks_conf"; then
            backup_file "$ks_conf"
            local tmpfile
            tmpfile=$(mktemp)
            awk '
                BEGIN { in_section = 0 }
                /^\[[[:space:]]*menu[[:space:]]+__(main|print)[[:space:]]+acepro[[:space:]]*\]/ { in_section = 1; next }
                /^(\[|#~#)/ { in_section = 0 }
                !in_section { print }
            ' "$ks_conf" > "$tmpfile" && mv "$tmpfile" "$ks_conf"
            print_success "Cleaned acepro menus from $ks_conf"
        else
            print_info "KlipperScreen.conf does not contain acepro menu entries"
        fi
    fi

    # Check for applied KlipperScreen patch
    local ks_patch="$SCRIPT_DIR/patches/ace_global_subscription.patch"
    if [ -d "$KLIPPERSCREEN_DIR" ] && [ -f "$ks_patch" ]; then
        if patch -d "$KLIPPERSCREEN_DIR" -R -p1 --forward --dry-run < "$ks_patch" >/dev/null 2>&1; then
            if prompt_yes_no "Revert KlipperScreen subscription patch?"; then
                if patch -d "$KLIPPERSCREEN_DIR" -R -p1 --forward < "$ks_patch"; then
                    print_success "Reverted KlipperScreen subscription patch"
                else
                    print_warning "Failed to revert KlipperScreen patch"
                fi
            fi
        fi
    fi

    # ========================================================================
    # Step 6: Cleaning printer.cfg & Config Directory
    # ========================================================================
    print_header "Step 6: Cleaning printer.cfg & Config Directory"
    local printer_cfg="$CONFIG_DIR/printer.cfg"
    if [ -f "$printer_cfg" ]; then
        if grep -qE '^[[:space:]]*\[include[[:space:]]+(acepro|ace_voron24|blobifier)\.cfg\]' "$printer_cfg"; then
            backup_file "$printer_cfg"
            local tmpfile
            tmpfile=$(mktemp)
            awk '!/^[[:space:]]*\[include[[:space:]]+(acepro|ace_voron24|blobifier)\.cfg\]/' "$printer_cfg" > "$tmpfile" && mv "$tmpfile" "$printer_cfg"
            print_success "Removed KLIPPACE / Blobifier includes from $printer_cfg"
        else
            print_info "printer.cfg does not contain KLIPPACE include lines"
        fi
    fi

    # Detect existing KLIPPACE config files
    local candidate_configs=(
        "ace_voron24.cfg"
        "ace_voron24_vars.cfg"
        "ace_voron24_hardware.cfg"
        "ace_voron24_setting.cfg"
        "ace_voron24_macros.cfg"
        "blobifier.cfg"
        "blobifier_hw.cfg"
        "acepro.cfg"
        "acepro_macros.cfg"
        "acepro_setting.cfg"
        "acepro_printer_macros.cfg"
        "printer_macros_generic.cfg"
        "spoolman_logic.cfg"
    )

    local found_configs=()
    for cfg in "${candidate_configs[@]}"; do
        if [ -f "$CONFIG_DIR/$cfg" ] || [ -L "$CONFIG_DIR/$cfg" ]; then
            found_configs+=("$cfg")
        fi
    done

    if [ ${#found_configs[@]} -gt 0 ]; then
        echo ""
        print_info "Found the following KLIPPACE configuration files in $CONFIG_DIR:"
        for f in "${found_configs[@]}"; do
            echo "  - $f"
        done
        echo ""
        if prompt_yes_no "Remove these KLIPPACE configuration files from $CONFIG_DIR?"; then
            for f in "${found_configs[@]}"; do
                local target="$CONFIG_DIR/$f"
                backup_file "$target"
                rm -f "$target"
                print_success "Removed: $target"
            done
        else
            print_info "Preserved configuration files in $CONFIG_DIR"
        fi
    fi

    # ========================================================================
    # Step 7: Restarting Services
    # ========================================================================
    print_header "Step 7: Service Restarts"
    if prompt_yes_no "Restart Klipper and Moonraker now?"; then
        if command -v systemctl >/dev/null 2>&1; then
            sudo systemctl restart klipper 2>/dev/null && print_success "Restarted Klipper" || print_warning "Could not restart Klipper"
            sudo systemctl restart moonraker 2>/dev/null && print_success "Restarted Moonraker" || print_warning "Could not restart Moonraker"
            if [ -d "$KLIPPERSCREEN_DIR" ]; then
                sudo systemctl restart KlipperScreen 2>/dev/null && print_success "Restarted KlipperScreen" || true
            fi
        elif command -v service >/dev/null 2>&1; then
            sudo service klipper restart 2>/dev/null && print_success "Restarted Klipper" || print_warning "Could not restart Klipper"
            sudo service moonraker restart 2>/dev/null && print_success "Restarted Moonraker" || print_warning "Could not restart Moonraker"
        else
            print_warning "systemctl/service not available; please restart services manually if needed."
        fi
    fi

    echo ""
    print_success "KLIPPACE uninstallation completed successfully!"
    print_info "If you have an old repository directory at ~/acepro-any-klipper, you can remove it with:"
    echo "  rm -rf ~/acepro-any-klipper"
    echo ""
}

if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi
