"""Per-print endless spool override (the tool mapper toggle).

The toggle lets one print opt in or out without rewriting the machine's saved
preference. That promise only holds if three things are true, and each of them
fails silently if it regresses:

1. **Resolution.** Every decision must read the override first. If the runout
   handler keeps reading the state variable directly, the button appears to work
   and does nothing at the moment it matters - mid-print, at a runout.
2. **Non-persistence.** The override must not reach disk. ``PersistentState.set()``
   marks a variable dirty and the next ``flush()`` writes it out, so using it
   would quietly turn a one-off choice into a permanent setting. This is why the
   override is a plain Python attribute.
3. **Reset at print end.** Without it the "this print only" label is a lie, and
   the next print inherits a decision nobody made for it.

These tests pin all three, plus the command that drives them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from extras.ace import commands as cmd_mod


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


class _State(dict):
    def __init__(self, initial=None):
        super().__init__(initial or {})
        self.saved = []
        self.dirty = set()

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value
        self.dirty.add(key)      # mirrors PersistentState.set

    def set_and_save(self, key, value):
        self[key] = value
        self.saved.append((key, value))

    def flush(self):
        self.dirty.clear()


def _manager(saved=False, override=None):
    """An AceManager-shaped object with only the endless-spool surface."""
    from extras.ace.manager import AceManager

    m = object.__new__(AceManager)
    m.state = _State({"ace_endless_spool_enabled": saved})
    m.endless_spool_print_override = override
    return m


class TestResolution:
    def test_falls_back_to_the_saved_setting(self):
        assert _manager(saved=True).is_endless_spool_enabled() is True
        assert _manager(saved=False).is_endless_spool_enabled() is False

    def test_override_on_wins_over_saved_off(self):
        """THE POINT: opt one print in without changing the standing setting."""
        assert _manager(saved=False, override=True).is_endless_spool_enabled() is True

    def test_override_off_wins_over_saved_on(self):
        assert _manager(saved=True, override=False).is_endless_spool_enabled() is False

    def test_clearing_the_override_restores_the_saved_setting(self):
        m = _manager(saved=True, override=False)
        m.clear_endless_spool_print_override()
        assert m.endless_spool_print_override is None
        assert m.is_endless_spool_enabled() is True

    def test_override_none_is_not_the_same_as_false(self):
        """``None`` means "no opinion"; ``False`` means "force off"."""
        assert _manager(saved=True, override=None).is_endless_spool_enabled() is True
        assert _manager(saved=True, override=False).is_endless_spool_enabled() is False

    def test_saved_setting_is_preserved_when_overriding(self):
        m = _manager(saved=True)
        m.set_endless_spool_for_print(False)
        assert m.is_endless_spool_enabled() is False
        assert m.get_saved_endless_spool_enabled() is True


class TestNonPersistence:
    def test_the_override_never_reaches_state(self):
        """If it lived in state, flush() would write it to disk."""
        m = _manager(saved=False)
        m.set_endless_spool_for_print(True)
        assert "ace_endless_spool_print_override" not in m.state
        assert m.state.dirty == set(), (
            f"nothing should be marked dirty by a per-print choice: {m.state.dirty}"
        )

    def test_flush_does_not_persist_the_override(self, monkeypatch):
        m = _manager(saved=False)
        m.set_endless_spool_for_print(True)
        m.state.flush()
        # A restart is simulated by dropping the in-memory attribute.
        m.endless_spool_print_override = None
        assert m.is_endless_spool_enabled() is False, (
            "the per-print choice survived as if it were saved"
        )

    def test_the_override_is_initialised_to_none(self):
        """A fresh manager must not start with a stale opinion."""
        import inspect
        from extras.ace import manager as mgr_mod

        src = inspect.getsource(mgr_mod.AceManager.__init__)
        assert "endless_spool_print_override = None" in src, (
            "the attribute must be initialised, or the first read raises"
        )


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------


class _Gcode:
    def __init__(self, params=None):
        self._params = params or {}
        self.events = []

    def get(self, name, default=None):
        return self._params.get(name, default)

    def get_int(self, name, default=None):
        value = self._params.get(name, default)
        return int(value) if value is not None else default

    def respond_info(self, msg):
        self.events.append(str(msg))

    def messages(self):
        return " | ".join(self.events)


@pytest.fixture
def install(monkeypatch):
    def _install(saved=False):
        m = _manager(saved=saved)
        monkeypatch.setattr(cmd_mod, "ace_get_manager", lambda _n: m)
        return m

    return _install


class TestCommand:
    def test_enable_sets_the_override_not_the_saved_setting(self, install):
        m = install(saved=False)
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(_Gcode({"ENABLE": "1"}))
        assert m.endless_spool_print_override is True
        assert m.state.saved == [], "the saved preference must not be rewritten"
        assert m.get_saved_endless_spool_enabled() is False

    def test_disable_sets_the_override(self, install):
        m = install(saved=True)
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(_Gcode({"ENABLE": "0"}))
        assert m.endless_spool_print_override is False
        assert m.is_endless_spool_enabled() is False
        assert m.get_saved_endless_spool_enabled() is True

    def test_clear_drops_the_override(self, install):
        m = install(saved=True)
        m.set_endless_spool_for_print(False)
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(_Gcode({"CLEAR": "1"}))
        assert m.endless_spool_print_override is None
        assert m.is_endless_spool_enabled() is True

    def test_clear_on_a_clean_manager_is_a_no_op(self, install):
        """PRINT_END calls this unconditionally, so it must never raise."""
        m = install(saved=False)
        gcode = _Gcode({"CLEAR": "1"})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(gcode)
        assert m.endless_spool_print_override is None
        assert "cleared" in gcode.messages().lower()

    @pytest.mark.parametrize("enable", ["1", "0"])
    def test_the_message_says_the_saved_setting_is_unchanged(self, install, enable):
        install(saved=True)
        gcode = _Gcode({"ENABLE": enable})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(gcode)
        assert "for this print only" in gcode.messages(), gcode.messages()
        assert "saved setting unchanged" in gcode.messages(), gcode.messages()

    def test_no_arguments_reports_state_without_changing_it(self, install):
        m = install(saved=True)
        m.set_endless_spool_for_print(False)
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(gcode)
        assert m.endless_spool_print_override is False, "report must not mutate"
        messages = gcode.messages()
        assert "effective=off" in messages, messages
        assert "saved=on" in messages, messages
        assert "override=False" in messages, messages

    def test_an_error_is_reported_not_raised(self, install, monkeypatch):
        monkeypatch.setattr(
            cmd_mod, "ace_get_manager",
            lambda _n: (_ for _ in ()).throw(RuntimeError("no manager")),
        )
        gcode = _Gcode({"ENABLE": "1"})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_FOR_PRINT(gcode)   # must not raise
        assert "error" in gcode.messages().lower(), gcode.messages()

    def test_the_command_is_registered(self):
        names = {entry[0] for entry in cmd_mod.ACE_COMMANDS}
        assert "ACE_ENDLESS_SPOOL_FOR_PRINT" in names


# ---------------------------------------------------------------------------
# the decision site actually uses the resolver
# ---------------------------------------------------------------------------


class TestRunoutMonitorHonoursTheOverride:
    """The whole feature is worthless if the runout handler reads state directly."""

    def test_runout_monitor_calls_the_resolver(self):
        import inspect
        from extras.ace import runout_monitor as rm_mod

        src = inspect.getsource(rm_mod.RunoutMonitor._handle_runout_detected)
        assert "is_endless_spool_enabled()" in src, (
            "the runout handler must resolve the override, not read "
            "ace_endless_spool_enabled directly - otherwise the tool mapper "
            "toggle looks like it works and never fires"
        )
        assert 'state.get("ace_endless_spool_enabled"' not in src

    def test_the_shim_publishes_the_effective_value(self):
        """The card's toggle reflects this; the saved value would show a stale state."""
        import inspect
        from extras.ace import mmu_shim as shim_mod

        src = inspect.getsource(shim_mod.MmuShim.get_status)
        assert "is_endless_spool_enabled()" in src, (
            "mmu.endless_spool must report the effective setting"
        )


# ---------------------------------------------------------------------------
# PRINT_END hygiene
# ---------------------------------------------------------------------------


class TestPrintEndClearsIt:
    def test_print_end_clears_the_override(self):
        """Without this, 'this print only' is untrue."""
        from pathlib import Path

        cfg = (Path(__file__).resolve().parent.parent / "VORON" / "printer.cfg").read_text()
        start = cfg.index("[gcode_macro PRINT_END]")
        end = cfg.index("[gcode_macro", start + 10)
        body = cfg[start:end]
        assert "ACE_ENDLESS_SPOOL_FOR_PRINT CLEAR=1" in body, (
            "PRINT_END must clear the per-print override, or it leaks into the "
            "next print"
        )

    def test_the_clear_is_ungated(self):
        """It has to run even when the print failed early; the command is a no-op
        when nothing is set, so guarding it only creates a way to miss it."""
        from pathlib import Path

        cfg = (Path(__file__).resolve().parent.parent / "VORON" / "printer.cfg").read_text()
        start = cfg.index("[gcode_macro PRINT_END]")
        end = cfg.index("[gcode_macro", start + 10)
        lines = cfg[start:end].splitlines()
        idx = next(i for i, l in enumerate(lines)
                   if "ACE_ENDLESS_SPOOL_FOR_PRINT CLEAR=1" in l)
        # Nothing but a comment or blank line may sit between it and column 4.
        assert lines[idx].startswith("    ACE_ENDLESS_SPOOL_FOR_PRINT"), (
            f"the clear must be a bare statement, found: {lines[idx]!r}"
        )
