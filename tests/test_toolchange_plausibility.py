"""Regression tests: a failed toolchange must not lead to a double feed.

A toolchange that fails *after* the load has completed leaves a nasty state:
the filament is physically at the nozzle, but ``ace_current_index`` has already
been reset to -1.  The plausibility guard in ``perform_tool_change`` only
reconciled the case where the tracked position said ``'bowden'``, so this state
slipped through untouched.

The next toolchange then called ``_feed_filament_into_toolhead``, which runs
with ``check_pre_condition=False`` and therefore skips its own
"Cannot feed, filament in nozzle or toolhead" guard, feeding a full load length
into an already-loaded hot nozzle.

Observed live on 2026-10-04: ``ACE_ON_PRINT_START`` completed the load, then
aborted at the blobifier purge with "QGL not applied!", leaving
``ace_current_index=-1`` with ``entry/nozzle sensors True``.
"""

from __future__ import annotations

import pytest

from extras.ace.config import (
    FILAMENT_STATE_BOWDEN,
    FILAMENT_STATE_NOZZLE,
    FILAMENT_STATE_SPLITTER,
    FILAMENT_STATE_TOOLHEAD,
)
from extras.ace.manager import filament_present_but_unaccounted


class TestFilamentPresentButUnaccounted:
    """Truth table for the predicate, exercised with no sensor ambiguity."""

    # (toolhead, rdm, filament_pos, current_tool, expected)
    CASES = [
        # No sensor sees filament -> never an inconsistency, whatever the state.
        (False, False, FILAMENT_STATE_BOWDEN, -1, False),
        (False, False, FILAMENT_STATE_NOZZLE, 2, False),
        (False, False, FILAMENT_STATE_NOZZLE, -1, False),
        (False, False, FILAMENT_STATE_SPLITTER, 0, False),

        # THE BUG: filament present, no tool recorded -> must be reconciled.
        (True,  False, FILAMENT_STATE_NOZZLE,   -1, True),
        (False, True,  FILAMENT_STATE_NOZZLE,   -1, True),
        (True,  False, FILAMENT_STATE_TOOLHEAD, -1, True),
        (False, True,  FILAMENT_STATE_SPLITTER, -1, True),

        # Pre-existing behaviour: sensor present but state claims 'bowden'.
        (True,  False, FILAMENT_STATE_BOWDEN, 2,  True),
        (True,  False, FILAMENT_STATE_BOWDEN, -1, True),

        # THE NORMAL CASE: a tool is recorded and it is where it should be.
        # This must never be treated as an inconsistency, or every toolchange
        # would unload the filament and then have nothing to swap.
        (True,  False, FILAMENT_STATE_NOZZLE,   2, False),
        (True,  False, FILAMENT_STATE_TOOLHEAD, 3, False),
        (False, True,  FILAMENT_STATE_SPLITTER, 1, False),
    ]

    @pytest.mark.parametrize("toolhead,rdm,pos,tool,expected", CASES)
    def test_truth_table(self, toolhead, rdm, pos, tool, expected):
        assert filament_present_but_unaccounted(toolhead, rdm, pos, tool) is expected

    def test_returns_a_bool_not_a_truthy_value(self):
        """The result is compared with `is True/False`, so keep it a real bool."""
        result = filament_present_but_unaccounted(True, False, FILAMENT_STATE_NOZZLE, -1)
        assert result is True

    @pytest.mark.parametrize("current_tool", [-1, 0, 1, 7])
    def test_clear_sensors_always_false(self, current_tool):
        for pos in (FILAMENT_STATE_BOWDEN, FILAMENT_STATE_SPLITTER,
                    FILAMENT_STATE_TOOLHEAD, FILAMENT_STATE_NOZZLE):
            assert filament_present_but_unaccounted(False, False, pos, current_tool) is False


class _FakeGcode:
    def __init__(self):
        self.events = []

    def respond_info(self, msg):
        self.events.append(msg)

    def run_script_from_command(self, script):
        self.events.append(("script", script))


class TestPerformToolChangeGuard:
    """The guard must fire for the bug case and stay out of the way otherwise."""

    class _Stop(Exception):
        """Raised once the guard has run, to keep the test off the load path."""

    @classmethod
    def _manager(cls, monkeypatch, toolhead_sensor, rdm_sensor,
                 filament_pos, current_tool):
        from extras.ace import manager as mgr_mod

        class _State(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        class _GcodeMove:
            pass

        calls = []

        m = mgr_mod.AceManager.__new__(mgr_mod.AceManager)
        m.gcode = _FakeGcode()
        m.state = _State({"ace_filament_pos": filament_pos,
                          "ace_current_index": current_tool})
        m.get_switch_state = lambda sensor: (
            toolhead_sensor if sensor == mgr_mod.SENSOR_TOOLHEAD else rdm_sensor
        )
        m.has_rdm_sensor = lambda: True
        m.smart_unload = lambda tool_index=-1, **kw: (calls.append(tool_index), True)[1]

        # perform_tool_change looks these up before the guard runs.
        m.printer = type("P", (), {
            "lookup_object": staticmethod(
                lambda name, default=None: _GcodeMove() if name == "gcode_move" else default
            )
        })()

        # The guard is the last thing we care about; stop just after it.
        def _stop(*a, **kw):
            raise cls._Stop()

        monkeypatch.setattr(mgr_mod, "get_ace_instance_and_slot_for_tool", _stop)
        return m, calls

    def test_bug_case_unloads_before_feeding(self, monkeypatch):
        """filament at nozzle + no tool recorded -> smart_unload(-1) to identify."""
        m, calls = self._manager(monkeypatch, True, False, FILAMENT_STATE_NOZZLE, -1)

        with pytest.raises(self._Stop):
            m.perform_tool_change(-1, 2)

        assert calls == [-1], (
            f"the guard must cycle slots to identify the loaded tool (got {calls})"
        )

    def test_normal_loaded_tool_is_not_unloaded_by_the_guard(self, monkeypatch):
        """A recorded tool sitting at the nozzle is a valid state, not a mismatch."""
        m, calls = self._manager(monkeypatch, True, False, FILAMENT_STATE_NOZZLE, 2)

        with pytest.raises(self._Stop):
            m.perform_tool_change(2, 3)

        assert calls == [], (
            f"a loaded, accounted-for tool must not be unloaded by the guard (got {calls})"
        )

    def test_bowden_mismatch_still_reconciles(self, monkeypatch):
        """Pre-existing behaviour must be preserved."""
        m, calls = self._manager(monkeypatch, True, False, FILAMENT_STATE_BOWDEN, 2)

        with pytest.raises(self._Stop):
            m.perform_tool_change(2, 3)

        assert calls == [2], f"expected an unload of T2 (got {calls})"

    def test_clear_sensors_do_not_trigger_a_unload(self, monkeypatch):
        m, calls = self._manager(monkeypatch, False, False, FILAMENT_STATE_NOZZLE, -1)

        with pytest.raises(self._Stop):
            m.perform_tool_change(-1, 2)

        assert calls == [], f"nothing present, nothing to clear (got {calls})"

    def test_guard_message_names_the_real_reason(self, monkeypatch):
        m, calls = self._manager(monkeypatch, True, False, FILAMENT_STATE_NOZZLE, -1)

        with pytest.raises(self._Stop):
            m.perform_tool_change(-1, 2)

        joined = " ".join(m.gcode.events)
        assert "no tool is recorded" in joined, joined
        assert "state='nozzle'" not in joined, (
            "'nozzle' is the correct position for a loaded tool; naming it as the "
            f"problem would mislead: {joined}"
        )
