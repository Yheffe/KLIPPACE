"""Tests for the MMU shim's action commands.

The card's Load/Unload buttons send plain ``MMU_LOAD`` / ``MMU_UNLOAD``, but
Fluidd also has extruder-only variants that append ``EXTRUDER_ONLY=1``. Those
must move only the segment between the toolhead entry sensor and the nozzle
rather than running a full toolchange or a full unload.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Gcmd:
    """Minimal stand-in for Klipper's gcode command object."""

    def __init__(self, **params):
        self.params = params
        self.messages = []

    def get_int(self, name, default=None):
        value = self.params.get(name)
        return default if value is None else int(value)

    def respond_info(self, msg):
        self.messages.append(msg)


class _Gcode:
    """Records scripts instead of running them."""

    def __init__(self):
        self.scripts = []
        self.messages = []

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def respond_info(self, msg):
        self.messages.append(msg)


def _make_shim(active_gate=-1, entry_to_nozzle=80, has_instances=True):
    """Build a MmuShim without running __init__ (no Klipper needed)."""
    from extras.ace.mmu_shim import MmuShim

    shim = object.__new__(MmuShim)
    instances = []
    if has_instances:
        instances.append(SimpleNamespace(max_entry_to_nozzle_length=entry_to_nozzle))
    shim.manager = SimpleNamespace(
        state={"ace_current_index": active_gate},
        instances=instances,
        has_rdm_sensor=lambda: False,
    )
    shim.gcode = _Gcode()
    shim.printer = SimpleNamespace(
        lookup_object=lambda name, default=None: default,
    )
    shim.logger = SimpleNamespace(exception=lambda *a, **k: None)
    return shim


class TestExtruderOnlyLength:
    def test_reads_the_configured_entry_to_nozzle_distance(self):
        shim = _make_shim(entry_to_nozzle=95)
        assert shim._extruder_only_length() == 95.0

    @pytest.mark.parametrize("value", [0, None, "junk"])
    def test_falls_back_when_the_value_is_unusable(self, value):
        shim = _make_shim(entry_to_nozzle=value)
        assert shim._extruder_only_length() == 80.0

    def test_falls_back_when_there_are_no_instances(self):
        shim = _make_shim(has_instances=False)
        assert shim._extruder_only_length() == 80.0


class TestActiveGateIndex:
    def test_returns_the_loaded_gate(self):
        assert _make_shim(active_gate=2)._active_gate_index() == 2

    def test_returns_minus_one_when_nothing_is_loaded(self):
        assert _make_shim(active_gate=-1)._active_gate_index() == -1

    @pytest.mark.parametrize("value", [None, "junk"])
    def test_tolerates_junk_state(self, value):
        shim = _make_shim()
        shim.manager.state["ace_current_index"] = value
        assert shim._active_gate_index() == -1


class TestLoad:
    def test_plain_load_runs_a_toolchange(self):
        shim = _make_shim(active_gate=1)
        shim.cmd_MMU_LOAD(_Gcmd())
        assert shim.gcode.scripts == ["ACE_CHANGE_TOOL GATE=1"]

    def test_extruder_only_feeds_just_the_nozzle_segment(self):
        shim = _make_shim(active_gate=2, entry_to_nozzle=80)
        gcmd = _Gcmd(EXTRUDER_ONLY=1)
        shim.cmd_MMU_LOAD(gcmd)
        assert shim.gcode.scripts == ["ACE_FEED T=2 LENGTH=80"]
        # It must not fall through to a full toolchange.
        assert not any("CHANGE_TOOL" in s for s in shim.gcode.scripts)

    def test_extruder_only_with_no_spool_loaded_does_nothing(self):
        shim = _make_shim(active_gate=-1)
        gcmd = _Gcmd(EXTRUDER_ONLY=1)
        shim.cmd_MMU_LOAD(gcmd)
        assert shim.gcode.scripts == []
        assert any("EXTRUDER_ONLY" in m for m in gcmd.messages)

    def test_extruder_only_zero_is_treated_as_a_normal_load(self):
        shim = _make_shim(active_gate=0)
        shim.cmd_MMU_LOAD(_Gcmd(EXTRUDER_ONLY=0))
        assert shim.gcode.scripts == ["ACE_CHANGE_TOOL GATE=0"]

    def test_explicit_gate_is_still_honoured(self):
        shim = _make_shim(active_gate=-1)
        shim.cmd_MMU_LOAD(_Gcmd(GATE=3))
        assert shim.gcode.scripts == ["ACE_CHANGE_TOOL GATE=3"]


class TestUnload:
    def test_plain_unload_delegates_to_smart_unload(self):
        shim = _make_shim(active_gate=1)
        shim.cmd_MMU_UNLOAD(_Gcmd())
        assert shim.gcode.scripts == ["ACE_SMART_UNLOAD"]

    def test_extruder_only_retracts_just_the_nozzle_segment(self):
        shim = _make_shim(active_gate=2, entry_to_nozzle=80)
        shim.cmd_MMU_UNLOAD(_Gcmd(EXTRUDER_ONLY=1))
        assert shim.gcode.scripts == ["ACE_RETRACT T=2 LENGTH=80"]

    def test_extruder_only_with_no_spool_loaded_does_nothing(self):
        shim = _make_shim(active_gate=-1)
        gcmd = _Gcmd(EXTRUDER_ONLY=1)
        shim.cmd_MMU_UNLOAD(gcmd)
        assert shim.gcode.scripts == []
        assert any("EXTRUDER_ONLY" in m for m in gcmd.messages)
