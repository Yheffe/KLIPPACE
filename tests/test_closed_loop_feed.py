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
                 forbidden_times=0, timeout_s=10.0,
                 feed_response_after_seconds=None):
        self.instance_num = 0
        self.gcode = _FakeGcode()
        self.clock = _Clock()
        self._start_t = self.clock.t
        self.sensor_after = sensor_after_seconds
        self.timeout_s = timeout_s
        self.events = []

        self._forbidden_left = forbidden_times
        self._feed_response = feed_response
        # A real feed completes some seconds after it is issued, not instantly.
        # When set, the response is delivered once the simulated clock reaches
        # this absolute time instead of at _feed() time.
        self._feed_response_after = feed_response_after_seconds
        self._pending_callback = None
        self._response_delivered = False
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

    # Guard against an unterminating loop. The polling helpers are bounded by a
    # timeout, so a mutated or broken timeout branch would spin forever -- and
    # because this clock is simulated, "forever" means the test run hangs
    # instead of reporting a failure. Verified by mutation: deleting the
    # timeout check left the suite spinning rather than failing. 120s of
    # simulated time is far beyond every timeout these tests use, so tripping
    # this bound can only mean the loop is not terminating.
    MAX_SIMULATED_SECONDS = 120.0

    def dwell(self, delay=0.0):
        self.clock.advance(delay if delay else 0.1)
        if self.clock.t - self._start_t > self.MAX_SIMULATED_SECONDS:
            raise AssertionError(
                f"feed loop ran for more than {self.MAX_SIMULATED_SECONDS:.0f}s "
                f"of simulated time without finishing; the timeout branch is "
                f"not terminating"
            )
        self._tick()

    def _tick(self):
        if self.sensor_after is not None and self.clock.t >= self.sensor_after:
            self._sensor = True
        if (self._pending_callback is not None
                and not self._response_delivered
                and self._feed_response_after is not None
                and self.clock.t >= self._feed_response_after):
            self._response_delivered = True
            self._pending_callback(self._feed_response)

    def _feed(self, slot, length, speed, callback=None):
        self.feed_calls.append((slot, length, speed))
        self.events.append("feed")
        if self._forbidden_left > 0:
            self._forbidden_left -= 1
            if callback:
                callback({"code": 1, "msg": "FORBIDDEN"})
        elif self._feed_response is not None:
            if self._feed_response_after is None:
                if callback:
                    callback(self._feed_response)
                self._response_delivered = True
            else:
                self._pending_callback = callback

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

    def test_sensor_poll_interval_keeps_overshoot_small(self, feed_harness):
        """Detection granularity *is* the overshoot budget.

        The loop only looks at the sensor once per poll, so filament keeps
        moving for up to one interval after the switch physically closes. At
        60mm/s the shipped 0.02s is 1.2mm; the 0.1s this used to be would be
        6.0mm, and 6mm of unplanned travel is enough to push the tip into the
        nozzle before Phase 2 starts.
        """
        from extras.ace.config import FEED_SENSOR_POLL_INTERVAL_S

        # Pin the budget itself. A self-referential timing assertion cannot do
        # this: any interval would satisfy "detected within N intervals".
        assert FEED_SENSOR_POLL_INTERVAL_S <= 0.05, (
            f"poll interval {FEED_SENSOR_POLL_INTERVAL_S}s allows more than 3mm "
            f"of overshoot at 60mm/s"
        )

        # And confirm the loop really notices within about one interval.
        h = feed_harness(
            sensor_after_seconds=1000.0 + FEED_SENSOR_POLL_INTERVAL_S * 1.5
        )
        out = _run_feed(h)

        assert out["triggered"] is True, out
        assert out["elapsed"] <= FEED_SENSOR_POLL_INTERVAL_S * 3, out

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

class TestFeedCompleteWithoutSensor:
    """A finished feed that never reached the sensor must not wait for the timeout.

    Observed on 2026-10-18, mid-print at a colour change: the ACE was commanded
    1200mm at 60mm/s (20s of travel, 40s timeout) and the entry sensor never
    tripped. The loop sat out the full 40s and only then handed over to
    feed-assist, which recovered it in 60s. The toolchange succeeded, but 20s
    were spent waiting for a feed that had already ended.

    A code-0 response means the ACE has finished the commanded length. Once that
    arrives with no sensor trip, further waiting cannot help.
    """

    def test_exits_before_the_timeout_when_the_feed_completes(self, feed_harness):
        h = feed_harness(
            sensor_after_seconds=None,          # never trips
            feed_response={"code": 0, "msg": "success"},
            feed_response_after_seconds=1002.0,  # ACE "finishes" after 2s
            timeout_s=10.0,
        )
        out = _run_feed(h)

        assert out["triggered"] is False, out
        assert out["reason"] == "feed-complete", out
        assert out["elapsed"] < 5.0, (
            f"waited {out['elapsed']:.1f}s for a feed the ACE had already "
            f"finished; the timeout should not be spent"
        )

    def test_a_late_sensor_trip_still_counts(self, feed_harness):
        """The grace period must not steal a trigger that is still settling."""
        h = feed_harness(
            sensor_after_seconds=1002.5,        # trips shortly after completion
            feed_response={"code": 0, "msg": "success"},
            feed_response_after_seconds=1002.0,
            timeout_s=10.0,
        )
        out = _run_feed(h)

        assert out["triggered"] is True, out
        assert out["reason"] == "sensor", out

    def test_reports_that_the_filament_is_not_moving(self, feed_harness):
        """The log must say why, not just that the sensor never tripped."""
        h = feed_harness(
            sensor_after_seconds=None,
            feed_response={"code": 0, "msg": "success"},
            feed_response_after_seconds=1002.0,
            timeout_s=10.0,
        )
        _run_feed(h)

        joined = " ".join(h.gcode.events)
        assert "feed complete" in joined, h.gcode.events
        assert "not moving" in joined, h.gcode.events


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


class TestPhaseTwoStartsItsOwnFeed:
    """Phase 2 must *start* a feed, because Phase 1 stops the one it had.

    Before the closed loop, Phase 1 left the ACE feeding and Phase 2 only called
    `_change_feed_speed()` to slow it down. Once Phase 1 began stopping the feed on
    the entry sensor, that call had nothing to modify - yet the ACE still answers
    code 0 to an update on a feed that is not running, so the old "not confirmed"
    fallback never fired and nothing pushed the filament.

    Observed 2026-10-18: `ACE link connected`, speed change acknowledged, and the
    extruder pulled the full 80mm cap without the nozzle sensor tripping. The
    filament was being dragged, not fed.
    """

    @classmethod
    def _dual_sensor_block(cls):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "extras" / "ace" / "instance.py").read_text()
        start = src.index("if self.manager.has_entry_sensor() and self.manager.has_nozzle_sensor():")
        end = src.index("# Single-sensor fallback", start)
        return src[start:end]

    def test_phase_two_issues_a_feed(self):
        block = self._dual_sensor_block()
        assert "self._feed(" in block, (
            "Phase 2 must start its own feed - Phase 1 already stopped the previous "
            "one, so there is nothing for a speed change to act on"
        )

    def test_phase_two_does_not_rely_on_a_speed_change_alone(self):
        block = self._dual_sensor_block()
        # Match the call, not the word: the comment above explains why the old
        # call was removed and would otherwise satisfy a bare substring check.
        assert "self._change_feed_speed(" not in block, (
            "Phase 2 cannot speed up a feed that Phase 1 already stopped; the ACE "
            "acks the update but nothing moves"
        )

    def test_phase_two_feed_is_bounded(self):
        """The new feed must be finite, or a missed sensor leaves the ACE pushing."""
        block = self._dual_sensor_block()
        assert "max_entry_to_nozzle_length + 50" in block, (
            "the Phase 2 feed length must be bounded by the entry-to-nozzle limit"
        )

    def test_phase_two_stops_the_feed_on_both_exits(self):
        block = self._dual_sensor_block()
        # one stop on the success path, one on the cap/failure path
        assert block.count("self._stop_feed(local_slot)") >= 2, (
            "both the success and the failure path must stop the feed"
        )


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
        return src[start:start + 1200]

    @classmethod
    def _phase_two_failure_block(cls):
        """Source from the link-state probe through the raise."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "extras" / "ace" / "instance.py").read_text()
        start = src.index("link = (")
        end = src.index("self._extruder_move(step_chunk", start)
        return src[start:end]

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

    def test_message_reports_the_ace_link_state(self):
        """A stopped ACE and an obstruction look identical from the outside.

        2026-10-18: the cap fired at 80mm with the speed change accepted and no
        obstruction, while the ACE was re-enumerating on USB. The extruder was
        very likely pulling filament that nothing was pushing - which grips
        nothing and slips, exactly like a jam. Without the link state in the
        message the two cannot be told apart after the fact.
        """
        block = self._phase_two_failure_block()
        assert "ACE link" in block, f"the failing path must report the link: {block}"
        assert "is_connected()" in block, (
            "the link state must be read from the serial manager, not guessed"
        )
        assert "DISCONNECTED" in block, (
            "a stopped ACE must be named as such, or it reads as a jam"
        )
        # And it must reach the operator, not just an internal variable.
        assert "{link}" in block, (
            "the link state has to be interpolated into the user-facing message"
        )

    def test_diagnostics_are_logged_before_raising(self):
        """The line has to be written, not just formatted into the exception."""
        block = self._phase_two_failure_block()
        assert "respond_info" in block, (
            "the Phase 2 diagnostics must be logged via respond_info so they "
            "reach klippy.log, not only raised as an exception"
        )
        assert block.index("respond_info") < block.index("raise ValueError"), (
            "log the diagnostic before raising, or it never reaches the log"
        )

    def test_diagnostics_do_not_come_from_logging_info(self):
        """logging.info never reaches klippy.log - the reason Phase 2 was opaque.

        `_change_feed_speed` reports through logging.info, so a rejected speed
        change leaves no trace in klippy.log. The new diagnostic must not repeat
        that mistake.
        """
        block = self._phase_two_failure_block()
        assert "logging.info" not in block, (
            "Phase 2 diagnostics must use respond_info, not logging.info"
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
