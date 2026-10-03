# KLIPPACE – Universal Klipper Extension for Anycubic ACE Pro

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Klipper](https://img.shields.io/badge/Klipper-required-green.svg)](https://www.klipper3d.org/)
[![Status](https://img.shields.io/badge/status-work--in--progress-orange.svg)](#)
[![AI Assisted](https://img.shields.io/badge/AI-assisted-blueviolet.svg)](#)

> [!WARNING]
> ### ⚠️ Work in Progress
> **KLIPPACE is very much an active work in progress!** Features, configuration schemas, and macros are subject to active development and frequent updates. Please test all hardware motions, cutter strokes, and feed distances carefully before running production prints. Feedback, bug reports, and contributions are welcome!

> [!NOTE]
> ### 🤖 AI Notice
> This project utilizes Artificial Intelligence (AI) tools to assist with development, code refactoring, and documentation. While configurations are tested and verified on physical hardware, always inspect macros, verify pin assignments, and test mechanical clearances before operating your printer unattended.

A powerful, universal Klipper extension that brings the **Anycubic ACE Pro** multi-material unit to **any** Klipper-based 3D printer — Voron 2.4, RatRig, Anycubic Kobra, Sovol, Ender, and custom CoreXY or bed-slinger machines.

KLIPPACE manages high-speed Bowden feeding, dual-sensor toolhead coordination, differential pressure feeding, filament tip cutting, Blobifier tray nozzle parking, purge management, nozzle scrubbing, endless spool failover, and Moonraker lane synchronization.

Supports **up to 3 ACE Pro units (12 tools)** chained together.

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [📦 Installation](#-installation)
- [⚙️ Printer Profiles & Configuration](#️-printer-profiles--configuration)
  - [Voron 2.4 (CoreXY) Profile](#voron-24-corexy-profile)
  - [Anycubic / Generic Profile](#anycubic--generic-profile)
- [🔌 Slicer Setup & OrcaSlicer Plugin](#-slicer-setup--orcaslicer-plugin)
  - [OrcaSlicer ACE Pro Sync Plugin](#orcaslicer-ace-pro-sync-plugin)
  - [Machine G-Code Setup](#machine-g-code-setup)
  - [Optimized Flush Volume Post-Processing Script](#optimized-flush-volume-post-processing-script)
- [🧪 Usage & Commands](#-usage--commands)
- [♻️ Endless Spool & Contextual Start Purge](#️-endless-spool--contextual-start-purge)
- [🔌 Connection Supervision](#-connection-supervision)
- [🖥️ Web Dashboard & KlipperScreen](#️-web-dashboard--klipperscreen)
- [🔧 Troubleshooting](#-troubleshooting)
- [🙏 Credits & License](#-credits--license)

---

## ✨ Features

### Core Multi-Material Engine
- **Universal Kinematics** – Seamlessly operates on CoreXY flying gantries (Voron 2.4), fixed gantry / bed-slingers (Kobra, Ender, Sovol), and dual-gantry setups.
- **Multi-ACE Chaining** – Supports 1 to 3 ACE Pro units (up to 12 filament slots).
- **Dual-Sensor Toolhead Coordination** – Coordinated entry and seating using both an upper entry sensor (`EBB:PD0`) and lower nozzle sensor (`EBB:PA15`).
- **Differential Forward Pressure Feeding** – Pushes from the ACE at differential speeds (`ace_entry_feeding_speed: 16` vs `extruder_feeding_speed: 8`) to overcome mechanical switch friction and seat firmly into extruder drive gears (e.g. WW BMG).
- **Splitter Auto-Park (Path A)** – Automatically rewinds 400mm on spool insertion (`spool_load_park_retract_length: 400`), safely parking the filament tip ~50mm before a passive 4-in-1 splitter so other slots can feed without collisions.
- **Coordinated Dual-Blob Toolchanging (Voron 2.4 Profile)**:
  - **Blob 1 (Load Feed Blob)** – As new filament enters the extruder, KLIPPACE coordinates an exponential Z-lift (`Z2.6 → Z12.6`) via `_ACE_LOAD_PURGE` with 100% part cooling during the ACE push to create a solid, clean vertical load blob instead of buckling.
  - **Blob 2 (Purge Blob)** – Pulsating extrusion via Blobifier v1.5 (`BLOBIFIER_PURGE`) flushes the transition color cleanly into the purge bucket.
  - **High-Velocity Cooling Freeze** – Blasts dual 24V part cooling fans at 100% power during a 5-second dwell (`pressure_release_time: 5000`), freezing the blob rock-solid so the servo tray retracts without squishing or stringing.
- **Continuous Zigzag Scrubbing with Y-Axis Jitter** – Advanced 40mm nozzle wipe across the Decontaminator brush (`X96–X136 Y360 Z3.0`) with sinusoidal Y-axis jitter ($\pm 4.0\text{mm}$, alternating between Y358.0 and Y360.0) every 5mm along X for complete, non-linear nozzle tip and flank cleaning.
- **Dual 24V Part Cooling Architecture** – Fully harnesses upgraded 24V blower fans via `[multi_pin dual_fan]` on `EBB:PD3` and `EBB:PA5` driven at 100% full power (`max_power: 1.0`).
- **Mechanical Gantry Cutting** – Integrated support for A4T Crossbow / gantry cutter pins (`CUT_TIP` at `X2 Y357`) with obstacle avoidance and post-cut retraction.
- **Blobifier Purge Bucket Detection** – Real-time switch/optical monitoring (`blobifier_bucket` on `PF4`) preventing print failure from purge waste overflow.
- **Smart Contextual Start Purge** – Remembers the residual filament in the hotend (`ace_last_loaded_tool`). Automatically calculates differential purge volumes at `PRINT_START` (standard 35mm when loading the same tool, heavy 85mm when purging out a different color/material).
- **Automatic 1:1 Tool-to-Gate Reset** – Automatically resets temporary tool-to-gate remappings back to 1:1 upon print completion or cancellation (`RESET_TOOL_MAPPING`).
- **Endless Spool Failover** – Automatically rolls over to a matching spool upon runout (`exact`, `material`, or `next` ready).
- **Moonraker & OrcaSlicer Lane Sync** – Real-time lane data synchronization for filament type, color, and spool parameters.
- **Universal OrcaSlicer ACE Pro Plugin** – One-click filament, color, temperature, and RFID synchronization into universal presets (`compatible_printers: []`), featuring dynamic printer network resolution across macOS, Linux, and Windows.
- **Fluidd / Mainsail Auto-Match Tool Mapper** – Streamlined 1-click slot selector and automated toolhead-to-gate assignment directly in the Web UI.
- **Integrated Chamber Dryer Control** – Regulates and monitors heating in the ACE Pro drying chamber (`[temperature_ace]`).

---

## 📦 Installation

### Prerequisites
- Klipper installed and running on Python 3.9+.
- One or more Anycubic ACE Pro units connected via USB.
- Moonraker and Mainsail or Fluidd installed.

### Interactive Setup & Installer

Clone the repository and run the setup script:

```bash
cd ~
git clone -b dev https://github.com/Yheffe/KLIPPACE.git
cd KLIPPACE
chmod +x installer.sh uninstaller.sh
./installer.sh
```

**Non-Interactive / Scripted Usage:**
```bash
# Voron 2.4 Profile
./installer.sh --profile voron -y

# Generic / Bed-Slinger Profile
./installer.sh --profile generic -y
```

The installer will:
1. Detect your Klipper directory and symlink the core Python modules into `klippy/extras/`.
2. Symlink `virtual_pins.py` and the `temperature_ace.py` sensor.
3. Prompt you to select your printer profile:
   - **`1) Voron 2.4`**: Copies the modular `config/voron24/` suite (including Blobifier v1.5) into `~/printer_data/config/` and adds `[include ace_voron24.cfg]` and `[include blobifier.cfg]` to `printer.cfg`.
   - **`2) Anycubic Kobra`** or **`3) Generic`**: Copies `acepro.cfg`, `acepro_setting.cfg`, `acepro_macros.cfg`, and optional `spoolman_logic.cfg`.
4. Configure the **Moonraker Update Manager** (`[update_manager KLIPPACE]`) in `moonraker.conf` for one-click Web UI updates.
5. Optionally install the **ACE Status Moonraker Component** and Web Dashboard for Mainsail / Fluidd.
6. Optionally link the **KlipperScreen** panel and menu entries.

Restart Klipper when the installer completes:

```bash
sudo service klipper restart
```

> [!NOTE]
> After updating or installing the web dashboard, perform a hard refresh in your browser (`Ctrl + F5` on Windows/Linux, `Cmd + Shift + R` on macOS).

### Clean Uninstallation

If you ever wish to remove KLIPPACE:

```bash
./uninstaller.sh
```

The uninstaller creates timestamped backups of all modified files, cleanly strips include lines and Moonraker sections, removes web dashboard assets, and prompts before deleting configuration files.

---

## ⚙️ Printer Profiles & Configuration

### Voron 2.4 (CoreXY) Profile

Calibrated for a Voron 2.4 (350mm) running an A4T toolhead with multi-material Bowden feeding:
- **Toolhead Board**: BTT EBB36 GEN2 (STM32G0B1, CAN/USB)
- **Part Cooling**: Dual 24V blower fans via `[multi_pin dual_fan]` (`EBB:PD3` and `EBB:PA5`) at `max_power: 1.0`
- **Extruder**: WW BMG (WristWatch BMG, 50:10 gear ratio)
- **Sensors**: Dual-sensor toolhead entry switch (`^EBB:PD0`) and nozzle seated switch (`^EBB:PA15`)
- **Filament Cutter**: Crossbow Cutter (gantry pin at `X2 Y357`, approach `X2 Y340`)
- **Blobifier Purge & Park**: Servo tray at `X5 Y360` (Tray top: `Z2.4`, Purge height: `Z2.6`)
- **Nozzle Scrubbing**: Decontaminator brush (`X96–X136 Y360 Z3.0`) with $\pm 4.0\text{mm}$ Y-axis zigzag jitter

The Voron profile is fully modular and lives in `config/voron24/`:

| File | Purpose |
| :--- | :--- |
| [`ace_voron24.cfg`](config/voron24/ace_voron24.cfg) | Master include file. Place `[include ace_voron24.cfg]` at the top of your `printer.cfg`. |
| [`ace_voron24_vars.cfg`](config/voron24/ace_voron24_vars.cfg) | Physical coordinates for Crossbow Cutter (`X2 Y357`), Blobifier Tray (`X5 Y360 Z2.6`), and Brush (`X96-136 Y360 Z3.0`). |
| [`ace_voron24_hardware.cfg`](config/voron24/ace_voron24_hardware.cfg) | Pin definitions for Entry Sensor (`^EBB:PD0`) and Nozzle Sensor (`^EBB:PA15`). |
| [`ace_voron24_setting.cfg`](config/voron24/ace_voron24_setting.cfg) | Calibrated feed lengths (1050mm total, 400mm auto-park, 16/8 mm/s differential entry). |
| [`ace_voron24_macros.cfg`](config/voron24/ace_voron24_macros.cfg) | Voron-safe macros: `CUT_TIP`, `_ACE_LOAD_PURGE`, `BLOBIFIER_PARK`, `CLEAN_NOZZLE`, `RESUME_NOZZLE_WIPE_SEQUENCE`. |
| [`blobifier.cfg`](config/voron24/blobifier.cfg) | Official Blobifier v1.5 pulsating purge routine, bucket ejection, and shake-off sequence. |
| [`blobifier_hw.cfg`](config/voron24/blobifier_hw.cfg) | Hardware pin definitions for Blobifier servo (`PE9` on Octopus Max EZ). |

> [!TIP]
> **Complete Voron Setup Guide**: Read [VORON24_SETUP.md](VORON24_SETUP.md) for full physical tube routing diagrams, step-by-step sensor calibration, and wiring details.

### Anycubic / Generic Profile

For standard bed-slingers and custom printers with servo-actuated purge baskets:

| File | Purpose |
| :--- | :--- |
| `acepro.cfg` | Master configuration include. |
| `acepro_setting.cfg` | Driver parameters, tube lengths, feed speeds, and sensor assignments. |
| `acepro_macros.cfg` | Purge, wipe, servo poop basket angles, and pause/resume logic. |
| `acepro_printer_macros.cfg` | Generic `MY_START_PRINT` and printer helper hooks. |
| `spoolman_logic.cfg` | (Optional) Spoolman RFID tag mapping and slot tracking integration. |

---

## 🔌 Slicer Setup & OrcaSlicer Plugin

KLIPPACE provides native integration with **OrcaSlicer** via a dedicated plugin, optimized print macros, and post-processing flush conversion.

### OrcaSlicer ACE Pro Sync Plugin

The KLIPPACE ACE Pro Sync plugin enables one-click synchronization of your ACE Pro's physical spool colors, materials, nozzle/bed temperatures, and RFID tags directly into OrcaSlicer user filament profiles.

#### Key Capabilities:
- **Dynamic Printer Network Resolution**: Automatically extracts target printer network parameters (`print_host`, `printhost_port`, `printhost_apikey`) directly from the active OrcaSlicer printer profile (or `OrcaSlicer.conf`). Works seamlessly without hardcoded IP addresses.
- **Universal Filament Presets**: Generates presets with `"compatible_printers": []`, ensuring synced ACE Pro spools are instantly visible and selectable across all printer models, bed sizes, and nozzle diameters.
- **Cross-Platform Compatibility**: Works across macOS (`~/Library/Application Support/OrcaSlicer`), Windows (`%APPDATA%/OrcaSlicer`), and Linux (`~/.config/OrcaSlicer`).
- **Interactive Embedded Web Page UI**: An embedded dark-mode "ACE Pro" tab directly inside OrcaSlicer displaying live slot swatches, materials, target temperatures, spool metadata and the preset name each slot will sync under, with a one-click **"Sync Filaments to Slicer"** action.
- **Custom Preset Names**: A slot given a name on the printer (the slot editor's *Preset name* field, or `ACE_SET_SLOT ... FILAMENT_SETTINGS_ID="..."`) is synced into Orca under that name instead of the generated `ACE T<n> - <material> <colour>` label. Renaming a spool replaces the previous preset rather than leaving an orphan.
- **Script Capability & Standalone CLI**: Trigger sync directly via OrcaSlicer's **File > Plugins / Run** or execute via terminal:
  ```bash
  python3 scripts/sync_ace_to_orca.py          # summary
  python3 scripts/sync_ace_to_orca.py --json   # full result payload
  python3 scripts/sync_ace_to_orca.py --host 192.168.1.168
  ```
  `scripts/sync_ace_to_orca.py` is a thin launcher that imports the plugin, so the sync logic exists in exactly one place: `plugins/orcaslicer/klippace_ace_sync.py`.
- **Smart Non-RFID Mapping**: Automatically maps generic or manual spools cleanly to standard PLA and default temperatures (210°C / 60°C) so all 4 slots are consistently synchronized.

#### Why custom preset names are tracked

A generated `ACE T<n> - ...` filename identifies its slot, so stale presets can be found by prefix. A custom name carries no such marker. The plugin therefore records the files it wrote in `klippace_ace_sync_manifest.json` (in the OrcaSlicer application directory) and uses that record to clean up on rename or removal. Legacy `ACE T<n> - *` presets are still swept by prefix, so upgrading needs no manual cleanup.

#### Plugin Installation:

1. **Locate your OrcaSlicer plugin directory**:
   - **macOS**: `~/Library/Application Support/OrcaSlicer/orca_plugins/klippace_ace_sync/`
   - **Linux**: `~/.config/OrcaSlicer/orca_plugins/klippace_ace_sync/`
   - **Windows**: `%APPDATA%\OrcaSlicer\orca_plugins\klippace_ace_sync\`

2. **Deploy the plugin files**:
   ```bash
   # macOS Example:
   mkdir -p ~/Library/Application\ Support/OrcaSlicer/orca_plugins/klippace_ace_sync
   cp plugins/orcaslicer/klippace_ace_sync.py ~/Library/Application\ Support/OrcaSlicer/orca_plugins/klippace_ace_sync/
   cp plugins/orcaslicer/.install_state.json ~/Library/Application\ Support/OrcaSlicer/orca_plugins/klippace_ace_sync/
   ```

3. **Restart OrcaSlicer**: The "ACE Pro" tab will appear under Pages, and "Sync ACE Pro Filaments" will be registered under Script capabilities.

---

### Machine G-Code Setup

#### 1. Machine Start G-Code
In your OrcaSlicer **Printer Settings -> Custom G-code -> Machine start G-code**:

```gcode
PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer] INITIAL_TOOL=[initial_tool] DRYER_MATERIAL=[filament_type]
```

`PRINT_START` will home, heat the bed, execute Quad Gantry Leveling (QGL), calibrate bed mesh, park the nozzle over the Blobifier tray (`X5 Y360 Z2.6`), check the last loaded tool against the initial tool to determine whether standard (35mm) or heavy transition (85mm) purge is required, heat the hotend to initial extrusion temperature, load the designated initial tool (`ACE_ON_PRINT_START`) while forming the initial load feed blob, scrub the nozzle across the Decontaminator brush, optionally start the ACE Pro dryer (`DRYER_START`), and execute an adaptive first-layer line purge (`LINE_PURGE`) next to the sliced object before beginning the first layer.

#### 2. Filament Change G-Code
In OrcaSlicer **Printer Settings -> Multimaterial -> Change filament G-code**:

```gcode
T[next_extruder]
```

#### 3. Layer Change G-Code
In OrcaSlicer **Printer Settings -> Custom G-code -> Layer change G-code**:

```gcode
;AFTER_LAYER_CHANGE
SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num + 1}
M117 Layer {layer_num + 1}/[total_layer_count] : {filament_settings_id[0]}
```

---

### Optimized Flush Volume Post-Processing Script
Under OrcaSlicer **Print Settings -> Others -> Post-processing scripts**:

```
/usr/bin/python3 /home/pi/KLIPPACE/slicer/orca_flush_to_purgelength.py
```

This script translates OrcaSlicer's flush matrix directly into optimal `PURGELENGTH` values for each tool change.

---

## 🧪 Usage & Commands

Standard Klipper tool change commands (`T0`, `T1`, `T2`, `T3`, ...) are fully supported. Additional commands provide manual diagnostic and maintenance control:

| Command | Description |
| :--- | :--- |
| `T<tool>` | Initiate a complete tool change to tool number `<tool>` (0–11). |
| `RESET_TOOL_MAPPING` | Reset all temporary tool-to-gate remappings back to 1:1. Automatically called on `PRINT_END` and `CANCEL_PRINT`. |
| `SET_GATE_MAP TOOL=<t> GATE=<g>` | Manually remap a logical slicer tool `<t>` to a physical ACE gate `<g>`. |
| `ACE_STATUS` / `ACE_GET_STATUS` | Display comprehensive ACE hardware state, temperatures, and slot status. |
| `ACE_CHANGE_TOOL TOOL=<n>` | Change to tool `<n>`. Set `TOOL=-1` to perform a complete unload back to the ACE. |
| `PARK_SLOT SLOT=<n>` | Manually rewind slot `<n>` by 400mm back before the 4-in-1 splitter. |
| `PARK_ALL_SLOTS` | Rewind all loaded slots by 400mm back before the splitter. |
| `BLOBIFIER_PARK` / `PARK` | Park nozzle over the extended Blobifier tray (`X5 Y360 Z2.6`). |
| `_ACE_LOAD_PURGE` | Coordinated exponential Z-lift (`Z2.6 → Z12.6`) and 100% fan during initial load feed to form load blob. |
| `BLOBIFIER_PURGE` | Execute Blobifier v1.5 pulsating purge blob, 5-second cooling freeze, and strip-off ejection. |
| `BLOBIFIER_SERVO POS=out\|in` | Manually command the Blobifier servo tray extended (`out`) or retracted (`in`). |
| `RESUME_NOZZLE_WIPE_SEQUENCE` | Execute continuous 40mm X-axis scrub across brush with alternating $\pm 4.0\text{mm}$ Y-axis jitter. |
| `LINE_PURGE` / `ADAPTIVE_PURGE` | Adaptive first-layer bed line purge adjacent to object perimeter (used in `PRINT_START`). |
| `LIFT_FROM_STOPPER` | Lift nozzle off the Blobifier tray to safe clearance height (`Z15`). |
| `CUT_TIP` | Execute filament cut stroke against gantry cutter pin (`X2 Y357`). |
| `CLEAN_NOZZLE` | Perform multi-pass nozzle scrub across the brass/silicone brush. |
| `DRYER_START` | Start ACE Pro dryer with temp and duration (e.g. `TEMP=50 DURATION=240` or `MATERIAL=PLA`). |
| `DRYER_STOP` | Stop the ACE Pro dryer. |
| `ACE_FEED T=<tool> LENGTH=<mm>` | Manually feed filament forward from a specific slot. |
| `ACE_RETRACT T=<tool> LENGTH=<mm>` | Manually retract filament from a specific slot. |
| `ACE_DEBUG_SENSORS` | Query current real-time state of all configured filament switches. |
| `ACE_INVENTORY` | Scan and refresh RFID and manual filament inventory across all ACE slots. |
| `UPDATE_ALL_MCUS` | Compile and flash firmware to all MCUs (Octopus Max EZ & EBB36) with safety checks. |

---

## ♻️ Endless Spool & Contextual Start Purge

### Endless Spool

When a filament spool runs empty during a print, Endless Spool automatically detects runout, unloads the empty spool, searches for a compatible replacement, and loads it to resume printing without human intervention.

#### Match Modes

Configure the matching logic via Mainsail/Fluidd or using `ACE_SET_ENDLESS_SPOOL_MODE`:
- **`exact`** (default) – Requires identical material **and** identical RGB color.
- **`material`** – Requires identical material type (e.g. PLA to PLA), ignoring color differences.
- **`next`** – Selects the next available ready spool in numerical order regardless of type or color.

```gcode
ACE_ENABLE_ENDLESS_SPOOL
ACE_DISABLE_ENDLESS_SPOOL
ACE_SET_ENDLESS_SPOOL_MODE MODE=exact
ACE_GET_ENDLESS_SPOOL_MODE
```

### 🧠 Smart Contextual Start Purge

KLIPPACE tracks the tool and material currently seated in the hotend using the persistent variable `ace_last_loaded_tool`.

During `PRINT_START`:
- **Same Tool Seated**: If the initial print tool matches the residual tool already in the nozzle, KLIPPACE skips heavy purging and applies a standard refresh purge (`purge_same_tool: 35.0` mm).
- **Tool / Color Transition**: If the initial tool differs from the last printed tool (e.g. transitioning from Black to White or changing material types), KLIPPACE automatically commands a heavy transition purge (`purge_different_tool: 85.0` mm) to flush out the old slug before forming the load blob.
- **Slicer Override**: If OrcaSlicer passes an explicit `PURGE_LENGTH` parameter in `PRINT_START`, that volume is honored directly.

---

## 🔌 Connection Supervision

KLIPPACE actively monitors USB communication health with the ACE Pro hardware. If unstable communication is detected (e.g. 6+ reconnects within a 3-minute window), it automatically pauses the print to prevent mid-print extrusion failures.

To toggle or adjust supervision in your settings:

```ini
[ace]
ace_connection_supervision: True
```

Run `ACE_GET_CONNECTION_STATUS` in the console to inspect per-instance link statistics.

---

## 🖥️ Web Dashboard & KlipperScreen

### Web Dashboard (Mainsail & Fluidd)
The included `acepro-mmu-dashboard` embeds interactive multi-material controls directly into Mainsail and Fluidd:
- **Real-Time Slot Indicators**: Slot status, active tool indicators, and temperatures.
- **1-Click Slot Selector**: Click any slot to immediately load, unload, or inspect that spool.
- **Auto-Match Tool Mapper**: Automatically correlates g-code tool numbers with physical ACE gates based on color hex and material type.
- **Blobifier Bucket Monitoring**: Displays real-time status of the optional bucket sensor (`blobifier_bucket` on `PF4`), warning or pausing before waste bucket overflow causes carriage collisions.
- **Spool Management**: Spool material and color assignment with Spoolman integration.
- **Dryer Control**: Chamber temperature monitoring, target adjustment, and timer countdown.

### Moonraker Update Manager Integration

To enable one-click updates for KLIPPACE directly from the Mainsail or Fluidd web interface, add the following to your `moonraker.conf`:

```ini
[update_manager KLIPPACE]
type: git_repo
path: ~/KLIPPACE
origin: https://github.com/Yheffe/KLIPPACE.git
primary_branch: dev
managed_services: klipper moonraker
```

*(Note: `installer.sh` will automatically offer to configure this for you during setup.)*

### KlipperScreen Panel
A native touchscreen panel is available for KlipperScreen:
- Symlink the panel:
  ```bash
  ln -sf ~/KLIPPACE/KlipperScreen/acepro.py ~/KlipperScreen/panels/acepro.py
  ```
- Add the menu definition to `main_menu.conf`:
  ```ini
  [menu __main acepro]
  name: ACE Pro
  icon: settings
  panel: acepro

  [menu __print acepro]
  name: ACE Pro
  icon: settings
  panel: acepro
  ```
- Restart KlipperScreen: `sudo systemctl restart KlipperScreen`.

---

## 🔧 Troubleshooting

### Toolhead Entry Sensor Doesn't Detect Filament
- Verify sensor state with:
  ```gcode
  QUERY_FILAMENT_SENSOR SENSOR=filament_entry_sensor
  ```
- If the sensor reports `detected` when empty and `not detected` when inserted, invert the switch pin in `ace_voron24_hardware.cfg`:
  ```ini
  switch_pin: ^!EBB:PD0
  ```

### ACE Stalls or Grinds at the Extruder Entry
- If the filament tip hits resistance entering the extruder drive gears, ensure differential forward pressure is enabled in `ace_voron24_setting.cfg`:
  ```ini
  ace_entry_feeding_speed: 16
  extruder_feeding_speed: 8
  ```
- The ACE feeding faster than the extruder builds forward Bowden tension that effortlessly pushes past the switch lever.

### Filament Hits Splitter on Multi-Spool Load
- Ensure `spool_load_park_retract_length: 400` is configured in `ace_voron24_setting.cfg`.
- After inserting a spool, KLIPPACE will automatically rewind the filament tip ~50mm before the 4-in-1 splitter. You can also run `PARK_ALL_SLOTS` at any time.

### Spool Does Not Rewind Tightly
- Lower `retract_speed` in your settings (e.g. from 50 mm/s to 35 mm/s) to allow the ACE motorized spool hub sufficient torque to rewind smoothly.

---

## 🙏 Credits & License

KLIPPACE builds upon and extends the groundbreaking work of the open-source 3D printing community:
- [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO)
- [szkrisz/ACEPROSV08](https://github.com/szkrisz/ACEPROSV08)
- [utkabobr/DuckACE](https://github.com/utkabobr/DuckACE)
- [agrloki/ValgACE](https://github.com/agrloki/ValgACE)

**License**: GNU General Public License v3.0 ([GPLv3](LICENSE))
