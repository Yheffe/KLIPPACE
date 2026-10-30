"""Endless spool commands: exact matching is the only mode that can be set.

The matching logic only honours exact matches, but that is not sufficient on its
own. Two other doors lead to the same place:

  * ``ACE_SET_ENDLESS_SPOOL_MODE`` could still accept ``material`` or ``next``
    and store them. The matcher would ignore them, but the UI would then display
    a mode that is not in effect, and an operator would reasonably believe a
    colour change was allowed.
  * A ``material`` or ``next`` value left in persistent state by an older
    install must not be resurrected by an upgrade.

Both are covered here. The refusal must also be *loud*: silently accepting the
request and doing something else is the failure this file exists to prevent.
"""

from __future__ import annotations

import re

import pytest

from extras.ace import commands as cmd_mod


class _Gcode:
    def __init__(self, params=None):
        self._params = params or {}
        self.events = []

    def get(self, name, default=None):
        return self._params.get(name, default)

    def get_int(self, name, default=None):
        value = self._params.get(name, default)
        return int(value) if value is not None else default

    def get_float(self, name, default=None):
        return self._params.get(name, default)

    def respond_info(self, msg):
        self.events.append(str(msg))

    def messages(self):
        return " | ".join(self.events)


class _State(dict):
    def __init__(self, initial=None):
        super().__init__(initial or {})
        self.saved = []

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value

    def set_and_save(self, key, value):
        self[key] = value
        self.saved.append((key, value))


class _Manager:
    def __init__(self, initial=None):
        self.state = _State(initial)


@pytest.fixture
def patch_manager(monkeypatch):
    """Point ace_get_manager at a controllable fake."""

    def _install(initial=None):
        manager = _Manager(initial)
        monkeypatch.setattr(cmd_mod, "ace_get_manager", lambda _n: manager)
        return manager

    return _install


# ---------------------------------------------------------------------------
# SET_ENDLESS_SPOOL_MODE
# ---------------------------------------------------------------------------


class TestSettingTheMode:
    def test_exact_is_accepted(self, patch_manager):
        manager = patch_manager()
        gcode = _Gcode({"MODE": "exact"})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert manager.state["ace_endless_spool_match_mode"] == "exact"
        assert "EXACT" in gcode.messages(), gcode.messages()

    @pytest.mark.parametrize("mode", ["material", "next", "MATERIAL", "Next", "first"])
    def test_the_former_modes_are_refused(self, patch_manager, mode):
        manager = patch_manager()
        gcode = _Gcode({"MODE": mode})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert manager.state.get("ace_endless_spool_match_mode") is None, (
            f"MODE={mode} must not be stored: {dict(manager.state)}"
        )
        assert manager.state.saved == [], (
            f"a refused mode must not be persisted: {manager.state.saved}"
        )

    @pytest.mark.parametrize("mode", ["material", "next"])
    def test_the_refusal_says_what_is_supported(self, patch_manager, mode):
        patch_manager()
        gcode = _Gcode({"MODE": mode})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        messages = gcode.messages()
        assert "not supported" in messages, messages
        assert "exact" in messages.lower(), (
            f"the operator needs to know what to use instead: {messages}"
        )
        assert "same material" in messages.lower(), (
            f"and what 'exact' means: {messages}"
        )

    def test_the_refusal_says_nothing_changed(self, patch_manager):
        patch_manager()
        gcode = _Gcode({"MODE": "next"})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert "Nothing was changed" in gcode.messages(), (
            f"otherwise the operator cannot tell whether it took effect: "
            f"{gcode.messages()}"
        )

    def test_a_refused_mode_does_not_clobber_a_previous_one(self, patch_manager):
        manager = patch_manager({"ace_endless_spool_match_mode": "exact"})
        gcode = _Gcode({"MODE": "next"})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert manager.state["ace_endless_spool_match_mode"] == "exact"
        assert manager.state.saved == []

    def test_setting_exact_repairs_a_stale_value(self, patch_manager):
        """An install upgrading from the two-mode era gets actively corrected."""
        manager = patch_manager({"ace_endless_spool_match_mode": "next"})
        gcode = _Gcode({"MODE": "exact"})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert manager.state["ace_endless_spool_match_mode"] == "exact"
        assert ("ace_endless_spool_match_mode", "exact") in manager.state.saved

    def test_no_mode_argument_defaults_to_exact(self, patch_manager):
        manager = patch_manager()
        gcode = _Gcode({})

        cmd_mod.cmd_ACE_SET_ENDLESS_SPOOL_MODE(gcode)

        assert manager.state["ace_endless_spool_match_mode"] == "exact"


# ---------------------------------------------------------------------------
# GET_ENDLESS_SPOOL_MODE
# ---------------------------------------------------------------------------


class TestQueryingTheMode:
    def test_reports_exact(self, patch_manager):
        patch_manager()
        gcode = _Gcode()

        cmd_mod.cmd_ACE_GET_ENDLESS_SPOOL_MODE(gcode)

        assert "EXACT" in gcode.messages(), gcode.messages()

    @pytest.mark.parametrize("stale", ["material", "next", "garbage", None])
    def test_a_stale_stored_value_is_never_reported(self, patch_manager, stale):
        """Reporting the stored value would advertise a mode that is not used.

        The message reads ``Endless spool mode: <MODE> (explanation)``, so the
        mode token is checked on its own rather than searching the whole string
        - the explanation legitimately mentions materials.
        """
        patch_manager({"ace_endless_spool_match_mode": stale})
        gcode = _Gcode()

        cmd_mod.cmd_ACE_GET_ENDLESS_SPOOL_MODE(gcode)

        message = gcode.messages()
        match = re.search(r"mode:\s*([A-Z ]+?)\s*\(", message)
        assert match, f"could not find the mode field in {message!r}"
        assert match.group(1).strip() == "EXACT", (
            f"stale stored value {stale!r} was reported as the active mode: "
            f"{match.group(1)!r}"
        )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestCommandsAreStillRegistered:
    """Removing the modes must not remove the commands.

    Operators have these in macros and KlipperScreen calls them; dropping them
    would turn a no-op into a hard error mid-print.
    """

    def _registered(self):
        return {name for name, _fn, *_rest in cmd_mod.ACE_COMMANDS}

    def test_set_mode_is_registered(self):
        assert "ACE_SET_ENDLESS_SPOOL_MODE" in self._registered()

    def test_get_mode_is_registered(self):
        assert "ACE_GET_ENDLESS_SPOOL_MODE" in self._registered()

    def test_enable_and_disable_are_registered(self):
        names = self._registered()
        assert "ACE_ENABLE_ENDLESS_SPOOL" in names
        assert "ACE_DISABLE_ENDLESS_SPOOL" in names
