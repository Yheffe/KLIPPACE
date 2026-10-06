"""The slot-to-toolhead feed must stop on the sensor, not run to a fixed length.

`_feed_to_toolhead_with_extruder_assist` had two halves with opposite designs.
Phase 2 (entry sensor -> nozzle) polled the sensor every 2mm, stopped the feed on
trigger, and capped the distance. Phase 1 (slot -> entry sensor) called
`execute_feed_with_retries`, which blocks until the ACE has run the *entire*
commanded length, and only then looked at the sensor.

That ordering is why a 1200mm feed could complete before the toolhead sensor was
ever consulted, producing this in the log:

    feed_filament_with_wait_for_response() completed -> length=1200.0mm, result_code=0
    Feed timeout for 1200.0mm after 40.0 seconds

and why a failure left the filament at an unknown point in a 1050mm bowden - which
is what made a retry unsafe, since the recovery only retracts 150mm.

Phase 1 now uses `_feed_until_sensor`, which stops the feed the moment the sensor
trips. These tests pin the sequencing, and in particular that success is decided by
our own sensor reading rather than by the ACE's response code: nothing in this
codebase had ever interrupted a feed before, so what the firmware reports for an
intentionally halted feed is unknown and must not be load-bearing.
"""

from __future__ import annotations

import pytest

from extras.ace.instance import AceInstance


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class _FakeGcode:
    def __init__(self):
        self.events = []

    def respond_info(self, msg):
        self.events.append(msg)


class _Clock:
    """Deterministic clock; each dwell() advances it."""

    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class _Harness:
    """Duck-typed AceInstance carrying only what the feed helpers touch."""

    def __init__(self, *, sensor_after_seconds=None, feed_response=None,
                 forbidden_times=0, timeout_s=10.0):
        self.instance_num = 0
        self.gcode = _FakeGcode()
        self.clock = _Clock()
        self.sensor_after = sensor_after_seconds
        self.timeout_s = timeout_s
        self.events = []

        self._forbidden_left = forbidden_times
        self._feed_response = feed_response
        self._sensor = False

        # Settle the sensor against the starting clock. Without this an
        # "already triggered at t=0" setup would not be visible until the first
        # dwell(), so the pre-check would miss it.
        self._tick()

        # _feed() is called by the helper; capture it and emulate the callback.
        self.feed_calls = []

    # -- collaborators -----------------------------------------------------
    def wait_ready(self):
        self.events.append("wait_ready")

    def dwell(self, delay=0.0):
        self.clock.advance(delay if delay else 0.1)
        self._tick()

    def _tick(self):
        if self.sensor_after is not None and self.clock.t >= self.sensor_after:
            self._sensor = True

    def _feed(self, slot, length, speed, callback=None):
        self.feed_calls.append((slot, length, speed))
        self.events.append("feed")
        if self._forbidden_left > 0:
            self._forbidden_left -= 1
            if callback:
                callback({"code": 1, "msg": "FORBIDDEN"})
        elif self._feed_response is not None:
            if callback:
                callback(self._feed_response)

    def _stop_feed(self, slot):
        self.events.append("stop_feed")

    def _sensor_fn(self):
        return self._sensor

    def _now(self):
        return self.clock.t


@pytest.fixture
def feed_harness(monkeypatch):
    """Patch time.time so the helpers use the deterministic clock."""
    import extras.ace.instance as mod

    def _make(**kwargs):
        h = _Harness(**kwargs)
        monkeypatch.setattr(mod.time, "time", h._now)
        return h

    return _make


def _run_feed(h, **overrides):
    """Run the real _feed_until_sensor against the harness.

    Both real methods are bound to the harness, so the loop under test is the
    shipped implementation rather than a copy of it.
    """
    import types

    h._poll_feed_until_sensor = types.MethodType(
        AceInstance._poll_feed_until_sensor, h
    )
    kwargs = {
        "local_slot": 0,
        "feed_length": 1200.0,
        "feed_speed": 60.0,
        "sensor_fn": h._sensor_fn,
        "timeout_s": overrides.pop("timeout_s", h.timeout_s),
    }
    kwargs.update(overrides)
    return AceInstance._feed_until_sensor(h, **kwargs)


# --------------------------------------------------------------------------
# the loop stops on the sensor
# --------------------------------------------------------------------------

class TestClosedLoopFeed:
    def test_sensor_trigger_stops_the_feed(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1003.0)   # ~3s in
        out = _run_feed(h)

        assert out["triggered"] is True, out
        assert out["reason"] == "sensor"
        assert "stop_feed" in h.events, (
            "the feed must be stopped when the sensor trips, not left running"
        )

    def test_feed_is_issued_before_the_poll_loop(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1001.0)
        _run_feed(h)
        assert h.events.index("feed") < h.events.index("stop_feed")
        assert h.feed_calls == [(0, 1200.0, 60.0)]

    def test_stop_happens_only_once(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1001.0)
        _run_feed(h)
        assert h.events.count("stop_feed") == 1, h.events

    def test_elapsed_reflects_the_time_to_trigger(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1002.0)
        out = _run_feed(h)
        assert 1.0 <= out["elapsed"] <= 3.0, out

    def test_immediate_trigger_does_not_feed_needlessly(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1000.0)
        out = _run_feed(h)
        assert out["triggered"] is True
        assert out["elapsed"] <= 1.0

    def test_timeout_stops_the_feed_too(self, feed_harness):
        """A failed feed must not be left running."""
        h = feed_harness(sensor_after_seconds=None, timeout_s=3.0)
        out = _run_feed(h)
        assert out["triggered"] is False
        assert out["reason"] == "timeout"
        assert "stop_feed" in h.events, (
            "an untriggered feed must be stopped, or filament keeps being pushed "
            "at a jam"
        )

    def test_already_triggered_issues_no_feed_at_all(self, feed_harness):
        """An already-satisfied sensor must not be fed into.

        The toolchange path passes check_pre_condition=False, so nothing upstream
        rejects an already-loaded toolhead. Feeding here would push filament with
        nowhere to go - the same over-feed the closed loop exists to prevent.
        """
        h = feed_harness(sensor_after_seconds=1000.0)   # triggered from the start
        out = _run_feed(h)

        assert out["triggered"] is True
        assert out["reason"] == "already-triggered"
        assert h.feed_calls == [], (
            f"no feed command may be issued when the sensor is already set: {h.feed_calls}"
        )
        assert "stop_feed" not in h.events, (
            "nothing was started, so there is nothing to stop"
        )


# --------------------------------------------------------------------------
# success must not hinge on the ACE's response code
# --------------------------------------------------------------------------

class TestResponseCodeIsNotAuthoritative:
    def test_success_despite_a_nonzero_stop_response(self, feed_harness):
        """The firmware's reply to an interrupted feed is unknown, so ignore it.

        The feed's own response is delivered through the callback. If a stop
        produced a non-zero code and we trusted it, a perfectly good feed would
        be reported as a failure.
        """
        h = feed_harness(sensor_after_seconds=1001.0,
                         feed_response={"code": 1, "msg": "STOPPED"})
        out = _run_feed(h)
        assert out["triggered"] is True, (
            f"a sensor trigger must win over the feed's response code: {out}"
        )

    def test_success_with_no_response_at_all(self, feed_harness):
        """A firmware that never answers must not fail a good feed."""
        h = feed_harness(sensor_after_seconds=1001.0, feed_response=None)
        out = _run_feed(h)
        assert out["triggered"] is True, out

    def test_success_when_the_response_arrives_after_the_stop(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1000.5,
                         feed_response={"code": 1, "msg": "interrupted"})
        assert _run_feed(h)["triggered"] is True

    def test_unknown_code_alone_does_not_fail_the_feed(self, feed_harness):
        """An unrecognised code must not be invented into a hard failure.

        Only FORBIDDEN has a defined meaning here. Anything else is surfaced for
        diagnosis and left to the timeout, rather than failing a feed that may be
        perfectly good.
        """
        h = feed_harness(sensor_after_seconds=1003.0,
                         feed_response={"code": 2, "msg": "WEIRD"})
        out = _run_feed(h)
        assert out["triggered"] is True, (
            f"a sensor trigger must win over an unrecognised code: {out}"
        )

    def test_unknown_code_is_reported_once_then_kept_for_the_timeout(self, feed_harness):
        h = feed_harness(sensor_after_seconds=None, timeout_s=2.0,
                         feed_response={"code": 2, "msg": "WEIRD"})
        out = _run_feed(h)

        assert out["triggered"] is False
        assert out["reason"] == "timeout"
        assert out.get("response") == "WEIRD", (
            "the timeout should carry the code that was seen, for diagnosis"
        )
        mentions = [m for m in h.gcode.events if "WEIRD" in m]
        assert len(mentions) == 1, (
            f"an unexpected code should be logged once, not every poll: {mentions}"
        )


# --------------------------------------------------------------------------
# refusals that arrive before completion are still errors
# --------------------------------------------------------------------------

class TestFeedRefusals:
    def test_forbidden_is_retried(self, feed_harness):
        # The sensor must trip well after the 1s retry backoff, otherwise the
        # retry's pre-check correctly notices filament has arrived and skips the
        # second feed - which is right, but not what this test is measuring.
        h = feed_harness(sensor_after_seconds=1005.0, forbidden_times=1)
        out = _run_feed(h)
        assert out["triggered"] is True, out
        assert len(h.feed_calls) == 2, (
            f"FORBIDDEN should be retried, got {len(h.feed_calls)} feed(s)"
        )

    def test_retry_skips_the_feed_if_filament_arrives_during_the_backoff(
        self, feed_harness
    ):
        """FORBIDDEN means "busy", so filament may land while we wait.

        Re-commanding a feed then would push filament that has nowhere to go, so
        the pre-check must win over the retry.
        """
        h = feed_harness(sensor_after_seconds=1000.5, forbidden_times=1)
        out = _run_feed(h)

        assert out["triggered"] is True
        assert out["reason"] == "already-triggered", out
        assert len(h.feed_calls) == 1, (
            f"the retry must not re-feed once the sensor is satisfied: {h.feed_calls}"
        )

    def test_forbidden_is_the_only_retried_code(self, feed_harness):
        """A single retry loop must not fire for unrelated codes."""
        h = feed_harness(sensor_after_seconds=1001.0,
                         feed_response={"code": 3, "msg": "NOT_FORBIDDEN"})
        _run_feed(h)
        assert len(h.feed_calls) == 1, (
            f"only FORBIDDEN should trigger another attempt: {len(h.feed_calls)}"
        )

    def test_forbidden_exhaustion_raises_rather_than_looping_forever(self, feed_harness):
        h = feed_harness(sensor_after_seconds=None, forbidden_times=999)
        with pytest.raises(ValueError) as e:
            _run_feed(h)
        assert "forbidden" in str(e.value).lower()
        assert len(h.feed_calls) <= 6, (
            f"must give up after MAX_RETRIES, not loop: {len(h.feed_calls)}"
        )

    def test_wait_ready_before_each_attempt(self, feed_harness):
        h = feed_harness(sensor_after_seconds=1001.0, forbidden_times=1)
        _run_feed(h)
        assert h.events.count("wait_ready") >= 2, (
            "the ACE must be ready before commanding a feed, each attempt"
        )


# --------------------------------------------------------------------------
# the caller actually uses it
# --------------------------------------------------------------------------

class TestPhaseOneUsesClosedLoop:
    SRC = None

    @classmethod
    def _src(cls):
        if cls.SRC is None:
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "extras" / "ace" / "instance.py"
            cls.SRC = p.read_text()
        return cls.SRC

    def _phase_one(self):
        """The slot -> entry-sensor half of the function.

        Both phases live in one function, so the slice is bounded at the Phase 2
        comment. Asserting over the whole function would wrongly flag Phase 2's
        restart path, which legitimately still uses the blocking helper because
        that feed is already bounded by the entry sensor.
        """
        src = self._src()
        start = src.index("def _feed_to_toolhead_with_extruder_assist")
        phase_two = src.index("# Phase 2:", start)
        return src[start:phase_two]

    def test_phase_one_calls_the_closed_loop_helper(self):
        assert "_feed_until_sensor(" in self._phase_one()

    def test_phase_one_no_longer_blocks_for_the_whole_length(self):
        assert "execute_feed_with_retries" not in self._phase_one(), (
            "Phase 1 is open-loop again: it will run the full commanded length "
            "before looking at the sensor"
        )

    def test_phase_two_still_uses_the_bounded_helper(self):
        """Phase 2's restart path feeds into a sensor-bounded region, so the
        blocking helper is still the right tool there."""
        assert "execute_feed_with_retries" in self._src()


class TestPhaseTwoDiagnosability:
    """The cap message must name the likely cause, which this change altered.

    Before the closed loop, Phase 1 over-fed and Phase 2 only nudged the filament
    the last 14-18mm, so `max_entry_to_nozzle_length` was never reached (0
    occurrences across the logs). Phase 2 now does the real entry-to-nozzle move,
    so the cap can legitimately bind on a healthy path - and the old message
    ("Check for jam, alignment, or obstruction") would send the reader hunting for
    a blockage that is not there.
    """

    @classmethod
    def _cap_message(cls):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "extras" / "ace" / "instance.py").read_text()
        marker = "Filament failed to reach nozzle sensor after"
        start = src.index(marker)
        return src[start:start + 700]

    def test_message_names_the_config_remedy(self):
        msg = self._cap_message()
        assert "max_entry_to_nozzle_length" in msg, (
            f"the cap message must name the setting to raise: {msg}"
        )

    def test_message_does_not_claim_a_jam_is_the_only_cause(self):
        msg = self._cap_message()
        assert "Either" in msg or "or " in msg, (
            f"the message should present both causes, not assert a jam: {msg}"
        )

    def test_cap_still_stops_the_feed_before_raising(self):
        """Whatever the cause, an over-long assist must not keep pushing."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "extras" / "ace" / "instance.py").read_text()
        start = src.index("if accumulated_extruded >= self.max_entry_to_nozzle_length:")
        # Bounded at the next loop rather than a fixed character count: the
        # explanatory comment above the raise already outgrew a 400-char window.
        end = src.index("self._extruder_move(step_chunk", start)
        window = src[start:end]
        assert "_stop_feed" in window, window
        assert "raise ValueError" in window, window
        assert window.index("_stop_feed") < window.index("raise ValueError"), (
            "the feed must be stopped before raising, or it keeps pushing "
            "at whatever is blocking it"
        )
