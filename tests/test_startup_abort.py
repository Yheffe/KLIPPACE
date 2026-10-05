"""Regression tests: a failed initial tool load must abort the print.

`cmd_ACE_CHANGE_TOOL` turned the heater off and raised on a failed *startup*
load, but `cmd_ACE_CHANGE_TOOL_WRAPPER` caught everything with a blanket
``except Exception`` and merely logged it.  The raise died there, so
`ACE_ON_PRINT_START` returned normally and `PRINT_START` carried on to the
nozzle wipe and the adaptive line purge — extruding both with nothing loaded.

The log said "cancel print" while the print was not cancelled.  Observed live on
2026-10-04 in pumpkin_PLA_7h45m.gcode:

    ACE: Initial toolchange failed, cancel print and switching extruder heater off
    ACE_CHANGE_TOOL error: Tool change to TNone failed during startup: ...
    Adaptive Purge: (168.7, 42.2) -> (198.7, 42.2), Extruding 20.0mm   <- purged anyway

Note the ``TNone`` too: the message interpolated ``tool_index``, which is unset
when the caller uses ``GATE=`` — and ``ACE_ON_PRINT_START`` always uses ``GATE=``.
"""

from __future__ import annotations

import pytest

from extras.ace import commands as C
from extras.ace.commands import StartupToolchangeAbort


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class _FakeGcode:
    def __init__(self):
        self.responses = []
        self.scripts = []

    def respond_info(self, msg):
        self.responses.append(msg)

    def run_script_from_command(self, script):
        self.scripts.append(script)


class _FakeMmu:
    def get_tool_for_gate(self, gate):
        return gate

    def get_gate_for_tool(self, tool):
        return tool


class _FakeKinematics:
    def get_status(self, _t):
        return {"homed_axes": "xyz"}


class _FakeToolhead:
    def get_kinematics(self):
        return _FakeKinematics()


class _FakeReactor:
    def monotonic(self):
        return 0.0


class _FakePrintStats:
    def __init__(self, state):
        self._state = state

    def get_status(self, _t):
        return {"state": self._state}


class _AceState:
    def __init__(self, startup_toolchange):
        self.variables = {"startup_toolchange": startup_toolchange}


class _FakePrinter:
    def __init__(self, print_state, startup_toolchange, gcode):
        self._print_state = print_state
        self._startup = startup_toolchange
        self._gcode = gcode

    def get_reactor(self):
        return _FakeReactor()

    def lookup_object(self, name, default=None):
        if name == "mmu":
            return _FakeMmu()
        if name == "toolhead":
            return _FakeToolhead()
        if name == "gcode":
            return self._gcode
        if name == "print_stats":
            return _FakePrintStats(self._print_state)
        if name == "gcode_macro _ACE_STATE":
            return _AceState(self._startup)
        return default


class _FakeState:
    def __init__(self):
        self.d = {"ace_current_index": 2, "ace_filament_pos": "nozzle"}

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value


class _FakeManager:
    def __init__(self, fail="feed failed"):
        self.state = _FakeState()
        self.toolchange_purge_length = 50.0
        self._fail = fail

    def get_ace_global_enabled(self):
        return True

    def perform_tool_change(self, current_tool, target_gate):
        raise RuntimeError(self._fail)

    def is_filament_path_free(self):
        return True


class _Gcmd:
    """Minimal BaseGCodeCommand stand-in."""

    def __init__(self, params, responses, scripts):
        self._params = params
        self._responses = responses
        self._scripts = scripts

    def get_int(self, name, default=None):
        v = self._params.get(name)
        return default if v is None else int(v)

    def get_float(self, name, default=None):
        v = self._params.get(name)
        return default if v is None else float(v)

    def get(self, name, default=None):
        return self._params.get(name, default)

    def get_command_parameters(self):
        return dict(self._params)

    def respond_info(self, msg):
        self._responses.append(msg)


def _drive(monkeypatch, params, print_state="printing",
           startup_toolchange=1, fail="feed failed"):
    """Drive the real cmd_ACE_CHANGE_TOOL with fakes.

    Returns ``(gcode, manager, exc)`` where ``exc`` is whatever it raised, or
    None.  Returning the exception rather than asserting inside keeps the tests
    free to inspect side effects that happen *before* the raise.
    """
    gcode = _FakeGcode()
    manager = _FakeManager(fail=fail)
    printer = _FakePrinter(print_state, startup_toolchange, gcode)
    monkeypatch.setattr(C, "get_printer", lambda: printer)
    gcmd = _Gcmd(params, gcode.responses, gcode.scripts)
    exc = None
    try:
        C.cmd_ACE_CHANGE_TOOL(manager, gcmd, params.get("TOOL"),
                              gate_index=params.get("GATE"))
    except Exception as e:      # noqa: BLE001 - we are asserting on it
        exc = e
    return gcode, manager, exc


# --------------------------------------------------------------------------
# the abort
# --------------------------------------------------------------------------

class TestStartupAbort:
    def test_failed_initial_load_raises_the_abort(self, monkeypatch):
        _, _, exc = _drive(monkeypatch, {"GATE": 0}, startup_toolchange=1)
        assert isinstance(exc, StartupToolchangeAbort), exc
        assert "failed during startup" in str(exc)

    def test_heater_is_turned_off_before_aborting(self, monkeypatch):
        gcode, _, exc = _drive(monkeypatch, {"GATE": 0}, startup_toolchange=1)
        assert isinstance(exc, StartupToolchangeAbort), exc
        assert "M104 S0" in gcode.scripts, gcode.scripts
        assert any("cancel print" in r for r in gcode.responses), gcode.responses

    def test_message_names_the_gate_not_none(self, monkeypatch):
        """`ACE_ON_PRINT_START` always calls with GATE=, so tool_index is None."""
        _, _, exc = _drive(monkeypatch, {"GATE": 3}, startup_toolchange=1)
        text = str(exc)
        assert "None" not in text, f"message leaks the unset tool_index: {text!r}"
        assert "T3" in text and "Gate 3" in text, text

    def test_mid_print_failure_still_pauses_instead_of_aborting(self, monkeypatch):
        """Only a failed *initial* load aborts; a mid-print one offers recovery."""
        gcode, _, exc = _drive(
            monkeypatch, {"TOOL": 3}, print_state="printing", startup_toolchange=0
        )
        assert exc is None, f"mid-print failure must not raise: {exc!r}"
        assert "PAUSE" in gcode.scripts, gcode.scripts
        assert not any("M104 S0" in s for s in gcode.scripts), gcode.scripts

    def test_state_is_not_set_to_the_target_after_failure(self, monkeypatch):
        _, manager, exc = _drive(monkeypatch, {"GATE": 3}, startup_toolchange=1)
        assert isinstance(exc, StartupToolchangeAbort), exc
        assert manager.state.get("ace_current_index") != 3, (
            "a failed load must never mark the target gate as loaded"
        )


# --------------------------------------------------------------------------
# the wrapper
# --------------------------------------------------------------------------

class TestWrapper:
    def test_abort_propagates_through_the_wrapper(self, monkeypatch):
        monkeypatch.setattr(C, "ace_get_manager", lambda i: object())

        def boom(manager, gcmd, tool_index, gate_index=None):
            raise StartupToolchangeAbort("tool change to T0 (Gate 0) failed during startup")

        monkeypatch.setattr(C, "cmd_ACE_CHANGE_TOOL", boom)
        responses = []
        gcmd = _Gcmd({"GATE": 0}, responses, [])
        with pytest.raises(StartupToolchangeAbort):
            C.cmd_ACE_CHANGE_TOOL_WRAPPER(gcmd)

    def test_other_exceptions_are_still_swallowed(self, monkeypatch):
        """Unrelated failures must not start aborting prints."""
        monkeypatch.setattr(C, "ace_get_manager", lambda i: object())

        def boom(manager, gcmd, tool_index, gate_index=None):
            raise RuntimeError("serial hiccup")

        monkeypatch.setattr(C, "cmd_ACE_CHANGE_TOOL", boom)
        responses = []
        gcmd = _Gcmd({"GATE": 0}, responses, [])
        C.cmd_ACE_CHANGE_TOOL_WRAPPER(gcmd)   # must not raise
        assert any("ACE_CHANGE_TOOL error" in r for r in responses), responses
