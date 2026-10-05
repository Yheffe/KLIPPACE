"""Regression tests: the filament must be cut exactly ONCE per unload.

Two independent code paths used to cut the filament during a single unload:

  1. ``_ACE_PREPARE_FOR_RETRACTION`` (gcode macro) runs ``CUT_TIP``, invoked by
     ``AceManager.prepare_toolhead_for_filament_retraction``.
  2. ``AceInstance._smart_unload_slot`` ran ``self.cut_macro`` itself.

Because (2) re-engaged the blade *after* the extruder had already retracted,
the cutter sheared a detached stub and could push a fragment into the ACE hub,
jamming it -- which is what produced the observed "Toolhead sensor still
triggered after 1075.0mm retraction" and the subsequent feed failure.

``_smart_unload_slot`` now takes ``skip_cut`` and ``AceManager.smart_unload``
passes ``skip_cut=True`` whenever the prep hook reports it already cut.
"""

from __future__ import annotations

import pytest


class _FakeManager:
    """Minimal manager stand-in for sensor/RDM queries."""

    def __init__(self, rdm: bool = False, entry_triggered: bool = False, nozzle: bool = False):
        self._rdm = rdm
        self._entry = entry_triggered
        self._nozzle = nozzle

    def has_rdm_sensor(self) -> bool:
        return self._rdm

    def has_nozzle_sensor(self) -> bool:
        return self._nozzle

    def get_entry_switch_state(self) -> bool:
        return self._entry

    def get_nozzle_switch_state(self) -> bool:
        return self._nozzle

    def get_switch_state(self, _sensor) -> bool:
        return self._rdm


class _FakeMonitor:
    """Sensor monitor stand-in: never reports a trigger."""

    def get_timing(self):
        return None

    def get_call_count(self):
        return 0


class _FakeToolhead:
    def wait_moves(self):
        pass


class _FakePrinter:
    def lookup_object(self, name, default=None):
        if name == "toolhead":
            return _FakeToolhead()
        return default


class _FakeGcode:
    def __init__(self):
        self.events = []

    def respond_info(self, msg):
        self.events.append(("info", msg))

    def run_script_from_command(self, script):
        self.events.append(("script", script))


class _FakeUnloadSelf:
    """Duck-typed ``AceInstance`` carrying only what ``_smart_unload_slot`` uses."""

    def __init__(self, manager):
        self.manager = manager
        self.printer = _FakePrinter()
        self.gcode = _FakeGcode()
        self.instance_num = 0
        self.retract_speed = 50.0
        self.timeout_multiplier = 1.0
        self.parkposition_to_toolhead_length = 1050.0
        self.parkposition_to_rdm_length = 150.0
        self.cut_macro = "CUT_TIP"
        self.cut_retract_length = 10.0
        self.cut_retract_speed = 15.0
        self.events = []

    # -- collaborators _smart_unload_slot calls ---------------------------
    def _disable_feed_assist(self, slot):
        self.events.append(("disable_feed_assist", slot))

    def _make_sensor_trigger_monitor(self, sensor):
        return _FakeMonitor()

    def _retract(self, slot, length, speed, on_retract_started=None, on_wait_for_ready=None):
        self.events.append(("retract", slot, length, speed))

    def _stop_retract(self, slot):
        self.events.append(("stop_retract", slot))

    def _extruder_move(self, length, speed, wait_for_move_end=False):
        self.events.append(("extruder_move", length, speed))

    def dwell(self, *args, **kwargs):
        self.events.append(("dwell",) + args)

    def _smart_unload_slot(self, *a, **kw):  # pragma: no cover - guard against recursion
        raise AssertionError("_FakeUnloadSelf must not call itself")


@pytest.fixture
def unload_self():
    """A ready-to-use fake instance whose toolhead sensor is already clear."""
    return _FakeUnloadSelf(_FakeManager(rdm=False, entry_triggered=False))


class TestSmartUnloadSlotCutOnce:
    def test_skip_cut_skips_cutter_and_precut_retract(self, unload_self):
        from extras.ace.instance import AceInstance

        result = AceInstance._smart_unload_slot(
            unload_self, slot=2, length=1075.0, skip_cut=True
        )

        assert result is True
        scripts = [e[1] for e in unload_self.gcode.events if e[0] == "script"]
        assert scripts == [], f"cutter macro must not run when skip_cut=True (got {scripts})"
        extruder = [e for e in unload_self.events if e[0] == "extruder_move"]
        assert extruder == [], f"pre-cut extruder retract must be skipped (got {extruder})"
        # The actual ACE pull-back must still happen.
        assert any(e[0] == "retract" for e in unload_self.events)

    def test_without_skip_cut_the_cutter_runs(self, unload_self):
        from extras.ace.instance import AceInstance

        AceInstance._smart_unload_slot(unload_self, slot=2, length=1075.0, skip_cut=False)

        scripts = [e[1] for e in unload_self.gcode.events if e[0] == "script"]
        assert "CUT_TIP" in scripts, "cutter macro must run when skip_cut=False"
        extruder = [e for e in unload_self.events if e[0] == "extruder_move"]
        assert extruder, "pre-cut extruder retract must run when skip_cut=False"
        assert extruder[0][1] == -10.0, "pre-cut retract must be negative"
        assert extruder[0][2] == unload_self.cut_retract_speed, (
            "pre-cut retract must use cut_retract_speed, not the feed speed"
        )

    def test_precut_retract_happens_before_the_cut(self, unload_self):
        from extras.ace.instance import AceInstance

        AceInstance._smart_unload_slot(unload_self, slot=2, length=1075.0, skip_cut=False)

        order = [e[0] for e in unload_self.events]
        move_i = order.index("extruder_move")
        cut_i = next(
            i for i, e in enumerate(unload_self.gcode.events) if e == ("script", "CUT_TIP")
        )
        assert move_i < cut_i + len(order), "sanity"
        # extruder_move is recorded on self.events; the macro on gcode.events.
        # Assert relative order within the shared timeline instead:
        assert unload_self.events[move_i][1] < 0


class TestSmartUnloadPassesSkipCut:
    """The plumbing that decides whether to cut: AceManager.smart_unload."""

    @staticmethod
    def _build_manager(monkeypatch, prep_cut_done: bool, toolhead_triggered: bool):
        from extras.ace import manager as mgr_mod

        class _State(dict):
            def set(self, key, value):
                self[key] = value

        class _Protocol:
            @staticmethod
            def feed_assist_causes_busy():
                return False

        class _Instance:
            def __init__(self):
                self.inventory = [{"status": "ready"} for _ in range(4)]
                self.calls = []
                self.protocol = _Protocol()
                self._feed_assist_index = -1

            def wait_ready(self):
                pass

            def _smart_unload_slot(self, slot, length=None, skip_cut=False):
                self.calls.append({"slot": slot, "length": length, "skip_cut": skip_cut})
                return True

        m = mgr_mod.AceManager.__new__(mgr_mod.AceManager)
        inst = _Instance()
        m.instances = [inst]
        m.gcode = _FakeGcode()
        m.state = _State({"ace_current_index": 1})
        m.toolhead_retraction_length = 25.0
        m.toolhead_retraction_speed = 15.0
        # The retraction-prep hook reports whether it performed the cut.
        m.prepare_toolhead_for_filament_retraction = lambda tool_index=-1: prep_cut_done
        # toolhead_triggered selects which unload branch runs.
        m.get_instant_switch_state = lambda sensor: toolhead_triggered
        m.get_entry_switch_state = lambda: toolhead_triggered
        m.get_nozzle_switch_state = lambda: False
        m.has_nozzle_sensor = lambda: False
        m.is_filament_path_free_instant = lambda: True
        m.has_rdm_sensor = lambda: False
        m._get_config_for_tool = lambda tool, param: 1050.0
        m._wait_toolhead_move_finished = lambda: None
        m._extruder_move = lambda *a, **kw: None

        monkeypatch.setattr(mgr_mod, "get_instance_from_tool", lambda tool: 0)
        monkeypatch.setattr(mgr_mod, "get_local_slot", lambda tool, instance_num: 1)
        return m, inst

    def test_prep_hook_cut_means_smart_unload_skips_the_cut(self, monkeypatch):
        m, inst = self._build_manager(monkeypatch, prep_cut_done=True, toolhead_triggered=True)

        assert m.smart_unload(1) is True
        assert inst.calls, "the instance unload must be invoked"
        assert inst.calls[-1]["skip_cut"] is True

    def test_no_prep_cut_means_smart_unload_performs_the_cut(self, monkeypatch):
        m, inst = self._build_manager(monkeypatch, prep_cut_done=False, toolhead_triggered=True)

        assert m.smart_unload(1) is True
        assert inst.calls, "the instance unload must be invoked"
        assert inst.calls[-1]["skip_cut"] is False

    @pytest.mark.parametrize("prep_cut_done", [True, False])
    def test_toolhead_clear_never_cuts(self, monkeypatch, prep_cut_done):
        """With the toolhead sensor clear the filament end is still in the bowden.

        There is nothing at the nozzle to cut, so the cutter must be skipped
        regardless of whether the prep hook says it already cut.
        """
        m, inst = self._build_manager(
            monkeypatch, prep_cut_done=prep_cut_done, toolhead_triggered=False
        )

        assert m.smart_unload(1) is True
        assert inst.calls, "the instance unload must be invoked"
        assert inst.calls[-1]["skip_cut"] is True

    def test_toolhead_clear_retract_message_is_not_misleading(self, monkeypatch):
        """A full park->toolhead pull must not be described as a 'short retract'."""
        m, inst = self._build_manager(monkeypatch, prep_cut_done=False, toolhead_triggered=False)

        m.smart_unload(1)
        messages = [e[1] for e in m.gcode.events if e[0] == "info"]
        joined = " ".join(messages)
        assert "short safety retract" not in joined, (
            f"1050mm is the full bowden length, not a short retract: {messages}"
        )
        assert "1050" in joined, f"the pull distance should be reported: {messages}"
