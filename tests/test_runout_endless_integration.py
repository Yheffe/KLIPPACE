"""Runout detection driving the endless spool swap.

This is the seam between "the filament ran out" and "swap to another spool", and
until now nothing tested it. ``_handle_runout_detected`` decides:

  * pause immediately, always
  * show an operator prompt, always
  * swap automatically only when endless spool is enabled *and* a match exists
  * otherwise stay paused and say why

The dangerous failure modes are silent: swapping when disabled (surprising,
mid-print), not swapping when enabled (wasted print), or leaving
``runout_handling_in_progress`` set so the monitor never fires again.
"""

from __future__ import annotations

import pytest

from extras.ace import runout_monitor as rm_mod
from extras.ace.config import ACE_INSTANCES, SLOTS_PER_ACE


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class _State(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class _Gcode:
    def __init__(self):
        self.events = []
        self.scripts = []

    def respond_info(self, msg):
        self.events.append(str(msg))

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def messages(self):
        return " | ".join(self.events)

    def scripts_joined(self):
        return " | ".join(self.scripts)


class _Instance:
    def __init__(self, num, slots):
        self.instance_num = num
        self.tool_offset = num * SLOTS_PER_ACE
        self.SLOT_COUNT = SLOTS_PER_ACE
        self.inventory = [
            {"material": "", "color": [0, 0, 0], "status": "empty"}
            for _ in range(SLOTS_PER_ACE)
        ]
        for index, spec in slots.items():
            self.inventory[index] = dict(spec)


class _Manager:
    def __init__(self):
        self.state = _State()
        # Mirrors AceManager: the runout handler resolves the per-print override
        # first, so the double must expose the same entry point.
        self.endless_spool_print_override = None

    def is_endless_spool_enabled(self):
        if self.endless_spool_print_override is not None:
            return bool(self.endless_spool_print_override)
        return bool(self.state.get("ace_endless_spool_enabled", False))

    def has_nozzle_sensor(self):
        return False


class _Spool:
    """Records what the monitor asked of it."""

    def __init__(self, match):
        self.match = match
        self.searched = []
        self.swaps = []

    def find_exact_match(self, tool_index):
        self.searched.append(tool_index)
        return self.match

    def execute_swap(self, from_tool, to_tool):
        self.swaps.append((from_tool, to_tool))


@pytest.fixture
def env():
    saved = dict(ACE_INSTANCES)
    ACE_INSTANCES.clear()

    class _Reactor:
        def monotonic(self):
            return 0.0

        def register_timer(self, *a, **kw):
            return object()

    class _Printer:
        def get_reactor(self):
            return _Reactor()

        def lookup_object(self, name, default=None):
            return default

    def make(match, *, endless_enabled, slots=None, tool_index=0):
        gcode = _Gcode()
        manager = _Manager()
        manager.state.set("ace_endless_spool_enabled", endless_enabled)

        ACE_INSTANCES.clear()
        if slots is not None:
            ACE_INSTANCES[0] = _Instance(0, slots)

        spool = _Spool(match)
        monitor = rm_mod.RunoutMonitor(
            _Printer(), gcode, _Reactor(), spool, manager,
            runout_debounce_count=1,
        )
        # The pause macro and the runout prompt are Klipper-side; record them
        # instead of running them.
        gcode.prompts = []
        monitor._pause_for_runout = lambda: gcode.scripts.append("PAUSE")
        monitor._show_runout_prompt = (
            lambda *a, **kw: (gcode.scripts.append("PROMPT"), gcode.prompts.append(a))
        )
        monitor._handle_runout_detected(tool_index)
        return monitor, spool, gcode, manager

    try:
        yield make
    finally:
        ACE_INSTANCES.clear()
        ACE_INSTANCES.update(saved)


PLA_RED = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}
PLA_RED_2 = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}


# ---------------------------------------------------------------------------
# always: pause and tell the operator
# ---------------------------------------------------------------------------


class TestItAlwaysPausesFirst:
    @pytest.mark.parametrize("enabled", [True, False])
    def test_pauses_the_print(self, env, enabled):
        _, _, gcode, _ = env(1, endless_enabled=enabled, slots={0: PLA_RED})
        assert "PAUSE" in gcode.scripts, gcode.scripts

    @pytest.mark.parametrize("enabled", [True, False])
    def test_pauses_before_attempting_any_swap(self, env, enabled):
        """A swap must never begin while the machine is still moving."""
        _, _, gcode, _ = env(1, endless_enabled=enabled, slots={0: PLA_RED})
        assert gcode.scripts.index("PAUSE") == 0, gcode.scripts

    @pytest.mark.parametrize("enabled", [True, False])
    def test_shows_the_operator_a_prompt(self, env, enabled):
        _, _, gcode, _ = env(1, endless_enabled=enabled, slots={0: PLA_RED})
        assert "PROMPT" in gcode.scripts, gcode.scripts

    def test_announces_the_runout(self, env):
        _, _, gcode, _ = env(1, endless_enabled=False, slots={0: PLA_RED})
        assert "Runout detected on T0" in gcode.messages(), gcode.messages()

    def test_reports_the_material_and_colour(self, env):
        _, _, gcode, _ = env(1, endless_enabled=False, slots={0: PLA_RED})
        joined = gcode.messages()
        assert "PLA" in joined, joined
        assert "RGB(255,0,0)" in joined, joined


# ---------------------------------------------------------------------------
# enabled + a match: swap
# ---------------------------------------------------------------------------


class TestWhenEnabledAndMatched:
    def test_executes_the_swap(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=True, slots={0: PLA_RED})
        assert spool.swaps == [(0, 1)], spool.swaps

    def test_searches_from_the_run_out_tool(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=True, slots={0: PLA_RED})
        assert spool.searched == [0], spool.searched

    def test_closes_the_prompt_before_swapping(self, env):
        """The runout prompt asks the operator to act; leaving it up while the
        machine swaps itself out is confusing and can swallow their click."""
        _, spool, gcode, _ = env(1, endless_enabled=True, slots={0: PLA_RED})
        assert 'action:prompt_end' in gcode.scripts_joined(), gcode.scripts

    def test_announces_the_match(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=True, slots={0: PLA_RED})
        assert "T0" in gcode.messages() and "T1" in gcode.messages()

    def test_does_not_prompt_the_operator_to_intervene(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=True, slots={0: PLA_RED})
        joined = gcode.messages()
        assert "Staying paused" not in joined, (
            f"a successful swap must not tell the operator to step in: {joined}"
        )


# ---------------------------------------------------------------------------
# enabled but no match
# ---------------------------------------------------------------------------


class TestWhenEnabledButNoMatch:
    def test_does_not_swap(self, env):
        _, spool, gcode, _ = env(-1, endless_enabled=True, slots={0: PLA_RED})
        assert spool.swaps == [], spool.swaps

    def test_says_no_match_was_found(self, env):
        _, spool, gcode, _ = env(-1, endless_enabled=True, slots={0: PLA_RED})
        assert "No endless spool match" in gcode.messages(), gcode.messages()

    def test_leaves_the_prompt_up_for_the_operator(self, env):
        _, spool, gcode, _ = env(-1, endless_enabled=True, slots={0: PLA_RED})
        assert 'action:prompt_end' not in gcode.scripts_joined(), gcode.scripts

    def test_tells_them_what_to_do(self, env):
        _, spool, gcode, _ = env(-1, endless_enabled=True, slots={0: PLA_RED})
        joined = gcode.messages().lower()
        assert "refill" in joined or "load matching" in joined, joined


# ---------------------------------------------------------------------------
# disabled
# ---------------------------------------------------------------------------


class TestWhenDisabled:
    def test_does_not_swap(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=False, slots={0: PLA_RED})
        assert spool.swaps == [], (
            f"endless spool was off, so nothing may be swapped: {spool.swaps}"
        )

    def test_does_not_even_search(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=False, slots={0: PLA_RED})
        assert spool.searched == [], (
            f"the search itself is pointless when the feature is off: {spool.searched}"
        )

    def test_says_it_is_disabled(self, env):
        _, spool, gcode, _ = env(1, endless_enabled=False, slots={0: PLA_RED})
        assert "Endless spool disabled" in gcode.messages(), gcode.messages()

    def test_defaults_to_disabled_when_the_variable_is_absent(self, env):
        """An unset variable must not silently enable automatic swapping."""
        saved = dict(ACE_INSTANCES)
        try:
            gcode = _Gcode()
            manager = _Manager()          # no ace_endless_spool_enabled at all
            ACE_INSTANCES.clear()
            ACE_INSTANCES[0] = _Instance(0, {0: PLA_RED})
            spool = _Spool(1)
            monitor = rm_mod.RunoutMonitor(
                type("P", (), {"get_reactor": lambda s: type(
                    "R", (), {"monotonic": staticmethod(lambda: 0.0),
                              "register_timer": lambda *a, **k: None})()})(),
                gcode, None, spool, manager, runout_debounce_count=1,
            )
            monitor._pause_for_runout = lambda: None
            monitor._show_runout_prompt = lambda *a, **kw: None
            monitor._handle_runout_detected(0)
            assert spool.swaps == [], spool.swaps
        finally:
            ACE_INSTANCES.clear()
            ACE_INSTANCES.update(saved)


# ---------------------------------------------------------------------------
# state hygiene
# ---------------------------------------------------------------------------


class TestStateIsLeftClean:
    """If the handler leaves its guard set, runout detection never fires again -
    and the failure is completely silent until a print is ruined."""

    def test_clears_the_in_progress_guard(self, env):
        monitor, *_ = env(1, endless_enabled=True, slots={0: PLA_RED})
        assert monitor.runout_handling_in_progress is False

    def test_clears_the_guard_even_when_the_swap_throws(self, env):
        saved = dict(ACE_INSTANCES)
        try:
            gcode = _Gcode()
            manager = _Manager()
            manager.state.set("ace_endless_spool_enabled", True)
            ACE_INSTANCES.clear()
            ACE_INSTANCES[0] = _Instance(0, {0: PLA_RED})

            class _Exploding(_Spool):
                def execute_swap(self, from_tool, to_tool):
                    raise RuntimeError("swap blew up")

            monitor = rm_mod.RunoutMonitor(
                type("P", (), {"get_reactor": lambda s: type(
                    "R", (), {"monotonic": staticmethod(lambda: 0.0),
                              "register_timer": lambda *a, **k: None})()})(),
                gcode, None, _Exploding(1), manager, runout_debounce_count=1,
            )
            monitor._pause_for_runout = lambda: None
            monitor._show_runout_prompt = lambda *a, **kw: None
            monitor._handle_runout_detected(0)

            assert monitor.runout_handling_in_progress is False, (
                "an exception in the swap must not disable runout detection for "
                "the rest of the print"
            )
            assert "Runout handling error" in gcode.messages(), gcode.messages()
        finally:
            ACE_INSTANCES.clear()
            ACE_INSTANCES.update(saved)

    def test_resets_sensor_tracking(self, env):
        """Without this the same runout retriggers in a loop."""
        saved = dict(ACE_INSTANCES)
        try:
            gcode = _Gcode()
            manager = _Manager()
            manager.state.set("ace_endless_spool_enabled", False)
            ACE_INSTANCES.clear()
            ACE_INSTANCES[0] = _Instance(0, {0: PLA_RED})
            monitor = rm_mod.RunoutMonitor(
                type("P", (), {"get_reactor": lambda s: type(
                    "R", (), {"monotonic": staticmethod(lambda: 0.0),
                              "register_timer": lambda *a, **k: None})()})(),
                gcode, None, _Spool(-1), manager, runout_debounce_count=1,
            )
            monitor._pause_for_runout = lambda: None
            monitor._show_runout_prompt = lambda *a, **kw: None
            monitor.prev_toolhead_sensor_state = True
            monitor._runout_false_count = 7

            monitor._handle_runout_detected(0)

            assert monitor.prev_toolhead_sensor_state is None
            assert monitor._runout_false_count == 0
        finally:
            ACE_INSTANCES.clear()
            ACE_INSTANCES.update(saved)


# ---------------------------------------------------------------------------
# robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_unregistered_tool_does_not_crash_the_handler(self, env):
        """A runout reported for a tool we know nothing about must still pause."""
        _, spool, gcode, _ = env(-1, endless_enabled=True, slots=None, tool_index=5)
        assert "PAUSE" in gcode.scripts, gcode.scripts
        assert "Runout detected on T5" in gcode.messages(), gcode.messages()

    def test_unknown_slot_reports_generic_material(self, env):
        """With no inventory for that tool the prompt must not invent details."""
        _, spool, gcode, _ = env(
            -1, endless_enabled=False, slots=None, tool_index=5
        )
        assert gcode.prompts, "the operator prompt must still be shown"
        material = gcode.prompts[0][3]
        assert material == "unknown", (
            f"an unregistered slot has no material; the prompt said {material!r}"
        )


# ---------------------------------------------------------------------------
# end to end: the real matcher behind the real monitor
# ---------------------------------------------------------------------------


class TestRealMatcherEndToEnd:
    """Wire the real EndlessSpool into the real RunoutMonitor.

    The tests above use a stub spool that returns whatever they tell it to, which
    proves the monitor wires the decision correctly but says nothing about the
    decision itself. These use the genuine matcher, so "only the same material
    AND the same colour is swapped in" is checked as an observable outcome rather
    than as a unit-level property.
    """

    def _run(self, slots, *, tool_index=0, endless_enabled=True, stale_mode=None):
        from extras.ace.endless_spool import EndlessSpool

        gcode = _Gcode()
        manager = _Manager()
        manager.state.set("ace_endless_spool_enabled", endless_enabled)
        if stale_mode is not None:
            manager.state.set("ace_endless_spool_match_mode", stale_mode)

        ACE_INSTANCES.clear()
        ACE_INSTANCES[0] = _Instance(0, slots)
        manager.instances = [ACE_INSTANCES[0]]

        class _Reactor:
            def monotonic(self):
                return 0.0

            def register_timer(self, *a, **kw):
                return object()

        class _Printer:
            def get_reactor(self):
                return _Reactor()

        spool = EndlessSpool(_Printer(), gcode, manager)
        spool.swaps = []
        real_swap = spool.execute_swap
        spool.execute_swap = lambda f, t: (spool.swaps.append((f, t)), real_swap(f, t))[1]

        monitor = rm_mod.RunoutMonitor(
            _Printer(), gcode, _Reactor(), spool, manager,
            runout_debounce_count=1,
        )
        monitor._pause_for_runout = lambda: gcode.scripts.append("PAUSE")
        monitor._show_runout_prompt = lambda *a, **kw: gcode.scripts.append("PROMPT")
        monitor._handle_runout_detected(tool_index)
        return spool, gcode

    def test_identical_spool_is_swapped_in(self):
        spool, gcode = self._run({0: PLA_RED, 2: PLA_RED_2})
        assert spool.swaps == [(0, 2)], spool.swaps

    def test_same_material_different_colour_is_not_swapped(self):
        """THE GUARANTEE: a colour change is never automatic."""
        spool, gcode = self._run(
            {0: PLA_RED,
             1: {"material": "PLA", "color": [0, 0, 255], "status": "ready"}}
        )
        assert spool.swaps == [], spool.swaps
        assert "No endless spool match" in gcode.messages(), gcode.messages()

    def test_same_colour_different_material_is_not_swapped(self):
        spool, gcode = self._run(
            {0: PLA_RED,
             1: {"material": "PETG", "color": [255, 0, 0], "status": "ready"}}
        )
        assert spool.swaps == [], spool.swaps

    def test_a_stale_stored_mode_cannot_loosen_it(self):
        """An upgrade from the two-mode era must not change the behaviour."""
        for stale in ("material", "next"):
            spool, gcode = self._run(
                {0: PLA_RED,
                 1: {"material": "PLA", "color": [0, 0, 255], "status": "ready"}},
                stale_mode=stale,
            )
            assert spool.swaps == [], (
                f"stored mode {stale!r} resurrected the old behaviour: {spool.swaps}"
            )

    def test_an_unidentified_spool_is_never_swapped_in(self):
        spool, gcode = self._run(
            {0: PLA_RED,
             1: {"material": "unknown", "color": [255, 0, 0], "status": "ready"}}
        )
        assert spool.swaps == [], spool.swaps

    def test_disabled_still_beats_an_available_exact_match(self):
        spool, gcode = self._run(
            {0: PLA_RED, 1: PLA_RED_2}, endless_enabled=False
        )
        assert spool.swaps == [], spool.swaps
