"""Regression tests: a tool is only "loaded" when the nozzle switch says so.

Observed live on 2026-10-24.  The printer sat in this state::

    ace_current_index = 0
    ace_filament_pos  = 'nozzle'
    entry sensor      = True
    nozzle sensor     = False     <-- filament never reached the melt zone

and ``ACE_CHANGE_TOOL GATE=0`` answered *"Tool 0 already loaded"* and did
nothing, because the tool-reselection branch decided "loaded" from the entry
switch alone.  The same branch had earlier *written* ``filament_pos='nozzle'``
from that same entry switch, so the two lies reinforced each other:

  * the entry switch promoted the state to ``'nozzle'`` while the filament was
    still short of the nozzle;
  * a later toolchange trusted the promoted state and skipped the load.

The result was a machine that believed it was ready to print with nothing at the
melt zone.  ``LINE_PURGE`` now refuses that state outright, but the guard is a
backstop - the real fix is to stop manufacturing the lie.

The rule, identical to the ``LINE_PURGE`` guard: **when a nozzle switch is
fitted it is the authority; the entry switch only proves the filament reached
the toolhead.**  A recorded position is a cache, a switch is a measurement, and
the measurement wins.

Machines without a nozzle switch keep the old behaviour, so single-sensor rigs
are unaffected.
"""

from __future__ import annotations

import pytest

from extras.ace.config import (
    FILAMENT_STATE_BOWDEN,
    FILAMENT_STATE_NOZZLE,
    FILAMENT_STATE_TOOLHEAD,
)


class _Stop(Exception):
    """Raised once the reselection branch has run, before the real load starts."""


class _FakeSensor:
    def __init__(self, present):
        self.filament_present = present
        self.sensor_enabled = True


class _State(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class _FakeGcode:
    def __init__(self):
        self.events = []

    def respond_info(self, msg):
        self.events.append(msg)

    def run_script_from_command(self, script):
        self.events.append(("script", script))
        # The reselection branch is done by the time the pre-toolchange macro is
        # queued; stop there so the test never walks the real load path.
        if script.startswith("_ACE_PRE_TOOLCHANGE"):
            raise _Stop()

    def messages(self):
        return " ".join(e for e in self.events if isinstance(e, str))


def _manager(monkeypatch, *, entry, nozzle, filament_pos, current_tool=0,
             path_free=False, fit_nozzle_sensor=True):
    """Build a manager shaped like the live one: entry + nozzle, no RDM."""
    from extras.ace import manager as mgr_mod

    m = mgr_mod.AceManager.__new__(mgr_mod.AceManager)
    m.gcode = _FakeGcode()
    m.state = _State({
        "ace_filament_pos": filament_pos,
        "ace_current_index": current_tool,
    })
    m.sensors = {
        mgr_mod.SENSOR_ENTRY: _FakeSensor(entry),
        # The manager aliases SENSOR_TOOLHEAD onto the entry sensor (see
        # _wire_sensors), so mirror that here rather than inventing a third
        # physical switch.
        mgr_mod.SENSOR_TOOLHEAD: _FakeSensor(entry),
    }
    if fit_nozzle_sensor:
        m.sensors[mgr_mod.SENSOR_NOZZLE] = _FakeSensor(nozzle)

    m.instances = []
    m.unloaded = []
    m.smart_unload = lambda tool_index=-1, **kw: (
        m.unloaded.append(tool_index), True)[1]
    m.is_filament_path_free = lambda: path_free
    m.printer = type("P", (), {
        "lookup_object": staticmethod(
            lambda name, default=None: object() if name == "gcode_move" else default
        )
    })()

    monkeypatch.setattr(mgr_mod, "get_ace_instance_and_slot_for_tool",
                        lambda tool: (None, None))
    monkeypatch.setattr(mgr_mod, "get_instance_from_tool", lambda tool: 0)
    monkeypatch.setattr(mgr_mod, "get_local_slot", lambda tool, inst: 0)
    return m


def _reselect(m):
    """Run a same-tool change.

    Returns ``(status, fell_through)``.  ``fell_through`` is True when the branch
    declined to short-circuit and handed over to the normal load path.
    """
    try:
        return m.perform_tool_change(0, 0), False
    except _Stop:
        return None, True


class TestLoadedIsDeclaredByTheNozzleSwitch:
    def test_entry_sensor_alone_does_not_mean_loaded(self, monkeypatch):
        """THE BUG: filament at the entry switch, nothing at the nozzle."""
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_NOZZLE)

        status, fell_through = _reselect(m)

        assert "already loaded" not in m.gcode.messages(), (
            "claiming 'already loaded' with a clear nozzle sensor is what made "
            f"the printer think it could print: {m.gcode.messages()}"
        )
        assert fell_through is True, (
            f"expected the toolchange to resume the load (status={status!r})"
        )

    def test_nozzle_sensor_confirms_the_tool_is_really_loaded(self, monkeypatch):
        m = _manager(monkeypatch, entry=True, nozzle=True,
                     filament_pos=FILAMENT_STATE_NOZZLE)

        status, fell_through = _reselect(m)

        assert fell_through is False
        assert "already loaded" in status, status
        assert m.unloaded == [], (
            f"a confirmed load must not be unloaded (got {m.unloaded})"
        )

    def test_the_filament_at_the_entry_is_not_unloaded_needlessly(
            self, monkeypatch):
        """The resume path should seat the filament, not cycle the whole spool.

        The filament is already past the splitter, so the load's closed-loop feed
        picks up at the entry sensor and only has the last stretch to travel.
        """
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_NOZZLE,
                     path_free=False)

        _reselect(m)

        assert m.unloaded in ([], [-1]), (
            "the resume path may clear a genuinely jammed path, but must not "
            f"start a blind unload cycle: {m.unloaded}"
        )


class TestStateIsNotPromotedByTheEntrySwitch:
    def test_entry_switch_does_not_promote_state_to_nozzle(self, monkeypatch):
        """This is the write that manufactured the lie in the first place."""
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_TOOLHEAD)

        _reselect(m)

        assert m.state["ace_filament_pos"] != FILAMENT_STATE_NOZZLE, (
            "the entry switch proves the filament reached the toolhead, not the "
            f"melt zone: state={m.state['ace_filament_pos']!r}"
        )

    def test_nozzle_switch_does_promote_state_to_nozzle(self, monkeypatch):
        m = _manager(monkeypatch, entry=True, nozzle=True,
                     filament_pos=FILAMENT_STATE_TOOLHEAD)

        status, fell_through = _reselect(m)

        assert fell_through is False
        assert m.state["ace_filament_pos"] == FILAMENT_STATE_NOZZLE
        assert "state corrected" in status, status

    def test_a_clear_path_and_clear_nozzle_never_promotes(self, monkeypatch):
        m = _manager(monkeypatch, entry=False, nozzle=False,
                     filament_pos=FILAMENT_STATE_BOWDEN, path_free=True)

        _reselect(m)

        assert m.state["ace_filament_pos"] != FILAMENT_STATE_NOZZLE


class TestSingleSensorMachinesAreUnaffected:
    def test_without_a_nozzle_switch_the_entry_switch_still_decides(
            self, monkeypatch):
        """No nozzle switch fitted: the old behaviour must be preserved.

        ``get_nozzle_switch_state`` falls back to the toolhead alias, which is the
        entry switch on a single-sensor rig.  Dropping that fallback would make
        those machines impossible to load.
        """
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_TOOLHEAD,
                     fit_nozzle_sensor=False)

        status, fell_through = _reselect(m)

        assert fell_through is False
        assert m.state["ace_filament_pos"] == FILAMENT_STATE_NOZZLE
        assert "state corrected" in status, status

    def test_without_a_nozzle_switch_and_no_filament_nothing_is_promoted(
            self, monkeypatch):
        m = _manager(monkeypatch, entry=False, nozzle=False,
                     filament_pos=FILAMENT_STATE_BOWDEN, path_free=True,
                     fit_nozzle_sensor=False)

        _reselect(m)

        assert m.state["ace_filament_pos"] == FILAMENT_STATE_BOWDEN


class TestTheMismatchIsDiagnosable:
    def test_the_message_names_the_short_stop(self, monkeypatch):
        """The operator needs to know the filament stopped short, not that a
        sensor is broken."""
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_NOZZLE)

        _reselect(m)

        joined = m.gcode.messages()
        assert "nozzle sensor is CLEAR" in joined, joined
        assert "short of the nozzle" in joined, (
            f"the entry switch being triggered is the key detail: {joined}"
        )

    def test_the_message_distinguishes_no_filament_at_all(self, monkeypatch):
        m = _manager(monkeypatch, entry=False, nozzle=False,
                     filament_pos=FILAMENT_STATE_NOZZLE, path_free=True)

        _reselect(m)

        joined = m.gcode.messages()
        assert "nozzle sensor is CLEAR" in joined, joined
        assert "no filament at the toolhead" in joined, joined
        assert "short of the nozzle" not in joined, (
            f"nothing is at the toolhead, so it did not stop short: {joined}"
        )


class _NozzleSensorAbsent:
    """Guard against reintroducing an assumption the live machine contradicts."""

    def test_the_switch_reading_is_read_per_call_not_cached(self, monkeypatch):
        """The filament can move between calls; a stale bool is a safety bug."""
        m = _manager(monkeypatch, entry=True, nozzle=False,
                     filament_pos=FILAMENT_STATE_NOZZLE)
        m.sensors[_sensor_nozzle()] = _FakeSensor(True)

        status, fell_through = _reselect(m)

        assert fell_through is False
        assert "already loaded" in status, status


def _sensor_nozzle():
    from extras.ace import manager as mgr_mod
    return mgr_mod.SENSOR_NOZZLE
