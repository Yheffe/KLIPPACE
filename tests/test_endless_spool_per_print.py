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


# ---------------------------------------------------------------------------
# the status report must not contradict the toggle
# ---------------------------------------------------------------------------


class TestStatusReport:
    """``ACE_ENDLESS_SPOOL_STATUS`` read the raw variable, so with the per-print
    override on it reported "disabled" while a runout would in fact swap. That is
    the exact contradiction that makes an operator distrust the feature."""

    def test_status_reports_the_effective_setting(self, install):
        m = install(saved=False)
        m.set_endless_spool_for_print(True)
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_STATUS(gcode)
        messages = gcode.messages()
        assert "Effective: ON" in messages, messages

    def test_status_distinguishes_saved_from_effective(self, install):
        m = install(saved=False)
        m.set_endless_spool_for_print(True)
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_STATUS(gcode)
        messages = gcode.messages()
        assert "saved off" in messages, messages
        assert "this print on" in messages, messages

    def test_status_says_exact_only(self, install):
        install(saved=True)
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_STATUS(gcode)
        assert "exact" in gcode.messages().lower(), gcode.messages()

    def test_status_does_not_read_the_raw_variable(self):
        import inspect
        from extras.ace import commands as c

        src = inspect.getsource(c.cmd_ACE_ENDLESS_SPOOL_STATUS)
        assert 'state.get("ace_endless_spool_enabled"' not in src, (
            "reading the raw variable here reports 'disabled' while the "
            "per-print override is about to swap a spool"
        )


# ---------------------------------------------------------------------------
# the dry-run matcher
# ---------------------------------------------------------------------------


class _FakeSpool:
    def __init__(self, matches):
        self.matches = matches          # {tool: match}
        self.asked = []

    def find_exact_match(self, tool):
        self.asked.append(tool)
        return self.matches.get(tool, -1)


@pytest.fixture
def with_inventory(monkeypatch):
    """Install a one-ACE inventory (4 slots) plus a fake matcher."""
    from extras.ace import config as cfg

    def _install(slots, matches, *, effective=True, saved=False):
        m = _manager(saved=saved)
        m.set_endless_spool_for_print(effective)
        m.endless_spool = _FakeSpool(matches)
        m.instances = [object()]
        monkeypatch.setattr(cmd_mod, "ace_get_manager", lambda _n: m)

        saved_registry = dict(cfg.ACE_INSTANCES)
        cfg.ACE_INSTANCES.clear()
        inst = SimpleNamespace(inventory=slots)
        cfg.ACE_INSTANCES[0] = inst
        monkeypatch.setattr(cmd_mod, "ACE_INSTANCES", cfg.ACE_INSTANCES)

        monkeypatch.setattr(cmd_mod, "get_instance_from_tool", lambda t: 0 if 0 <= t < 4 else -1)
        monkeypatch.setattr(cmd_mod, "get_local_slot", lambda t, i: t if 0 <= t < 4 else -1)
        monkeypatch.setattr(cmd_mod, "SLOTS_PER_ACE", 4)
        return m, saved_registry

    yield _install
    from extras.ace import config as cfg
    cfg.ACE_INSTANCES.clear()


def _inv(status="ready", material="PLA", color=(0, 0, 0)):
    return {"status": status, "material": material, "color": list(color)}


class TestMatchDryRun:
    def test_reports_a_matching_pair(self, with_inventory):
        slots = [_inv(), _inv(), _inv(), _inv()]
        with_inventory(slots, {0: 3, 3: 0})
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        messages = gcode.messages()
        assert "would swap to T3" in messages, messages

    def test_reports_no_match_and_says_it_would_pause(self, with_inventory):
        slots = [_inv(color=(0, 0, 0)), _inv(color=(255, 0, 0)), _inv(color=(1, 1, 1)), _inv(status="empty")]
        with_inventory(slots, {})
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        messages = gcode.messages()
        assert "NO match" in messages, messages
        assert "would PAUSE" in messages, messages

    def test_skips_slots_that_are_not_ready(self, with_inventory):
        slots = [_inv(), _inv(status="empty"), _inv(), _inv(status="empty")]
        _, _r = with_inventory(slots, {0: 2})
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        messages = gcode.messages()
        assert "not a candidate" in messages, messages

    def test_reports_the_effective_state(self, with_inventory):
        with_inventory([_inv()] * 4, {}, effective=False)
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        messages = gcode.messages()
        assert "is OFF for this print" in messages, messages
        assert "just pause" in messages, messages

    def test_single_tool_argument_limits_the_scan(self, with_inventory):
        m, _r = with_inventory([_inv()] * 4, {2: 0})
        gcode = _Gcode({"TOOL": "2"})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        assert m.endless_spool.asked == [2], m.endless_spool.asked

    def test_out_of_range_tool_is_reported_not_crashed(self, with_inventory):
        with_inventory([_inv()] * 4, {})
        gcode = _Gcode({"TOOL": "9"})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        assert "not present" in gcode.messages(), gcode.messages()

    def test_it_never_moves_anything(self, with_inventory):
        """A dry run that touched hardware would defeat the point."""
        import inspect
        from extras.ace import commands as c

        src = inspect.getsource(c.cmd_ACE_ENDLESS_SPOOL_TEST)
        for forbidden in ("perform_tool_change", "execute_swap", "_feed",
                          "smart_unload", "run_script_from_command"):
            assert forbidden not in src, (
                f"the match test must be read-only, found {forbidden}"
            )

    def test_the_summary_counts_matches(self, with_inventory):
        with_inventory([_inv()] * 4, {0: 1, 1: 0})
        gcode = _Gcode({})
        cmd_mod.cmd_ACE_ENDLESS_SPOOL_TEST(gcode)
        assert "2 of 4" in gcode.messages(), gcode.messages()
