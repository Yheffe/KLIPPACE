"""Tests for the MMU status fields that third-party UIs read.

Fluidd and our own card read ``gate_temp``, but Mainsail reads
``gate_temperature`` (the Happy Hare spelling). Mainsail also indexes a
per-gate ``espooler`` list, falling back to the scalar ``espooler_active``
for the selected gate. Both spellings are published so one printer can serve
either UI.

These tests also pin the *absence* of fields that were added speculatively and
turned out to be read by nothing -- ``gate_color_rgb`` and ``num_units`` on the
``mmu`` object. Mainsail takes ``num_units`` from the separate ``mmu_machine``
object, which ``MmuMachineShim`` already provides.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Instance:
    """Stand-in for an ACE instance."""

    def __init__(self, slots, feed_assist_slot=-1, raise_on_status=False):
        self.slots = slots
        self._status = {
            "slots": slots,
            "dryer_status": {"status": "stop", "target_temp": 0, "remain_time": 0},
            "temp": 28,
            "model": "Anycubic Color Engine Pro",
            "status": "ready",
            "enable_rfid": 1,
            "feed_assist_slot": feed_assist_slot,
        }
        self._raise = raise_on_status

    def get_status(self, eventtime=None):
        if self._raise:
            raise RuntimeError("ACE instance unavailable")
        return self._status


def _slot(status="ready", color=(255, 127, 50), material="PLA", spool_id=None):
    return {
        "status": status,
        "color": list(color),
        "material": material,
        "spool_id": spool_id,
    }


def _make_shim(instances, active_gate=-1, filament_pos="bowden"):
    """Build a MmuShim without running __init__ (no Klipper needed)."""
    from extras.ace.mmu_shim import MmuShim

    shim = object.__new__(MmuShim)
    shim.manager = SimpleNamespace(
        state={
            "ace_current_index": active_gate,
            "ace_filament_pos": filament_pos,
            "ace_endless_spool_enabled": False,
        },
        instances=instances,
        ace_config={},
        toolchange_in_progress=False,
    )
    shim.printer = SimpleNamespace(lookup_object=lambda name, default=None: default)
    shim.logger = SimpleNamespace(exception=lambda *a, **k: None)
    shim.tool_to_gate_map = []
    shim.endless_spool_groups = []
    shim._active_tool = -1
    return shim


def _four_slots():
    return [_slot(spool_id=i) for i in range(4)]


class TestGateTemperature:
    """Mainsail reads gate_temperature; Fluidd reads gate_temp."""

    def test_both_spellings_are_published_and_identical(self):
        status = _make_shim([_Instance(_four_slots())]).get_status()
        assert status["gate_temperature"] == status["gate_temp"]

    def test_length_matches_the_gate_count(self):
        status = _make_shim([_Instance(_four_slots())]).get_status()
        assert len(status["gate_temperature"]) == status["num_gates"] == 4

    def test_values_are_resolved_per_gate(self):
        # Two materials, interleaved: the resolution must follow each slot.
        slots = [
            _slot(material="PLA"),
            _slot(material="ABS"),
            _slot(material="PLA"),
            _slot(material="ABS"),
        ]
        status = _make_shim([_Instance(slots)]).get_status()
        temps = status["gate_temp"]
        assert all(isinstance(t, int) and t > 0 for t in temps)
        assert temps[0] == temps[2]
        assert temps[1] == temps[3]
        assert temps[0] != temps[1]

    def test_empty_slot_inherits_its_material_default(self):
        # Documents current behaviour: an empty slot with no material still
        # resolves to the PLA default rather than 0. Mainsail shows a gate's
        # temperature whenever it is > 0, so an empty gate advertises a temp.
        slots = _four_slots()
        slots[2] = _slot(status="empty", material="")
        status = _make_shim([_Instance(slots)]).get_status()
        assert status["gate_temp"][2] == status["material_temps"]["PLA"]


class TestEspooler:
    """Mainsail indexes espooler per gate, with a scalar legacy fallback."""

    def test_espooler_is_a_list_covering_every_gate(self):
        status = _make_shim([_Instance(_four_slots())]).get_status()
        assert isinstance(status["espooler"], list)
        assert len(status["espooler"]) == status["num_gates"]

    def test_no_feed_assist_reports_all_none(self):
        status = _make_shim([_Instance(_four_slots())]).get_status()
        assert status["espooler"] == [None, None, None, None]

    def test_feed_assist_marks_only_that_gate(self):
        status = _make_shim([_Instance(_four_slots(), feed_assist_slot=2)]).get_status()
        assert status["espooler"] == [None, None, "assist", None]

    def test_feed_assist_slot_zero_is_not_treated_as_absent(self):
        status = _make_shim([_Instance(_four_slots(), feed_assist_slot=0)]).get_status()
        assert status["espooler"] == ["assist", None, None, None]

    def test_junk_feed_assist_slot_is_ignored(self):
        status = _make_shim([_Instance(_four_slots(), feed_assist_slot="n/a")]).get_status()
        assert status["espooler"] == [None, None, None, None]

    def test_scalar_fallback_matches_the_selected_gate(self):
        shim = _make_shim(
            [_Instance(_four_slots(), feed_assist_slot=1)],
            active_gate=1,
            filament_pos="nozzle",
        )
        status = shim.get_status()
        assert status["gate"] == 1
        assert status["espooler_active"] == "assist"

    def test_scalar_fallback_is_none_when_a_different_gate_is_selected(self):
        shim = _make_shim(
            [_Instance(_four_slots(), feed_assist_slot=1)],
            active_gate=0,
            filament_pos="nozzle",
        )
        status = shim.get_status()
        assert status["gate"] == 0
        assert status["espooler_active"] is None

    def test_multi_unit_assist_maps_to_a_global_gate(self):
        # Feed assist is reported per instance as a LOCAL slot index; the
        # second instance's local slot 1 is global gate 5.
        status = _make_shim(
            [_Instance(_four_slots()), _Instance(_four_slots(), feed_assist_slot=1)]
        ).get_status()
        assert status["num_gates"] == 8
        assert status["espooler"] == [None, None, None, None, None, "assist", None, None]


class TestNoSpeculativeFields:
    """Fields added without a confirmed reader must not reappear."""

    @pytest.mark.parametrize("field", ["gate_color_rgb", "num_units"])
    def test_unread_field_is_absent(self, field):
        status = _make_shim([_Instance(_four_slots())]).get_status()
        assert field not in status


class TestFallbackStatus:
    """A failing instance must still yield a UI-usable dict."""

    def test_fallback_publishes_mainsail_fields(self):
        status = _make_shim([_Instance(_four_slots(), raise_on_status=True)]).get_status()
        assert status["num_gates"] == 4
        assert status["gate_temperature"] == status["gate_temp"] == [0, 0, 0, 0]
        assert status["espooler"] == [None, None, None, None]
        assert status["espooler_active"] is None

    def test_fallback_has_no_unread_fields(self):
        status = _make_shim([_Instance(_four_slots(), raise_on_status=True)]).get_status()
        assert "gate_color_rgb" not in status
        assert "num_units" not in status


class TestMmuMachine:
    """Mainsail draws gates from mmu_machine, not from mmu.num_gates."""

    def test_unit_exposes_the_shape_mainsail_reads(self):
        from extras.ace.mmu_shim import MmuMachineShim

        manager = SimpleNamespace(instances=[_Instance(_four_slots())])
        status = MmuMachineShim(manager).get_status()
        assert status["num_units"] == 1
        assert status["unit_0"]["num_gates"] == 4
        assert status["unit_0"]["first_gate"] == 0
        assert "has_bypass" in status["unit_0"]

    def test_second_unit_starts_after_the_first(self):
        from extras.ace.mmu_shim import MmuMachineShim

        manager = SimpleNamespace(
            instances=[_Instance(_four_slots()), _Instance(_four_slots())]
        )
        status = MmuMachineShim(manager).get_status()
        assert status["num_units"] == 2
        assert status["unit_1"]["first_gate"] == 4

    def test_never_reports_zero_units(self):
        from extras.ace.mmu_shim import MmuMachineShim

        status = MmuMachineShim(SimpleNamespace(instances=[])).get_status()
        assert status["num_units"] == 1
