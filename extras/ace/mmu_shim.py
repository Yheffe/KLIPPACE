"""
KLIPPACE MMU Compatibility Shim for Mainsail & Fluidd
Exposes Happy Hare MMU printer object schema and standard MMU G-code commands
so that Mainsail and Fluidd automatically display their native MMU dashboard cards
while preserving full Anycubic ACE Pro hardware capabilities and controls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional


class MmuShim:
    """
    Klipper printer object shim implementing the Happy Hare MMU status interface.
    Mirrors live telemetry from Anycubic ACE Pro instances and managers.
    """

    def __init__(self, printer, gcode, manager):
        self.printer = printer
        self.gcode = gcode
        self.manager = manager
        self.logger = logging.getLogger(__name__)

        self.tool_to_gate_map: List[int] = []
        self._action = "Idle"

        # Register standard MMU G-code commands
        self._register_mmu_commands()

    def _register_mmu_commands(self):
        """Register MMU G-codes expected by Mainsail/Fluidd MMU panels."""
        cmd_map = {
            "MMU_CHANGE_TOOL": self.cmd_MMU_CHANGE_TOOL,
            "MMU_TOOL": self.cmd_MMU_CHANGE_TOOL,
            "MMU_SELECT": self.cmd_MMU_SELECT,
            "MMU_LOAD": self.cmd_MMU_LOAD,
            "MMU_UNLOAD": self.cmd_MMU_UNLOAD,
            "MMU_EJECT": self.cmd_MMU_EJECT,
            "MMU_CUT_TIP": self.cmd_MMU_CUT_TIP,
            "MMU_RECOVER": self.cmd_MMU_RECOVER,
            "MMU_CHECK_GATES": self.cmd_MMU_CHECK_GATES,
            "MMU_STATUS": self.cmd_MMU_STATUS,
            "MMU_GATE_MAP": self.cmd_MMU_GATE_MAP,
            "MMU_TTG_MAP": self.cmd_MMU_TTG_MAP,
        }

        for cmd, handler in cmd_map.items():
            try:
                self.gcode.register_command(
                    cmd, handler, desc=f"Happy Hare MMU compatibility: {cmd}"
                )
            except Exception as e:
                self.logger.debug(f"MmuShim: Command {cmd} already registered or error: {e}")

    # =========================================================================
    # Status Dictionary for Moonraker / Mainsail / Fluidd
    # =========================================================================

    def get_status(self, eventtime=None) -> Dict[str, Any]:
        """Return the Happy Hare compatible MMU status dictionary."""
        try:
            num_gates = 0
            gate_status = []
            gate_color = []
            gate_material = []
            gate_spool_id = []
            gate_speed = []
            units_list = []

            instances = getattr(self.manager, "instances", [])
            for inst_idx, inst in enumerate(instances):
                inst_status = inst.get_status(eventtime) if hasattr(inst, "get_status") else {}
                slots = inst_status.get("slots", [])
                num_gates += len(slots)

                dryer = inst_status.get("dryer_status", {})
                temp = inst_status.get("temp", 0)

                units_list.append({
                    "name": f"ACE Pro {inst_idx}",
                    "num_gates": len(slots),
                    "first_gate": inst_idx * 4,
                    "model": inst_status.get("model", "Anycubic Color Engine Pro"),
                    "temp": temp,
                    "humidity": 0,
                    "heater": "temperature_sensor ace_dryer",
                    "status": inst_status.get("status", "ready"),
                    "dryer_status": dryer.get("status", "stop"),
                    "dryer_target_temp": dryer.get("target_temp", 0),
                    "dryer_remain_time": dryer.get("remain_time", 0),
                    "rfid_enabled": bool(inst_status.get("enable_rfid", 1)),
                })

                for slot in slots:
                    st = slot.get("status", "empty")
                    if st == "ready":
                        gate_status.append(1)  # Available from spool
                    elif st == "empty":
                        gate_status.append(0)  # Empty
                    else:
                        gate_status.append(-1)  # Unknown / busy

                    # Normalize color to hex string '#rrggbb'
                    c = slot.get("color", [255, 255, 255])
                    if isinstance(c, (list, tuple)) and len(c) >= 3:
                        hex_c = f"#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x}"
                    else:
                        hex_c = "#ffffff"
                    gate_color.append(hex_c)

                    mat = slot.get("material", "PLA") or "PLA"
                    gate_material.append(mat)

                    spool_id = slot.get("spool_id")
                    gate_spool_id.append(int(spool_id) if spool_id is not None else -1)
                    gate_speed.append(100.0)

            # Active tool & filament location
            active_tool = self.manager.state.get("ace_current_index", -1)
            fil_pos = self.manager.state.get("ace_filament_pos", "bowden")
            is_loaded = (fil_pos == "nozzle") and (active_tool >= 0)

            # Ensure tool_to_gate_map matches num_gates
            if len(self.tool_to_gate_map) != num_gates:
                self.tool_to_gate_map = list(range(num_gates))

            # Query print state
            print_stats = self.printer.lookup_object("print_stats", None)
            print_state = "standby"
            if print_stats and hasattr(print_stats, "get_status"):
                print_state = print_stats.get_status(eventtime).get("state", "standby")

            action = "Idle"
            if getattr(self.manager, "toolchange_in_progress", False):
                action = "Loading"
            elif print_state == "printing":
                action = "Printing"

            return {
                "enabled": True,
                "is_enabled": True,
                "num_gates": num_gates,
                "gate_status": gate_status,
                "gate_color": gate_color,
                "gate_material": gate_material,
                "gate_filament_name": list(gate_material),
                "gate_spool_id": gate_spool_id,
                "gate_speed": gate_speed,
                "gate_speed_override": [100.0] * num_gates,
                "tool": active_tool,
                "gate": active_tool if active_tool >= 0 else -1,
                "tool_to_gate_map": list(self.tool_to_gate_map),
                "ttg_map": list(self.tool_to_gate_map),
                "endless_spool_groups": list(range(num_gates)),
                "has_bypass": False,
                "action": action,
                "filament": "Loaded" if is_loaded else "Unloaded",
                "filament_pos": fil_pos,
                "is_homed": True,
                "is_locked": False,
                "print_state": print_state,
                "active_spool": active_tool,
                "units": len(units_list),
                "unit": units_list,
                "clog_detection": bool(self.manager.ace_config.get("tangle_detection", False)),
                "endless_spool": bool(self.manager.state.get("ace_endless_spool_enabled", False)),
            }
        except Exception as e:
            self.logger.exception(f"MmuShim.get_status failed: {e}")
            return {
                "enabled": True,
                "is_enabled": True,
                "num_gates": 4,
                "gate_status": [1, 1, 1, 1],
                "gate_color": ["#ff7f32", "#ff3a2f", "#eff0f1", "#000000"],
                "gate_material": ["PLA", "PLA", "PLA", "PLA"],
                "gate_filament_name": ["PLA", "PLA", "PLA", "PLA"],
                "gate_spool_id": [-1, -1, -1, -1],
                "gate_speed": [100.0, 100.0, 100.0, 100.0],
                "gate_speed_override": [100.0, 100.0, 100.0, 100.0],
                "tool": -1,
                "gate": -1,
                "tool_to_gate_map": [0, 1, 2, 3],
                "ttg_map": [0, 1, 2, 3],
                "endless_spool_groups": [0, 1, 2, 3],
                "has_bypass": False,
                "action": "Idle",
                "filament": "Unloaded",
                "filament_pos": "bowden",
                "is_homed": True,
                "is_locked": False,
                "print_state": "standby",
                "active_spool": -1,
                "units": 1,
                "unit": [],
                "clog_detection": False,
                "endless_spool": False,
            }


class MmuMachineShim:
    """
    Klipper printer object shim implementing the Happy Hare MMU Machine topology interface.
    Exposes unit definitions (unit_0, unit_1, etc.) for Fluidd / Mainsail MMU unit rendering.
    """

    def __init__(self, manager):
        self.manager = manager

    def get_status(self, eventtime=None) -> Dict[str, Any]:
        instances = getattr(self.manager, "instances", [])
        num_units = max(len(instances), 1)
        res: Dict[str, Any] = {"num_units": num_units}

        for idx, inst in enumerate(instances):
            slots = getattr(inst, "slots", [None] * 4)
            res[f"unit_{idx}"] = {
                "name": f"ACE Pro {idx}",
                "vendor": "Anycubic",
                "version": "1.0",
                "num_gates": len(slots),
                "first_gate": idx * 4,
                "has_bypass": False,
            }

        if not instances:
            res["unit_0"] = {
                "name": "ACE Pro 0",
                "vendor": "Anycubic",
                "version": "1.0",
                "num_gates": 4,
                "first_gate": 0,
                "has_bypass": False,
            }

        return res

    # =========================================================================
    # G-Code Command Implementations
    # =========================================================================

    def cmd_MMU_CHANGE_TOOL(self, gcmd):
        """Change to specified tool: MMU_CHANGE_TOOL TOOL=<int>"""
        tool = gcmd.get_int("TOOL", None)
        if tool is None:
            gcmd.respond_error("MMU_CHANGE_TOOL: TOOL parameter is required")
            return
        gcmd.respond_info(f"MMU: Changing to Tool T{tool}")
        self.gcode.run_script_from_command(f"T{tool}")

    def cmd_MMU_SELECT(self, gcmd):
        """Select a tool or gate: MMU_SELECT [TOOL=<int>] [GATE=<int>]"""
        tool = gcmd.get_int("TOOL", None)
        gate = gcmd.get_int("GATE", None)
        target = tool if tool is not None else gate
        if target is None:
            gcmd.respond_error("MMU_SELECT: TOOL or GATE parameter is required")
            return
        gcmd.respond_info(f"MMU: Selecting tool T{target}")
        self.gcode.run_script_from_command(f"T{target}")

    def cmd_MMU_LOAD(self, gcmd):
        """Load filament into toolhead/nozzle."""
        tool = gcmd.get_int("TOOL", self.manager.state.get("ace_current_index", 0))
        gcmd.respond_info(f"MMU: Loading tool T{tool}")
        self.gcode.run_script_from_command(f"T{tool}")

    def cmd_MMU_UNLOAD(self, gcmd):
        """Unload filament from nozzle."""
        gcmd.respond_info("MMU: Unloading active tool from nozzle")
        # Run UNLOAD_TOOL macro if defined, else ACE_SMART_UNLOAD
        if self.printer.lookup_object("gcode_macro UNLOAD_TOOL", None):
            self.gcode.run_script_from_command("UNLOAD_TOOL")
        else:
            self.gcode.run_script_from_command("ACE_SMART_UNLOAD")

    def cmd_MMU_EJECT(self, gcmd):
        """Eject/retract filament to park position."""
        gcmd.respond_info("MMU: Ejecting filament to park position")
        if self.printer.lookup_object("gcode_macro UNLOAD_TOOL", None):
            self.gcode.run_script_from_command("UNLOAD_TOOL")
        else:
            self.gcode.run_script_from_command("ACE_SMART_UNLOAD")

    def cmd_MMU_CUT_TIP(self, gcmd):
        """Cut filament tip using toolhead cutter pin."""
        gcmd.respond_info("MMU: Executing filament tip cut")
        if self.printer.lookup_object("gcode_macro CUT_TIP", None):
            self.gcode.run_script_from_command("CUT_TIP")
        else:
            gcmd.respond_error("CUT_TIP macro not found")

    def cmd_MMU_RECOVER(self, gcmd):
        """Reset state / recover MMU status."""
        gcmd.respond_info("MMU: Recovering toolhead / active spool state")
        self.gcode.run_script_from_command("ACE_RESET_ACTIVE_TOOLHEAD")

    def cmd_MMU_CHECK_GATES(self, gcmd):
        """Query/refresh ACE slot RFID and presence status."""
        gcmd.respond_info("MMU: Refreshing ACE Pro slot telemetry...")
        self.gcode.run_script_from_command("ACE_QUERY_SLOTS")

    def cmd_MMU_STATUS(self, gcmd):
        """Output human-readable MMU & ACE status report."""
        st = self.get_status()
        active_t = st.get("tool", -1)
        active_str = f"T{active_t}" if active_t >= 0 else "None (Standby)"
        fil_str = st.get("filament", "Unloaded")

        lines = [
            "// =================== MMU / ACE STATUS ===================",
            f"// Active Tool: {active_str} | Filament State: {fil_str}",
            f"// Total Gates: {st.get('num_gates', 4)} | Units: {st.get('units', 1)}",
            "// --------------------------------------------------------",
        ]

        for i in range(st.get("num_gates", 4)):
            status_text = "READY" if st["gate_status"][i] == 1 else ("EMPTY" if st["gate_status"][i] == 0 else "UNKNOWN")
            color_text = st["gate_color"][i]
            mat_text = st["gate_material"][i]
            lines.append(f"// Gate {i} [T{i}]: {status_text:<8} | Mat: {mat_text:<6} | Color: {color_text}")

        lines.append("// ========================================================")
        for line in lines:
            gcmd.respond_info(line)

    def cmd_MMU_GATE_MAP(self, gcmd):
        """Display gate map."""
        self.cmd_MMU_STATUS(gcmd)

    def cmd_MMU_TTG_MAP(self, gcmd):
        """Display or set Tool-to-Gate mapping."""
        tool = gcmd.get_int("TOOL", None)
        gate = gcmd.get_int("GATE", None)
        if tool is not None and gate is not None:
            if 0 <= tool < len(self.tool_to_gate_map) and 0 <= gate < len(self.tool_to_gate_map):
                self.tool_to_gate_map[tool] = gate
                gcmd.respond_info(f"MMU: Mapped Tool T{tool} to Gate {gate}")
            else:
                gcmd.respond_error("MMU_TTG_MAP: Tool or gate out of range")
        else:
            ttg_str = ", ".join(f"T{t}->G{g}" for t, g in enumerate(self.tool_to_gate_map))
            gcmd.respond_info(f"MMU Tool-to-Gate Map: {ttg_str}")
