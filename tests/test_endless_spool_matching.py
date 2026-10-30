"""Endless spool matching logic: which spool do we swap to?

Endless spool runs unattended, mid-print, often hours in. A wrong decision here
either ruins the print (incompatible filament) or wastes it (no swap attempted
when a perfectly good spool was available). Neither shows up in any other test,
because the whole path only executes after a runout is detected.

These tests drive the real ``EndlessSpool.find_exact_match`` against the real
``ACE_INSTANCES`` registry and the real ``get_instance_from_tool`` /
``get_local_slot`` helpers, so the tool-index arithmetic is exercised rather than
mocked away. Only the printer, gcode and manager are faked.

Only exact matching exists: the same material AND the same RGB colour. The
``material`` (ignore colour) and ``next`` (ignore material and colour) modes
were removed, so the tests that used to pin their behaviour now assert its
absence - see ``TestTheFormerModesAreGone``.

Removing them also closed a hole: ``next`` returned before the unknown-material
guard ran, so it could feed an unidentifiable spool into a running print. The
guard now sits on the only path there is.

One fragility is pinned rather than fixed: colour comparison is exact and
type-sensitive, so a ``(255, 0, 0)`` tuple never equals a ``[255, 0, 0]`` list.
"""

from __future__ import annotations

import logging

import pytest

from extras.ace import config as cfg
from extras.ace.config import ACE_INSTANCES, SLOTS_PER_ACE
from extras.ace.endless_spool import EndlessSpool


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class _State(dict):
    """Minimal stand-in for PersistentState (get/set only)."""

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class _Gcode:
    def __init__(self):
        self.events = []
        self.scripts = []

    def respond_info(self, msg):
        self.events.append(msg)

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def messages(self):
        return " | ".join(str(e) for e in self.events)


class _Inventory(dict):
    """One ACE unit's four slots."""

    def __init__(self, slots=None):
        super().__init__(slots or {})

    def slot(self, index):
        return self[index]


class _Instance:
    def __init__(self, num, slots):
        self.instance_num = num
        self.tool_offset = num * SLOTS_PER_ACE
        self.SLOT_COUNT = SLOTS_PER_ACE
        self.inventory = [_slot() for _ in range(SLOTS_PER_ACE)]
        for index, spec in slots.items():
            self.inventory[index] = _slot(**spec)


class _Manager:
    def __init__(self, state=None):
        self.state = _State(state or {})
        self.instances = []


def _slot(material="", color=None, status="empty"):
    return {
        "material": material,
        "color": [0, 0, 0] if color is None else color,
        "status": status,
    }


@pytest.fixture
def env():
    """Two ACE units (8 tools), with the registry patched and restored."""
    saved = dict(ACE_INSTANCES)
    ACE_INSTANCES.clear()
    manager = _Manager()
    gcode = _Gcode()

    class _Reactor:
        def monotonic(self):
            return 0.0

    class _Printer:
        def get_reactor(self):
            return _Reactor()

    spool = EndlessSpool(_Printer(), gcode, manager)

    def build(*units):
        """units = ({slot_index: spec}, {...}) one dict per ACE instance."""
        ACE_INSTANCES.clear()
        manager.instances = []
        for num, slots in enumerate(units):
            inst = _Instance(num, slots)
            ACE_INSTANCES[num] = inst
            manager.instances.append(inst)
        return manager.instances

    try:
        yield spool, manager, gcode, build, ACE_INSTANCES
    finally:
        ACE_INSTANCES.clear()
        ACE_INSTANCES.update(saved)


PLA_RED = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}
PLA_RED_2 = {"material": "PLA", "color": [255, 0, 0], "status": "ready"}
PLA_BLUE = {"material": "PLA", "color": [0, 0, 255], "status": "ready"}
PETG_RED = {"material": "PETG", "color": [255, 0, 0], "status": "ready"}


# ---------------------------------------------------------------------------
# match mode selection
# ---------------------------------------------------------------------------


class TestMatchMode:
    def test_defaults_to_exact(self, env):
        spool, *_ = env
        assert spool.get_match_mode() == "exact"

    def test_exact_is_reported(self, env):
        spool, manager, *_ = env
        manager.state.set("ace_endless_spool_match_mode", "exact")
        assert spool.get_match_mode() == "exact"

    @pytest.mark.parametrize("stale", ["material", "next", "EXACT", "", None, 3])
    def test_every_other_value_reports_exact(self, env, stale):
        """The former modes are gone; a persisted value must not revive them.

        An older install can have ``ace_endless_spool_match_mode`` saved as
        ``material`` or ``next``. Upgrading must not silently leave the machine
        on the looser behaviour, so the stored value is ignored and reported as
        exact.
        """
        spool, manager, *_ = env
        manager.state.set("ace_endless_spool_match_mode", stale)
        assert spool.get_match_mode() == "exact"

    def test_a_stale_value_is_reported_once_not_every_search(self, env, caplog):
        """A warning on every runout search would bury the rest of the log."""
        spool, manager, gcode, build, _ = env
        manager.state.set("ace_endless_spool_match_mode", "next")
        build({0: PLA_RED, 1: PLA_BLUE})

        with caplog.at_level(logging.WARNING):
            caplog.clear()
            for _ in range(5):
                spool.find_exact_match(0)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]


# ---------------------------------------------------------------------------
# exact mode
# ---------------------------------------------------------------------------


class TestExactMode:
    def test_matches_same_material_and_colour(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED, 2: PLA_RED_2})
        assert spool.find_exact_match(0) == 2

    def test_rejects_different_colour(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED, 1: PLA_BLUE})
        assert spool.find_exact_match(0) == -1

    def test_rejects_different_material(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED, 1: PETG_RED})
        assert spool.find_exact_match(0) == -1

    def test_prefers_the_closest_match(self, env):
        """Closest first: the shortest purge and the least wasted time."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED, 1: PLA_RED_2, 2: PLA_RED_2})
        assert spool.find_exact_match(0) == 1

    def test_never_returns_the_current_tool(self, env):
        """Matching the slot that just ran out would loop until it gave up."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED})
        assert spool.find_exact_match(0) != 0

    def test_colour_comparison_is_type_sensitive(self, env):
        """LATENT FRAGILITY, NOT A LIVE BUG.

        ``cand_color != current_color`` compares sequences by value, but a
        ``(255, 0, 0)`` tuple never equals a ``[255, 0, 0]`` list. Identical
        colours of mixed type compare unequal, so a legitimate match would be
        refused and the print would stay paused.

        Checked: not reachable today. Every writer of ``inventory["color"]``
        either uses a literal list (``instance.py``) or ``saved_color`` from
        persistent state, which round-trips through JSON and comes back a list.
        So this documents the constraint rather than a defect - if a future
        caller hands in a tuple, this test will start failing and that is the
        signal to normalise the comparison.
        """
        spool, manager, gcode, build, _ = env
        build({0: {"material": "PLA", "color": [255, 0, 0], "status": "ready"},
               1: {"material": "PLA", "color": (255, 0, 0), "status": "ready"}})
        assert spool.find_exact_match(0) == -1


# ---------------------------------------------------------------------------
# only exact matching exists
# ---------------------------------------------------------------------------


class TestTheFormerModesAreGone:
    """Endless spool only swaps to a spool with the same material AND colour.

    ``material`` (ignore colour) and ``next`` (ignore material and colour) were
    removed on request. A runout is not a good moment to change colour in the
    part, and swapping in an unidentified spool risks a different polymer. Both
    classes of test below now assert that the looser behaviour is *absent* -
    which is the whole point of the lock-down.
    """

    def test_material_only_is_not_honoured(self, env):
        """Same material, different colour used to match. It must not now."""
        spool, manager, gcode, build, _ = env
        manager.state.set("ace_endless_spool_match_mode", "material")
        build({0: PLA_RED, 1: PLA_BLUE})
        assert spool.find_exact_match(0) == -1

    def test_next_ready_is_not_honoured(self, env):
        """A ready spool of a different material used to match. It must not now."""
        spool, manager, gcode, build, _ = env
        manager.state.set("ace_endless_spool_match_mode", "next")
        build({0: PLA_RED, 1: PETG_RED})
        assert spool.find_exact_match(0) == -1

    def test_a_different_colour_of_the_right_material_never_matches(self, env):
        spool, manager, gcode, build, _ = env
        for stale in ("material", "next", "exact"):
            manager.state.set("ace_endless_spool_match_mode", stale)
            build({0: PLA_RED, 1: PLA_BLUE})
            assert spool.find_exact_match(0) == -1, (
                f"a colour change must never be swapped in (stored mode {stale!r})"
            )

    def test_a_different_material_of_the_right_colour_never_matches(self, env):
        spool, manager, gcode, build, _ = env
        for stale in ("material", "next", "exact"):
            manager.state.set("ace_endless_spool_match_mode", stale)
            build({0: PLA_RED, 1: PETG_RED})
            assert spool.find_exact_match(0) == -1, (
                f"a different polymer must never be swapped in (stored mode {stale!r})"
            )

    def test_an_unknown_material_never_matches_in_any_stored_mode(self, env):
        """``next`` used to return before the unknown-material guard ran.

        With the mode gone, that hole is gone with it: the guard is on the only
        path that exists.
        """
        spool, manager, gcode, build, _ = env
        for stale in ("next", "material", "exact"):
            manager.state.set("ace_endless_spool_match_mode", stale)
            build({0: PLA_RED,
                   1: {"material": "unknown", "color": [255, 0, 0],
                       "status": "ready"},
                   2: PLA_RED_2})
            assert spool.find_exact_match(0) == 2, (
                f"the unidentified spool must be skipped and T2 found "
                f"(stored mode {stale!r})"
            )

    def test_an_exact_match_still_works_whatever_is_stored(self, env):
        """The lock-down must not break the supported case."""
        spool, manager, gcode, build, _ = env
        for stale in ("material", "next", "exact", "garbage"):
            manager.state.set("ace_endless_spool_match_mode", stale)
            build({0: PLA_RED, 1: PLA_RED_2})
            assert spool.find_exact_match(0) == 1, (
                f"an identical spool must always be found (stored mode {stale!r})"
            )


# ---------------------------------------------------------------------------
# the unknown-material safety guard
# ---------------------------------------------------------------------------


class TestUnknownMaterialGuard:
    """Unknown materials are never swapped in, except in ``next`` mode.

    The rationale in the code is explicit: an unidentified spool may be a
    different polymer at a different temperature, and feeding it mid-print is
    worse than pausing.
    """

    @pytest.mark.parametrize("mode", ["exact", "material"])
    def test_unknown_candidate_is_skipped(self, env, mode):
        spool, manager, gcode, build, _ = env
        manager.state.set("ace_endless_spool_match_mode", mode)
        build({0: PLA_RED,
               1: {"material": "unknown", "color": [255, 0, 0], "status": "ready"},
               2: PLA_RED_2})
        assert spool.find_exact_match(0) == 2, (
            "an unidentified spool must be passed over even when material and "
            "colour would otherwise line up"
        )

    @pytest.mark.parametrize("mode", ["exact", "material"])
    def test_unknown_current_material_never_matches(self, env, mode):
        """If we cannot identify what ran out, we cannot know what matches."""
        spool, manager, gcode, build, _ = env
        manager.state.set("ace_endless_spool_match_mode", mode)
        build({0: {"material": "unknown", "color": [255, 0, 0], "status": "ready"},
               1: {"material": "unknown", "color": [255, 0, 0], "status": "ready"}})
        assert spool.find_exact_match(0) == -1

    def test_unknown_is_rejected_even_in_the_right_colour(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED,
               1: {"material": "unknown", "color": [255, 0, 0], "status": "ready"}})
        assert spool.find_exact_match(0) == -1


# ---------------------------------------------------------------------------
# slot status filtering
# ---------------------------------------------------------------------------


class TestSlotStatus:
    @pytest.mark.parametrize(
        "status", ["empty", "feeding", "unwinding", "shifting", "preload", "searching"]
    )
    def test_only_ready_slots_are_candidates(self, env, status):
        """A slot mid-operation, or empty, or temporarily flagged, is not a match."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED,
               1: {"material": "PLA", "color": [255, 0, 0], "status": status},
               2: PLA_RED_2})
        assert spool.find_exact_match(0) == 2

    def test_missing_status_is_not_a_candidate(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED,
               1: {"material": "PLA", "color": [255, 0, 0]},
               2: PLA_RED_2})
        assert spool.find_exact_match(0) == 2


# ---------------------------------------------------------------------------
# text normalisation
# ---------------------------------------------------------------------------


class TestMaterialNormalisation:
    @pytest.mark.parametrize("other", ["pla", "PlA", "  PLA  ", "pla\n"])
    def test_material_matching_ignores_case_and_whitespace(self, env, other):
        """RFID, manual entry and slicer presets do not agree on capitalisation."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED,
               1: {"material": other, "color": [255, 0, 0], "status": "ready"}})
        assert spool.find_exact_match(0) == 1


# ---------------------------------------------------------------------------
# tool index arithmetic
# ---------------------------------------------------------------------------


class TestToolArithmetic:
    def test_wraps_past_the_end_of_the_list(self, env):
        """From the last slot, the only other candidates are lower indices."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED, 1: {}, 2: {}, 3: PLA_RED_2})
        assert spool.find_exact_match(3) == 0

    def test_crosses_into_the_second_ace_unit(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED}, {0: PLA_RED_2})
        assert spool.find_exact_match(0) == 4, (
            "tool 4 is slot 0 of ACE 1; matching must span both units"
        )

    def test_wraps_from_the_second_unit_back_to_the_first(self, env):
        spool, manager, gcode, build, _ = env
        build({1: PLA_RED}, {3: PLA_RED_2})
        # T7 is ACE1 slot 3; the next match going forward wraps to T1.
        assert spool.find_exact_match(7) == 1

    def test_negative_tool_index_returns_minus_one(self, env):
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED})
        assert spool.find_exact_match(-1) == -1

    def test_tool_beyond_the_registered_instances_returns_minus_one(self, env):
        """A single-unit machine asked about T7 must not pretend to know."""
        spool, manager, gcode, build, _ = env
        build({0: PLA_RED})
        assert spool.find_exact_match(7) == -1

    def test_no_instances_at_all_returns_minus_one(self, env):
        spool, manager, gcode, build, _ = env
        build()
        assert spool.find_exact_match(0) == -1


# ---------------------------------------------------------------------------
# get_status contract
# ---------------------------------------------------------------------------


class TestStatus:
    def test_returns_a_dict(self, env):
        spool, *_ = env
        assert isinstance(spool.get_status(), dict)


def test_slots_per_ace_is_four():
    """The tool-index arithmetic in every test above assumes this."""
    assert cfg.SLOTS_PER_ACE == 4
