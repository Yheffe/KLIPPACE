"""An empty slot must not be reported as a loaded spool.

Reported live 2026-10-30: "T3 does not change no matter what I do. It's stuck
saying I have black PLA even if nothing is present."

The inventory was correct - ``material: ""``, ``status: "empty"`` - but the shim
read::

    mat = slot.get("material", "PLA") or "PLA"

so an absent material became ``PLA``. Two consequences, both visible:

  * every gate advertised a material, so a client drew a spool that was not there;
  * it defeated the dashboard's own "no colour" sentinel. The card only shows its
    neutral placeholder when the RGB is all-zero **and** the material is unknown,
    so a fabricated ``PLA`` left the empty slot painted solid black and labelled
    PLA. The card was right; the data it was given was not.

The rule these tests enforce: publish what is stored. An empty slot has no
material, so it reports none - and no fabricated temperature either, which is what
Mainsail keys its "loaded" display off.

The error path had the same defect in a worse form: when ``get_status()`` threw it
returned four *ready PLA spools*, which renders a fully stocked machine and hides
the failure that produced it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Instance:
    def __init__(self, slots, raise_on_status=False):
        self._status = {
            "slots": slots,
            "dryer_status": {"status": "stop", "target_temp": 0, "remain_time": 0},
            "temp": 28,
            "model": "Anycubic Color Engine Pro",
            "status": "ready",
            "enable_rfid": 1,
            "feed_assist_slot": -1,
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


def _make_shim(instances, active_gate=-1):
    from extras.ace.mmu_shim import MmuShim

    shim = object.__new__(MmuShim)
    shim.manager = SimpleNamespace(
        state={
            "ace_current_index": active_gate,
            "ace_filament_pos": "bowden",
            "ace_endless_spool_enabled": False,
        },
        instances=instances,
        ace_config={},
        toolchange_in_progress=False,
        # get_status publishes the *effective* endless spool setting, which goes
        # through the resolver rather than the raw variable.
        is_endless_spool_enabled=lambda: False,
    )
    shim.printer = SimpleNamespace(lookup_object=lambda name, default=None: default)
    shim.logger = SimpleNamespace(exception=lambda *a, **k: None)
    shim.tool_to_gate_map = []
    shim.endless_spool_groups = []
    shim._active_tool = -1
    return shim


def _slots_with_empty(index=3):
    slots = [_slot(spool_id=i) for i in range(4)]
    slots[index] = _slot(status="empty", color=(0, 0, 0), material="", spool_id=None)
    return slots


# ---------------------------------------------------------------------------
# material
# ---------------------------------------------------------------------------


class TestEmptySlotMaterial:
    def test_empty_slot_reports_no_material(self):
        """THE BUG: an absent material was reported as PLA."""
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_material"][3] == "", (
            f"T3 has nothing in it, but reports {status['gate_material'][3]!r}"
        )

    def test_empty_slot_does_not_claim_pla(self):
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_material"][3].upper() != "PLA"

    def test_filament_name_follows_the_material(self):
        """gate_filament_name is a copy of gate_material; it must not diverge."""
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_filament_name"][3] == ""
        assert status["gate_filament_name"] == status["gate_material"]

    def test_loaded_slots_keep_their_material(self):
        """The fix must not erase real data."""
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_material"][:3] == ["PLA", "PLA", "PLA"]

    def test_a_real_black_spool_keeps_its_material(self):
        """Black PLA is a real thing and must still be reported as PLA."""
        slots = [_slot(spool_id=i) for i in range(4)]
        slots[3] = _slot(status="ready", color=(0, 0, 0), material="PLA")
        status = _make_shim([_Instance(slots)]).get_status()
        assert status["gate_material"][3] == "PLA", (
            "a genuine black spool must not be mistaken for an empty slot"
        )
        assert status["gate_color"][3] == "#000000"

    @pytest.mark.parametrize("junk", [None, "", "   ", "\t"])
    def test_absent_material_reads_as_absent(self, junk):
        """Whitespace-only must not become a material called '   '."""
        slots = [_slot(spool_id=i) for i in range(4)]
        slots[3] = _slot(status="ready", color=(10, 20, 30), material=junk)
        status = _make_shim([_Instance(slots)]).get_status()
        assert status["gate_material"][3] == "", repr(status["gate_material"][3])

    def test_material_is_not_upper_cased_or_otherwise_rewritten(self):
        """Clients display it verbatim; only emptiness is our business."""
        slots = [_slot(spool_id=i) for i in range(4)]
        slots[3] = _slot(status="ready", material="  PETG-CF  ")
        status = _make_shim([_Instance(slots)]).get_status()
        assert status["gate_material"][3] == "PETG-CF"


# ---------------------------------------------------------------------------
# temperature
# ---------------------------------------------------------------------------


class TestEmptySlotTemperature:
    def test_empty_slot_advertises_no_temperature(self):
        """Mainsail treats gate_temp > 0 as "a spool is here"."""
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_temp"][3] == 0
        assert status["gate_temperature"][3] == 0

    def test_loaded_slots_keep_a_temperature(self):
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert all(t > 0 for t in status["gate_temp"][:3]), status["gate_temp"]


# ---------------------------------------------------------------------------
# status, and how it combines with the other two
# ---------------------------------------------------------------------------


class TestEmptySlotStatus:
    def test_empty_slot_status_is_zero(self):
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_status"][3] == 0

    def test_the_three_fields_agree_about_emptiness(self):
        """Status says empty, and neither colour nor material contradicts it.

        The dashboard decides "unknown slot" from colour + material, so all three
        have to point the same way or the tile renders as a solid black spool.
        """
        status = _make_shim([_Instance(_slots_with_empty())]).get_status()
        assert status["gate_status"][3] == 0
        assert status["gate_material"][3] == ""
        assert status["gate_color"][3] == "#000000", (
            "all-zero RGB is the ACE no-colour sentinel the card keys off"
        )

    def test_a_busy_slot_is_unknown_not_empty(self):
        slots = [_slot(spool_id=i) for i in range(4)]
        slots[3] = _slot(status="feeding", material="PLA")
        status = _make_shim([_Instance(slots)]).get_status()
        assert status["gate_status"][3] == -1, (
            "a slot mid-operation is neither present nor empty"
        )
        assert status["gate_material"][3] == "PLA", (
            "and its material is still real, so it must not be dropped"
        )


# ---------------------------------------------------------------------------
# the error fallback
# ---------------------------------------------------------------------------


class TestErrorFallbackIsHonest:
    def test_a_failed_status_does_not_invent_four_pla_spools(self):
        """This fallback used to claim a fully stocked machine."""
        status = _make_shim([_Instance([], raise_on_status=True)]).get_status()
        assert status["gate_material"] == ["", "", "", ""], status["gate_material"]
        assert status["gate_filament_name"] == ["", "", "", ""]

    def test_a_failed_status_does_not_claim_gates_are_ready(self):
        status = _make_shim([_Instance([], raise_on_status=True)]).get_status()
        assert status["gate_status"] == [-1, -1, -1, -1], (
            "unknown, not ready: claiming ready hides the failure"
        )

    def test_the_fallback_still_provides_every_field_clients_need(self):
        """Honest must not mean incomplete - UIs index these arrays."""
        status = _make_shim([_Instance([], raise_on_status=True)]).get_status()
        for key in ("gate_status", "gate_color", "gate_material",
                    "gate_filament_name", "gate_spool_id", "gate_temp",
                    "gate_temperature", "espooler"):
            assert len(status[key]) == status["num_gates"], key
