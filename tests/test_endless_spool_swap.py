"""Endless spool swap execution: retries, recovery, and giving up safely.

``execute_swap`` is the part that actually moves filament. It marks the run-out
slot empty, calls ``perform_tool_change``, resumes the print, and - if the load
fails - unloads the bad candidate, finds another, and retries. It gives up after
three attempts and must leave the machine in a state a human can recover from.

The scenarios that matter are all failure scenarios, because the happy path is
the one thing that gets exercised whenever the feature is used at all:

  * a candidate that fails to load, followed by a successful rival
  * every candidate failing, ending in a prompt rather than a dead pause
  * the "temporarily unavailable" bookkeeping being restored even when the
    search itself throws - otherwise a slot stays stuck in ``searching``
    for the rest of the print

Two behaviours here are pinned rather than endorsed; both are flagged in the
docstrings and raised in review notes.
"""

from __future__ import annotations

import pytest

from extras.ace.config import ACE_INSTANCES, SLOTS_PER_ACE
from extras.ace.endless_spool import EndlessSpool


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
    """One ACE unit, with the collaborators execute_swap touches."""

    def __init__(self, num, slots, unload_error=None):
        self.instance_num = num
        self.tool_offset = num * SLOTS_PER_ACE
        self.SLOT_COUNT = SLOTS_PER_ACE
        self.parkposition_to_toolhead_length = 1050.0
        self.inventory = [_empty_slot() for _ in range(SLOTS_PER_ACE)]
        for index, spec in slots.items():
            self.inventory[index] = _slot(**spec)
        self.unload_error = unload_error
        self.unloaded = []

    def _smart_unload_slot(self, slot, length=None):
        self.unloaded.append(slot)
        if self.unload_error:
            raise self.unload_error


def _empty_slot():
    return {"material": "", "color": [0, 0, 0], "status": "empty"}


def _slot(material="", color=None, status="ready"):
    return {
        "material": material,
        "color": [0, 0, 0] if color is None else color,
        "status": status,
    }


class _Manager:
    def __init__(self, gcode):
        self.state = _State()
        self.instances = []
        self.gcode = gcode
        self.tool_change_calls = []
        self.persist_calls = 0
        # Each entry: None for success, or an Exception to raise.
        self.tool_change_outcomes = []

    def perform_tool_change(self, from_tool, to_tool, is_endless_spool=False):
        self.tool_change_calls.append((from_tool, to_tool, is_endless_spool))
        if self.tool_change_outcomes:
            outcome = self.tool_change_outcomes.pop(0)
            if outcome is not None:
                raise outcome
        return f"Tool {to_tool} loaded"

    def _sync_inventory_to_persistent(self, instance_num, flush=True):
        self.persist_calls += 1


PLA_RED = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}
PLA_RED_2 = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}
PLA_RED_3 = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}


@pytest.fixture
def env():
    saved = dict(ACE_INSTANCES)
    ACE_INSTANCES.clear()
    gcode = _Gcode()
    manager = _Manager(gcode)

    class _Reactor:
        def monotonic(self):
            return 0.0

    class _Printer:
        def get_reactor(self):
            return _Reactor()

    spool = EndlessSpool(_Printer(), gcode, manager)

    def build(*units):
        """units = ({slot: spec} or (slots, unload_error)) per ACE instance."""
        ACE_INSTANCES.clear()
        manager.instances = []
        for num, spec in enumerate(units):
            slots, error = (spec, None) if isinstance(spec, dict) else spec
            inst = _Instance(num, slots, unload_error=error)
            ACE_INSTANCES[num] = inst
            manager.instances.append(inst)
        return manager.instances

    try:
        yield spool, manager, gcode, build
    finally:
        ACE_INSTANCES.clear()
        ACE_INSTANCES.update(saved)


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


class TestSuccessfulSwap:
    def test_marks_the_run_out_slot_empty(self, env):
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2})
        spool.execute_swap(0, 1)
        assert ace.inventory[0]["status"] == "empty", (
            "the exhausted spool must not stay 'ready', or a later runout would "
            "try to feed from it again"
        )

    def test_asks_for_an_endless_spool_tool_change(self, env):
        """The flag suppresses unloading a tool that is already an empty path."""
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        spool.execute_swap(0, 1)
        assert manager.tool_change_calls == [(0, 1, True)]

    def test_resumes_the_print(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        spool.execute_swap(0, 1)
        assert "RESUME PURGE=0" in gcode.scripts, (
            "the print must resume, otherwise the swap achieved nothing"
        )

    def test_resumes_only_after_the_tool_change_succeeded(self, env):
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("feed jammed")]
        spool.execute_swap(0, 1)
        assert "RESUME PURGE=0" not in gcode.scripts, (
            "resuming with no filament loaded would print air"
        )

    def test_reports_the_outcome(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        spool.execute_swap(0, 1)
        assert "T0" in gcode.messages() and "T1" in gcode.messages()


# ---------------------------------------------------------------------------
# recovery after a failed load
# ---------------------------------------------------------------------------


class TestRecovery:
    def test_unloads_the_failed_candidate(self, env):
        """A half-loaded spool has to be cleared before another can be tried."""
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("feed jammed"), None]
        spool.execute_swap(0, 1)
        assert ace.unloaded == [1], f"expected T1 (slot 1) to be unloaded: {ace.unloaded}"

    def test_marks_the_failed_candidate_empty(self, env):
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("feed jammed"), None]
        spool.execute_swap(0, 1)
        assert ace.inventory[1]["status"] == "empty", (
            "a spool that failed to load must not be offered again"
        )

    def test_retries_with_the_next_matching_spool(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("feed jammed"), None]
        spool.execute_swap(0, 1)
        assert manager.tool_change_calls == [(0, 1, True), (0, 2, True)], (
            "the retry must target the next candidate, still swapping away from "
            "the original run-out tool"
        )

    def test_searches_from_the_original_tool_not_the_failed_candidate(self, env):
        """Searching onward from T1 would skip anything between T0 and T1."""
        spool, manager, gcode, build = env
        build({0: PLA_RED,
               1: {"material": "PLA", "color": [0, 0, 0], "status": "ready"},
               2: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("feed jammed"), None]
        spool.execute_swap(0, 1)
        # T1 is PETG-ish (different colour) so it is not a candidate any more;
        # T2 is the match. The point is that the search found T2 at all.
        assert manager.tool_change_calls[-1][1] == 2

    def test_restores_temporarily_hidden_statuses(self, env):
        """Tried tools are hidden during the search, then put back.

        Leaving one as ``searching`` would make it invisible to every later
        match for the rest of the print.
        """
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2, 2: {"material": "PETG",
                                                      "color": [0, 0, 0],
                                                      "status": "ready"}})
        manager.tool_change_outcomes = [Exception("feed jammed"), None]
        spool.execute_swap(0, 1)
        assert ace.inventory[2]["status"] == "ready", (
            f"an untried slot must keep its status: {ace.inventory[2]}"
        )

    def test_statuses_are_restored_even_if_the_search_raises(self, env):
        """The restore lives in a ``finally``; this proves it earns its keep."""
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("feed jammed")]

        original = spool.find_exact_match

        def _boom(_tool):
            raise RuntimeError("search exploded")

        spool.find_exact_match = _boom
        try:
            spool.execute_swap(0, 1)
        finally:
            spool.find_exact_match = original

        assert ace.inventory[1]["status"] != "searching", (
            f"slot left mid-search after an exception: {ace.inventory[1]}"
        )


# ---------------------------------------------------------------------------
# giving up
# ---------------------------------------------------------------------------


class TestGivingUp:
    def test_never_exceeds_three_attempts(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3, 3: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        assert len(manager.tool_change_calls) == 3, (
            f"bounded retries, got {manager.tool_change_calls}"
        )

    def test_does_not_resume_when_everything_failed(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        assert "RESUME PURGE=0" not in gcode.scripts

    def test_says_so_loudly(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        joined = gcode.messages()
        assert "SWAP FAILED" in joined, joined
        assert "PAUSED" in joined.upper(), (
            f"the operator must be told the print is waiting on them: {joined}"
        )

    def test_shows_a_prompt_with_resume_and_cancel(self, env):
        """A dead pause with no UI is the worst outcome; give the operator buttons."""
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        scripts = gcode.scripts_joined()
        assert "prompt_begin" in scripts, scripts
        assert "prompt_show" in scripts, (
            f"a built prompt that is never shown leaves the user staring at a paused "
            f"print: {scripts}"
        )
        assert "RESUME|primary" in scripts, scripts
        assert "CANCEL_PRINT" in scripts, scripts

    def test_stops_searching_once_candidates_run_out(self, env):
        """With a single candidate, the second attempt must give up immediately."""
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        assert len(manager.tool_change_calls) == 1, (
            f"no second candidate existed, so there was nothing to retry: "
            f"{manager.tool_change_calls}"
        )

    def test_the_attempt_bound_is_what_stops_it_when_matches_are_plentiful(self, env):
        """THE REASON THE CAP EXISTS.

        The tests above all run out of candidates before the cap is reached, so
        they would pass just as happily with an unbounded loop. Give it a full
        box of identical spools and the cap is the only thing that ends it.
        """
        spool, manager, gcode, build = env
        # Eight identical spools: seven other candidates to chew through.
        build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_3, 3: PLA_RED_3},
              {0: PLA_RED_2, 1: PLA_RED_3, 2: PLA_RED_2, 3: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("fail")] * 20

        spool.execute_swap(0, 1)

        assert len(manager.tool_change_calls) == 3, (
            f"the swap must give up after three attempts even with more spools "
            f"available; it made {len(manager.tool_change_calls)}"
        )

    def test_reports_lack_of_candidates(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        assert "No more matching spools" in gcode.messages(), gcode.messages()


# ---------------------------------------------------------------------------
# the run-out slot after a failed swap
# ---------------------------------------------------------------------------


class TestRunOutSlotAfterFailure:
    def test_run_out_slot_is_left_ready(self, env):
        """DOCUMENTED, AND SUSPECT.

        On total failure the exhausted spool is set back to ``ready`` -
        "restore status for retry". Nothing verifies that a spool was actually
        refilled, so the inventory now claims an empty slot is usable. It will
        be treated as a valid endless-spool candidate next time.

        The consequence is bounded (that swap fails, recovery moves on), and the
        operator-facing prompt does ask them to refill. But ``ready`` means
        "physically present and usable" elsewhere in this codebase, so this is
        either a deliberate nudge or a latent bug. Pinned so it is a decision.
        """
        spool, manager, gcode, build = env
        (ace,) = build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        assert ace.inventory[0]["status"] == "ready"

    def test_the_prompt_asks_for_a_refill(self, env):
        spool, manager, gcode, build = env
        build({0: PLA_RED, 1: PLA_RED_2})
        manager.tool_change_outcomes = [Exception("fail")] * 5
        spool.execute_swap(0, 1)
        scripts = gcode.scripts_joined().lower()
        assert "refill" in scripts or "load matching" in scripts, scripts


# ---------------------------------------------------------------------------
# multi-instance
# ---------------------------------------------------------------------------


class TestAcrossInstances:
    def test_swaps_to_a_spool_on_the_second_unit(self, env):
        spool, manager, gcode, build = env
        (unit0, unit1) = build({0: PLA_RED}, {0: PLA_RED_2})
        spool.execute_swap(0, 4)
        assert manager.tool_change_calls == [(0, 4, True)]
        assert unit0.inventory[0]["status"] == "empty"
        assert unit1.inventory[0]["status"] == "ready"

    def test_recovery_unloads_on_the_right_unit(self, env):
        spool, manager, gcode, build = env
        (unit0, unit1) = build({0: PLA_RED}, {0: PLA_RED_2, 1: PLA_RED_3})
        manager.tool_change_outcomes = [Exception("fail"), None]
        spool.execute_swap(0, 4)
        assert unit1.unloaded == [0], (
            f"the recovery unload must go to ACE 1 slot 0: {unit1.unloaded}"
        )
        assert unit0.unloaded == [], unit0.unloaded
