"""Guard: LINE_PURGE must refuse to extrude with no filament loaded.

PRINT_START runs LINE_PURGE immediately after ACE_ON_PRINT_START.  If the initial
tool load failed in there, the purge used to extrude a 20mm line onto the bed
with nothing at the nozzle.  Observed live on 2026-10-04 in
pumpkin_PLA_7h45m.gcode:

    ACE: Initial toolchange failed, cancel print and switching extruder heater off
    ACE_CHANGE_TOOL error: Tool change to TNone failed during startup: ...
    Adaptive Purge: (168.7, 42.2) -> (198.7, 42.2), Extruding 20.0mm   <- purged anyway

These tests render the *real* ``LINE_PURGE`` body out of ``VORON/printer.cfg``
with Klipper's own Jinja settings, so deleting or inverting the guard fails them.
That matters: this repo already had one safety guard
(``_BLOBIFIER_SAFE_DESCEND``) sit inert for want of anyone rendering it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2", reason="jinja2 is a declared dependency (requirements.txt)")

REPO_ROOT = Path(__file__).resolve().parent.parent
PRINTER_CFG = REPO_ROOT / "VORON" / "printer.cfg"
MACRO_NAME = "LINE_PURGE"


def _macro_body(cfg_path: Path, name: str):
    """Extract the indented gcode body of a [gcode_macro NAME] section."""
    text = cfg_path.read_text()
    m = re.search(
        r"^\[gcode_macro %s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(name),
        text, re.S | re.M,
    )
    if not m:
        raise AssertionError(f"[gcode_macro {name}] not found in {cfg_path}")
    section = m.group(0)
    body = re.search(r"^gcode:\s*$(.*)", section, re.S | re.M)
    if not body:
        raise AssertionError(f"[gcode_macro {name}] has no gcode: body")
    return body.group(1)


class _Raise(Exception):
    """Stand-in for Klipper's action_raise_error, which aborts the gcode."""


class _PrinterStatus:
    """Fake of Klipper's GetStatusWrapper.

    ``__getitem__`` raises KeyError for unknown objects, exactly as the real
    wrapper does.  Jinja's getitem catches LookupError and yields Undefined, which
    is what makes ``printer['x'] is defined`` work in configs — so this fake has to
    raise, not return None, or the test would not exercise that path.
    """

    def __init__(self, objects):
        self._objects = objects

    def __getitem__(self, key):
        sval = str(key).strip()
        if sval not in self._objects:
            raise KeyError(key)
        return self._objects[sval]

    def __contains__(self, key):
        return str(key).strip() in self._objects

    def __iter__(self):
        return iter(self._objects)


def _render_line_purge(objects, params=None):
    """Render the real LINE_PURGE body.  Returns (result, raised, info_messages)."""
    env = jinja2.Environment("{%", "%}", "{", "}")   # Klipper's delimiters
    env.filters.setdefault("round", round)
    template = env.from_string(_macro_body(PRINTER_CFG, MACRO_NAME))

    raised = []
    info = []
    context = {
        "printer": _PrinterStatus(objects),
        "params": params or {},
        "action_respond_info": lambda msg: info.append(msg) or "",
        "action_raise_error": lambda msg: raised.append(msg) or (_ for _ in ()).throw(_Raise(msg)),
    }
    try:
        rendered = template.render(context)
    except _Raise:
        rendered = None
    return rendered, raised, info


def _base_objects(**overrides):
    """A printer where LINE_PURGE's non-guard parts can all evaluate."""
    objects = {
        "toolhead": {
            "max_velocity": 300.0,
            "axis_maximum": {"x": 355.0, "y": 360.0, "z": 230.0},
        },
        "exclude_object": {
            "objects": [{"polygon": [[100.0, 100.0], [150.0, 150.0]]}],
        },
        "output_pin ACE_Pro": {"value": 1.0},
        "gcode_macro _ACE_STATE": {"active": -1},
        "save_variables": {"variables": {"ace_current_index": -1}},
        "filament_switch_sensor filament_entry_sensor": {"filament_detected": False},
        "filament_switch_sensor filament_nozzle_sensor": {"filament_detected": False},
    }
    objects.update(overrides)
    return objects


# --------------------------------------------------------------------------
# the guard fires
# --------------------------------------------------------------------------

class TestGuardBlocks:
    def test_no_tool_and_clear_sensors_refuses_to_purge(self):
        result, raised, info = _render_line_purge(_base_objects())
        assert raised, "the guard must raise when nothing is loaded"
        assert "refusing to purge" in raised[0]
        assert result is None, "no gcode should be emitted when refusing"

    def test_message_is_actionable(self):
        _, raised, _ = _render_line_purge(_base_objects())
        msg = raised[0]
        assert "ace_current_index=-1" in msg, msg
        assert "tool load" in msg, msg

    def test_one_sensor_showing_filament_is_enough_to_allow(self):
        """OR, not AND: a single sensor vouching for filament must permit it."""
        objects = _base_objects(
            **{"filament_switch_sensor filament_entry_sensor": {"filament_detected": True}}
        )
        result, raised, _ = _render_line_purge(objects)
        assert not raised, raised
        assert result and "G92 E0" in result

    def test_nozzle_sensor_alone_also_allows(self):
        objects = _base_objects(
            **{"filament_switch_sensor filament_nozzle_sensor": {"filament_detected": True}}
        )
        _, raised, _ = _render_line_purge(objects)
        assert not raised, raised


# --------------------------------------------------------------------------
# the guard stays out of the way
# --------------------------------------------------------------------------

class TestGuardAllows:
    def test_tool_recorded_in_save_variables_allows(self):
        objects = _base_objects()
        objects["save_variables"] = {"variables": {"ace_current_index": 2}}
        result, raised, _ = _render_line_purge(objects)
        assert not raised, raised
        assert result and "G92 E0" in result

    def test_ace_disabled_skips_the_guard_entirely(self):
        """Single-material use must be unaffected."""
        objects = _base_objects(**{"output_pin ACE_Pro": {"value": 0.0}})
        _, raised, _ = _render_line_purge(objects)
        assert not raised, raised

    def test_machine_without_ace_is_untouched(self):
        """No ACE enable pin means ACE is not managing this printer.

        The pin is registered by the ACE module, so its absence is the signal
        that a machine is running single-material.  Discriminating on the pin
        alone (rather than also requiring _ACE_STATE) keeps every branch of the
        gate covered by a test.
        """
        objects = _base_objects()
        del objects["output_pin ACE_Pro"]
        del objects["gcode_macro _ACE_STATE"]
        _, raised, _ = _render_line_purge(objects)
        assert not raised, (
            "a machine without ACE must not have its purge blocked by this guard"
        )

    def test_ace_pin_off_is_untouched_even_with_no_filament(self):
        """Dropping to ACE-disabled must restore normal purging immediately."""
        objects = _base_objects(**{"output_pin ACE_Pro": {"value": 0.0}})
        assert objects["save_variables"]["variables"]["ace_current_index"] == -1
        _, raised, _ = _render_line_purge(objects)
        assert not raised, raised

    def test_ace_pin_present_but_no_value_still_guards(self):
        """A pin that exists without a readable value is treated as enabled.

        This matches ACE_ON_PRINT_START's `|default(1)` convention, so the guard
        errs toward protection when the pin state cannot be read.
        """
        objects = _base_objects(**{"output_pin ACE_Pro": {}})
        _, raised, _ = _render_line_purge(objects)
        assert raised, "an unreadable ACE pin should still be treated as enabled"

    def test_missing_sensors_do_not_block_a_recorded_tool(self):
        """Sensors are optional; ace_current_index is the authoritative signal."""
        objects = _base_objects()
        objects["save_variables"] = {"variables": {"ace_current_index": 0}}
        del objects["filament_switch_sensor filament_entry_sensor"]
        del objects["filament_switch_sensor filament_nozzle_sensor"]
        _, raised, _ = _render_line_purge(objects)
        assert not raised, raised

    def test_missing_sensors_block_when_no_tool_is_recorded(self):
        """Conservative: nothing vouches for filament, so refuse."""
        objects = _base_objects()
        del objects["filament_switch_sensor filament_entry_sensor"]
        del objects["filament_switch_sensor filament_nozzle_sensor"]
        _, raised, _ = _render_line_purge(objects)
        assert raised, "with no sensor and no tool state there is nothing to trust"

    def test_missing_save_variables_blocks_when_sensors_are_clear(self):
        objects = _base_objects()
        del objects["save_variables"]
        _, raised, _ = _render_line_purge(objects)
        assert raised, raised


# --------------------------------------------------------------------------
# the guard is still there, and line purge still works
# --------------------------------------------------------------------------

class TestGuardPresent:
    def test_guard_text_is_present_in_the_config(self):
        body = _macro_body(PRINTER_CFG, MACRO_NAME)
        assert "refusing to purge" in body, "the guard has been removed"
        assert "action_raise_error" in body, "the guard no longer aborts"

    def test_the_purge_still_emits_its_extrusion(self):
        objects = _base_objects()
        objects["save_variables"] = {"variables": {"ace_current_index": 1}}
        result, _, _ = _render_line_purge(objects)
        assert "E20.0" in result, result          # default PURGE_AMOUNT
        assert "STATE_LINE_PURGE" in result

    def test_purge_params_are_honoured(self):
        objects = _base_objects()
        objects["save_variables"] = {"variables": {"ace_current_index": 1}}
        result, _, _ = _render_line_purge(objects, {"PURGE_AMOUNT": 42.0})
        assert "E42.0" in result, result

    def test_aliases_still_delegate(self):
        text = PRINTER_CFG.read_text()
        for alias in ("ADAPTIVE_PURGE", "VORON_PURGE"):
            assert re.search(r"\[gcode_macro %s\]" % alias, text), alias
