# Voron 2.4R2 Multi-Material Setup Guide (Anycubic ACE Pro + KLIPPACE)

This guide walks you through setting up and running the **Anycubic ACE Pro** on a **Voron 2.4R2 (350mm)** using KLIPPACE.

---

## 1. Physical Layout & Tube Routing

```
┌─────────────────────────────────────────────────────────┐
│                    ACE Pro Unit                         │
│               (Mounted on Top Panel)                    │
└──────────┬─────────────┬─────────────┬─────────────┬────┘
           │             │             │             │
        ~150mm        ~150mm        ~150mm        ~150mm  (PTFE Tubes)
           │             │             │             │
           └─────────────┼─────────────┼─────────────┘
                         ▼
             ┌─────────────────────────┐
             │     4-in-1 Splitter     │
             │   (Passive Bowden Hub)  │
             └───────────┬─────────────┘
                         │
                       ~850mm  (Common Reverse Bowden Tube)
                          │
                          ▼
              ┌─────────────────────────┐
              │  Toolhead Entry Sensor  │  --> Pin: EBB:PD0
              │  (Just above Extruder)  │      [filament_entry_sensor]
              └───────────┬─────────────┘
                          │
                     Extruder Gears (WW BMG / A4T)
                          │
              ┌───────────┴─────────────┐
              │   Lower Toolhead Sensor │  --> Pin: EBB:PA15
              │        (At Nozzle)      │      [filament_nozzle_sensor]
              └─────────────────────────┘
```

### Tube Length Calibration
- **`spool_load_park_retract_length: 400`**: When a new spool is inserted, the ACE hardware feeds ~500–550mm. KLIPPACE automatically rewinds 400mm so the tip parks ~100–150mm from the ACE (~50mm before the 150mm splitter), keeping the splitter completely open so other slots can feed freely.
- **`toolchange_load_length: 1100`**: High-speed feeding distance down towards the toolhead entry sensor.
- **`filament_runout_sensor_name_entry: filament_entry_sensor`**: Upper toolhead sensor (`^EBB:PD0`) directly above the extruder gears. Fast Bowden feed transitions to pressure feeding the instant this switch trips.
- **`filament_runout_sensor_name_nozzle: filament_nozzle_sensor`**: Lower toolhead sensor (`^EBB:PA15`) near the nozzle.
- **`ace_entry_feeding_speed: 16`**: Once the entry sensor trips, the ACE continues actively pushing forward at 16 mm/s while the extruder steps forward at 8 mm/s (`extruder_feeding_speed`). This differential speed builds forward pressure inside the Bowden tube to overcome the mechanical resistance of the entry switch lever and seat firmly into the extruder drive gears.
- **`extruder_feeding_speed: 8`**: Extruder rotational speed during coordinated entry to nozzle.
- **`max_entry_to_nozzle_length: 80`**: Safety distance limit for coordinated feeding between the entry sensor and nozzle sensor.
- **`toolhead_full_purge_length: 50`**: Distance to push through the nozzle to prime.

---

## 2. Hardware Pin & Sensor Mapping

In [`config/voron24/ace_voron24_hardware.cfg`](config/voron24/ace_voron24_hardware.cfg):

| Function | Pin | Macro Sensor Name | Notes |
| :--- | :--- | :--- | :--- |
| **Toolhead Entry Switch** | `^EBB:PD0` | `filament_entry_sensor` | Sits just before extruder gears. Triggers ACE fast-feed stop. |
| **Lower Nozzle Switch** | `^EBB:PA15` | `filament_nozzle_sensor` | Sits near nozzle / post-extruder. |
| **Crossbow Cutter Pin** | N/A (Mechanical) | Engaged at `X0 Y359` | Depresses Crossbow cutter lever against gantry pin. |
| **Nozzle Scrubber** | N/A (Mechanical) | `X108-158 Y350 Z6.0` | 50mm scrub stroke across brass/silicone brush. |
| **Purge Position** | N/A (Space) | `X90 Y355 Z15` | Rear rail purge bucket/chute location adjacent to brush. |
| **Silicone Stopper** | N/A (Mechanical) | `X90 Y350 Z3.5` | Nozzle rests on silicone pad during filament swaps to prevent oozing. |

> [!NOTE]
> The Anycubic servo poop basket (`[servo servo_wipe]`) is **disabled** on Voron (`servo_enable: False`). No servo pins are defined, preventing pin conflicts with `EBB:PB14` (the extruder step pin).

---

## 3. Installation & Integration

### Option A: Using the Interactive Installer
On your printer's Raspberry Pi / host:
```bash
cd ~/KLIPPACE
./installer.sh
```
1. In Step 2, select **`1) Voron 2.4`**.
2. The installer will copy all files in `config/voron24/` to `~/printer_data/config/` and automatically add `[include ace_voron24.cfg]` to your `printer.cfg`.

### Option B: Manual Setup
If you copy files manually:
1. Copy the contents of `config/voron24/` into your `~/printer_data/config/` directory.
2. In your `printer.cfg`, ensure the top includes:
   ```ini
   [include ace_voron24.cfg]
   ```
3. **Avoid Duplicate `CUT_TIP`**: In `printer.cfg`, comment out your existing `[gcode_macro CUT_TIP]` block. The exact same motion sequence is now provided by `ace_voron24_macros.cfg`.

---

## 4. Verification & Testing Sequence

Before running a full multi-material print, test each subsystem step-by-step:

### Step 1: Verify Sensor States
Run in the Mainsail/Fluidd console:
```gcode
QUERY_FILAMENT_SENSOR SENSOR=filament_entry_sensor
QUERY_FILAMENT_SENSOR SENSOR=filament_nozzle_sensor
```
- Both should report `Filament Sensor filament_entry_sensor: filament not detected` when empty.
- Insert filament by hand into the top entry switch; it should report `filament detected`.
- *(If inverted, change `switch_pin: ^EBB:PD0` to `switch_pin: ^!EBB:PD0` in `ace_voron24_hardware.cfg`).*

### Step 2: Test Cutter Motion
Heat hotend to 220°C, home XYZ, and test the cutter stroke:
```gcode
G28
M109 S220
CUT_TIP
```
- Toolhead moves to `X0 Y340`
- Moves to `X0 Y359` at F2000 to depress the cutter pin
- Retracts 10mm filament
- Exits to `X0 Y330`

### Step 3: Test Nozzle Scrubber & Silicone Stopper
Test the nozzle clean/scrubber:
```gcode
CLEAN_NOZZLE
```
- Toolhead moves to `X108 Y350`, lowers to `Z6.0`, scrubs across the brush 6 times, then lifts to `Z25`.

Test the silicone stopper park position:
```gcode
PARK_ON_STOPPER
```
- Toolhead travels to `X90 Y350` at safe Z height, then lowers to `Z3.5` to rest the nozzle on the silicone stopper.

Lift off the stopper:
```gcode
LIFT_FROM_STOPPER
```
- Toolhead lifts safely back up to `Z15`.

### Step 4: Test First Tool Load & Unload
With filament loaded in Slot 0 of your ACE Pro:
```gcode
# Load Slot 0 (T0) to nozzle:
T0

# Check tool state:
ACE_STATUS

# Unload filament back to ACE Pro:
ACE_CHANGE_TOOL TOOL=-1
```
Observe that:
1. Filament feeds rapidly from ACE through the splitter down the 850mm tube.
2. As soon as it hits the entry switch (`EBB:PD0`), fast feed transitions to slow coordinated feeding at 8 mm/s.
3. The ACE continues pushing forward with active pressure while the extruder motor steps forward synchronously in 2mm chunks, pushing past the switch lever and through the extruder gears.
4. Coordinated feeding continues until the nozzle sensor (`EBB:PA15`) trips.
5. Once `EBB:PA15` triggers, ACE feed stops, switches to feed assist, and primes 50mm through the nozzle over `X90 Y355` before wiping across the brush.
6. On unload, nozzle heats, `CUT_TIP` shears the tip, and ACE Pro pulls the filament completely out of the toolhead and past the 4-in-1 splitter.

### Step 5: Loading New Spools & Auto-Park
When inserting a new spool into any slot:
1. Push filament into the ACE slot funnel until the motor grabs it.
2. The ACE feeds ~500–550mm through the tube.
3. Within 1 second of entering `ready` state, KLIPPACE automatically rewinds **400mm** (`spool_load_park_retract_length: 400`).
4. The tip retreats out of the 4-in-1 splitter and rests ~50mm before the splitter.
5. You can now load the next slot without collisions!

*Manual park buttons available in Mainsail/Fluidd:*
- `PARK_SLOT SLOT=0` (or `SLOT=1`, `2`, `3`)
- `PARK_ALL_SLOTS`

---

## 5. Slicer Configuration (OrcaSlicer)

### Machine Start G-Code
Update your **Machine Start G-code** in OrcaSlicer to pass the initial tool:
```gcode
PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer] INITIAL_TOOL=[initial_tool]
```
*(Your `PRINT_START` will now automatically ensure the initial tool is loaded and wiped before running `LINE_PURGE`!)*

### Tool Change G-Code
In OrcaSlicer **Printer Settings -> Multimaterial -> Change filament G-code**:
```gcode
T[next_extruder]
```

### Post-Processing Script (Purge Volume Optimization)
Under **Print Settings -> Others -> Post-processing scripts**:
```
/usr/bin/python3 /home/pi/KLIPPACE/slicer/orca_flush_to_purgelength.py
```
This script automatically translates OrcaSlicer's flush volume matrix into the exact `PURGELENGTH` parameter for each tool change.
