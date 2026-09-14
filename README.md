# KLIPPACE – Universal Klipper Extension for Anycubic ACE Pro

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Klipper](https://img.shields.io/badge/Klipper-required-green.svg)](https://www.klipper3d.org/)
[![Status](https://img.shields.io/badge/status-work--in--progress-orange.svg)](#)

> [!WARNING]
> ### ⚠️ Work in Progress
> **KLIPPACE is very much an active work in progress!** Features, configuration schemas, and macros are subject to active development and frequent updates. Please test all hardware motions, cutter strokes, and feed distances carefully before running production prints. Feedback, bug reports, and contributions are welcome!

A powerful, universal Klipper extension that brings the **Anycubic ACE Pro** multi-material unit to **any** Klipper-based 3D printer — Voron 2.4, RatRig, Anycubic Kobra, Sovol, Ender, and custom CoreXY or bed-slinger machines.

KLIPPACE manages high-speed Bowden feeding, dual-sensor toolhead coordination, differential pressure feeding, filament tip cutting, silicone stopper nozzle parking, purge management, nozzle scrubbing, endless spool failover, and Moonraker lane synchronization.

Supports **up to 3 ACE Pro units (12 tools)** chained together.

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [📦 Installation](#-installation)
- [⚙️ Printer Profiles & Configuration](#️-printer-profiles--configuration)
  - [Voron 2.4 (CoreXY) Profile](#voron-24-corexy-profile)
  - [Anycubic / Generic Profile](#anycubic--generic-profile)
- [🔌 Slicer Setup (OrcaSlicer)](#-slicer-setup-orcaslicer)
- [🧪 Usage & Commands](#-usage--commands)
- [♻️ Endless Spool](#️-endless-spool)
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
- **Differential Forward Pressure Feeding** – Pushes from the ACE at differential speeds (`ace_entry_feeding_speed: 16` vs `extruder_feeding_speed: 8`) to overcome mechanical switch friction and seat firmly into extruder drive gears.
- **Splitter Auto-Park (Path A)** – Automatically rewinds 400mm on spool insertion (`spool_load_park_retract_length: 400`), safely parking the filament tip ~50mm before a passive 4-in-1 splitter so other slots can feed without collisions.
- **Silicone Stopper Park / Nozzle Seal** – Parks and rests the hot nozzle against a silicone stopper pad (`X90 Y350 Z3.5`) during tool swaps to eliminate oozing while the ACE switches spools.
- **Mechanical Gantry Cutting** – Integrated support for A4T Crossbow / gantry cutter pins (`CUT_TIP` at `X0 Y359`) with post-cut retraction.
- **Decontaminator Nozzle Scrubber** – Configurable multi-pass brush scrubbing (`CLEAN_NOZZLE` at `X108-X158 Y350 Z6.0`).
- **Endless Spool Failover** – Automatically rolls over to a matching spool upon runout (`exact`, `material`, or `next` ready).
- **Moonraker & OrcaSlicer Lane Sync** – Real-time lane data synchronization for filament type, color, and spool parameters.
- **Integrated Chamber Dryer Control** – Regulates and monitors heating in the ACE Pro drying chamber (`[temperature_ace]`).

---

## 📦 Installation

### Prerequisites
- Klipper installed and running on Python 3.9+.
- One or more Anycubic ACE Pro units connected via USB.
- Moonraker and Mainsail or Fluidd installed.

### Interactive One-Click Installer

Clone the repository and run the interactive setup script:

```bash
cd ~
git clone -b dev https://github.com/Yheffe/KLIPPACE.git
cd KLIPPACE
chmod +x installer.sh
./installer.sh
```

The installer will:
1. Detect your Klipper directory and symlink the core Python modules into `klippy/extras/`.
2. Symlink `virtual_pins.py` and the `temperature_ace.py` sensor.
3. Prompt you to select your printer profile:
   - **`1) Voron 2.4`**: Copies the modular `config/voron24/` suite into `~/printer_data/config/` and adds `[include ace_voron24.cfg]` to `printer.cfg`.
   - **`2) Anycubic Kobra`** or **`3) Generic`**: Copies `acepro.cfg`, `acepro_setting.cfg`, and `acepro_macros.cfg`.
4. Optionally install the **ACE Status Moonraker Component** and Web Dashboard for Mainsail / Fluidd.
5. Optionally link the **KlipperScreen** panel.

Restart Klipper when the installer completes:

```bash
sudo service klipper restart
```

> [!NOTE]
> After updating or installing the web dashboard, perform a hard refresh in your browser (`Ctrl + F5` on Windows/Linux, `Cmd + Shift + R` on macOS).

---

## ⚙️ Printer Profiles & Configuration

### Voron 2.4 (CoreXY) Profile

The Voron profile is fully modular and lives in `config/voron24/`:

| File | Purpose |
| :--- | :--- |
| [`ace_voron24.cfg`](config/voron24/ace_voron24.cfg) | Master include file. Place `[include ace_voron24.cfg]` at the top of your `printer.cfg`. |
| [`ace_voron24_vars.cfg`](config/voron24/ace_voron24_vars.cfg) | Physical coordinates for Cutter (`X0 Y359`), Stopper (`X90 Y350`), Purge (`X90 Y355`), and Brush (`X108-158 Y350`). |
| [`ace_voron24_hardware.cfg`](config/voron24/ace_voron24_hardware.cfg) | Pin definitions for Entry Sensor (`^EBB:PD0`) and Nozzle Sensor (`^EBB:PA15`). |
| [`ace_voron24_setting.cfg`](config/voron24/ace_voron24_setting.cfg) | Calibrated feed lengths (1050mm total, 400mm auto-park, 16/8 mm/s differential entry). |
| [`ace_voron24_macros.cfg`](config/voron24/ace_voron24_macros.cfg) | Voron-safe macros: `CUT_TIP`, `PARK_ON_STOPPER`, `LIFT_FROM_STOPPER`, `CLEAN_NOZZLE`, `ACE_ON_PRINT_START`. |

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

---

## 🔌 Slicer Setup (OrcaSlicer)

### 1. Machine Start G-Code
In your OrcaSlicer **Printer Settings -> Custom G-code -> Machine start G-code**:

```gcode
PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer] INITIAL_TOOL=[initial_tool]
```

`PRINT_START` will execute QGL, calibrate the bed mesh, heat the hotend, load the designated initial tool (`ACE_ON_PRINT_START`), and prime the nozzle before starting the print.

### 2. Filament Change G-Code
In OrcaSlicer **Printer Settings -> Multimaterial -> Change filament G-code**:

```gcode
T[next_extruder]
```

### 3. Layer Change G-Code
In OrcaSlicer **Printer Settings -> Custom G-code -> Layer change G-code**:

```gcode
;AFTER_LAYER_CHANGE
SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num + 1}
M117 Layer {layer_num + 1}/[total_layer_count] : {filament_settings_id[0]}
```

### 4. Optimized Flush Volume Post-Processing Script
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
| `ACE_STATUS` / `ACE_GET_STATUS` | Display comprehensive ACE hardware state, temperatures, and slot status. |
| `ACE_CHANGE_TOOL TOOL=<n>` | Change to tool `<n>`. Set `TOOL=-1` to perform a complete unload back to the ACE. |
| `PARK_SLOT SLOT=<n>` | Manually rewind slot `<n>` by 400mm back before the 4-in-1 splitter. |
| `PARK_ALL_SLOTS` | Rewind all loaded slots by 400mm back before the splitter. |
| `PARK_ON_STOPPER` | Park nozzle sealed against the silicone stopper pad (`X90 Y350 Z3.5`). |
| `LIFT_FROM_STOPPER` | Lift nozzle off the silicone stopper pad to safe clearance height (`Z15`). |
| `CUT_TIP` | Execute filament cut stroke against gantry cutter pin (`X0 Y359`). |
| `CLEAN_NOZZLE` | Perform multi-pass nozzle scrub across the brass/silicone brush. |
| `ACE_FEED T=<tool> LENGTH=<mm>` | Manually feed filament forward from a specific slot. |
| `ACE_RETRACT T=<tool> LENGTH=<mm>` | Manually retract filament from a specific slot. |
| `ACE_DEBUG_SENSORS` | Query current real-time state of all configured filament switches. |

---

## ♻️ Endless Spool

When a filament spool runs empty during a print, Endless Spool automatically detects runout, unloads the empty spool, searches for a compatible replacement, and loads it to resume printing without human intervention.

### Match Modes

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
- Real-time slot status, active tool indicators, and temperatures.
- Spool material and color assignment with Spoolman integration.
- Manual feed, retract, and park controls.
- Dryer temperature monitoring and timer controls.

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
