"""Regression tests: a post-load failure must not discard a seated tool.

Observed live on 2026-10-24, immediately after fixing the "already loaded" lie.
``ACE_CHANGE_TOOL GATE=0`` loaded T0 correctly - the log shows the entry sensor
triggering, then ``Nozzle sensor triggered after 14.0mm coordinated feed``, then
feed assist enabled and 50mm primed through the nozzle.

Then the *post-load* Blobifier purge raised ``BLOBIFIER: QGL not applied``.  The
cleanup handler treated any exception as a load failure and reset
``ace_current_index`` to -1, reporting::

    ACE: State updated - no active tool loaded (failed tool change to T0)

So the machine recorded "nothing loaded" with filament demonstrably at the melt
zone.  ``mmu.tool`` then reported -1 and the tool had to be reloaded by hand for
no reason.

The mistake is treating "something went wrong" as "the load failed".  A failure
that happens after the filament is seated is a purge/move/blobifier problem, and
the nozzle switch is the authority on whether the filament arrived - it cannot
trigger unless filament physically reached the melt zone.

These tests pin down that a nozzle-confirmed tool survives a post-load error,
while a genuinely failed load is still recorded as no tool.
"""

from __future__ import annotations

import pytest

from extras.ace.config import FILAMENT_STATE_BOWDEN, FILAMENT_STATE_NOZZLE
from extras.ace import commands as cmd_mod


class _Stop(Exception):
    """Raised from the load itself to simulate a failure at a chosen point."""


class _FakeGcode:
    def __init__(self):
        self.events = []
        self.scripts = []

    def respond_info(self, msg):
        self.events.append(msg)

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def messages(self):
        return " | ".join(self.events)


class _State(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class _Manager:
    """Minimal stand-in exposing what the failure handler actually calls."""

    def __init__(self, *, nozzle_present_sensor, filament_pos, current_tool,
                 has_nozzle_sensor):
        self.state = _State({
            "ace_filament_pos": filament_pos,
            "ace_current_index": current_tool,
        })
        self._nozzle = nozzle_present_sensor
        self._has_nozzle = has_nozzle_sensor

    def has_nozzle_sensor(self):
        return self._has_nozzle

    def get_ace_global_enabled(self):
        # Without this the command returns before it does anything, and the test
        # would pass without ever reaching the failure handler.
        return True

    def get_switch_state(self, sensor):
        if sensor == "nozzle_sensor":
            return self._nozzle
        return False

    def is_filament_path_free(self):
        # Path not free whenever the nozzle switch sees filament.
        return not self._nozzle


def _run_failing_toolchange(monkeypatch, *, exception_from, **kwargs):
    """Drive cmd_ACE_CHANGE_TOOL into its failure handler.

    ``exception_from`` is either ``"load"`` (fail before the filament is seated)
    or ``"purge"`` (fail after - the live Blobifier case).
    """
    manager = _Manager(**kwargs)
    gcode = _FakeGcode()

    if exception_from == "load":
        def _perform(current_tool, target_tool, is_endless_spool=False):
            raise Exception("BLOBIFIER: QGL not applied! Run QUAD_GANTRY_LEVEL first.")
    else:
        def _perform(current_tool, target_tool, is_endless_spool=False):
            # The load completed: state now says nozzle.
            manager.state.set("ace_filament_pos", FILAMENT_STATE_NOZZLE)
            raise Exception("BLOBIFIER: QGL not applied! Run QUAD_GANTRY_LEVEL first.")

    manager.perform_tool_change = _perform

    class _Mmu:
        def __init__(self):
            self.active = "unchanged"

        def set_active_tool(self, tool):
            self.active = tool

        def get_tool_for_gate(self, gate):
            return gate

    mmu = _Mmu()

    class _Printer:
        def lookup_object(self, name, default=None):
            if name == "gcode":
                return gcode
            if name == "mmu":
                return mmu
            if name == "gcode_macro _ACE_STATE":
                return None
            return default

        def get_reactor(self):
            class _R:
                def monotonic(self):
                    return 0.0
            return _R()

    class _Gcmd:
        def get_float(self, name, default=None):
            return default

        def get(self, name, default=None):
            return default

        def respond_info(self, msg):
            gcode.events.append(msg)

    monkeypatch.setattr(cmd_mod, "get_printer", lambda: _Printer())
    # Avoid the startup-abort plumbing and homing checks.
    monkeypatch.setattr(cmd_mod, "StartupToolchangeAbort", _Stop)

    class _NoopGcode:
        pass

    manager.printer = _Printer()
    manager.gcode = gcode
    manager.toolchange_purge_length = 0

    with pytest.raises((_Stop, Exception)):
        cmd_mod.cmd_ACE_CHANGE_TOOL(manager, _Gcmd(), None, gate_index=0)

    assert gcode.events, (
        "the command never reported anything, so it bailed out before reaching "
        "the failure handler and the assertions below would be meaningless"
    )

    return manager, gcode, mmu


class TestTheNozzleSwitchOutvotesAPostLoadError:
    def test_a_seated_tool_survives_a_purge_error(self, monkeypatch):
        """THE BUG: filament at the nozzle, purge raised, tool was forgotten."""
        manager, gcode, mmu = _run_failing_toolchange(
            monkeypatch,
            exception_from="purge",
            nozzle_present_sensor=True,
            filament_pos=FILAMENT_STATE_NOZZLE,
            current_tool=0,
            has_nozzle_sensor=True,
        )

        assert manager.state.get("ace_current_index") == 0, (
            "the nozzle sensor proves the load succeeded; forgetting the tool "
            f"leaves mmu.tool wrong: {manager.state.get('ace_current_index')}"
        )

    def test_the_message_says_the_load_was_not_the_problem(self, monkeypatch):
        manager, gcode, _ = _run_failing_toolchange(
            monkeypatch,
            exception_from="purge",
            nozzle_present_sensor=True,
            filament_pos=FILAMENT_STATE_NOZZLE,
            current_tool=0,
            has_nozzle_sensor=True,
        )

        joined = gcode.messages()
        assert "nozzle sensor" in joined, joined
        assert "no active tool loaded" not in joined, (
            f"the tool *is* loaded - saying otherwise is the same class of lie: {joined}"
        )

    def test_a_genuinely_failed_load_still_records_no_tool(self, monkeypatch):
        """A failure before the filament is seated must still clear the tool."""
        manager, gcode, _ = _run_failing_toolchange(
            monkeypatch,
            exception_from="load",
            nozzle_present_sensor=False,
            filament_pos=FILAMENT_STATE_BOWDEN,
            current_tool=0,
            has_nozzle_sensor=True,
        )

        assert manager.state.get("ace_current_index") == -1
        assert "no active tool loaded" in gcode.messages()

    def test_an_entry_only_machine_does_not_get_the_benefit_of_the_doubt(
            self, monkeypatch):
        """Without a nozzle switch there is no proof the filament arrived.

        The entry switch reaching the toolhead is not enough to claim a
        completed load, so the old (conservative) behaviour is kept.
        """
        manager, gcode, _ = _run_failing_toolchange(
            monkeypatch,
            exception_from="load",
            nozzle_present_sensor=True,   # entry switch triggered...
            filament_pos=FILAMENT_STATE_BOWDEN,
            current_tool=0,
            has_nozzle_sensor=False,      # ...but no nozzle switch to confirm
        )

        assert manager.state.get("ace_current_index") == -1
        assert "no active tool loaded" in gcode.messages()
