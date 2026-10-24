"""The dryer macros: unit conversion, chamber labelling, and the print-end stop.

Three bugs, all silent:

1. ``DRYER_STATUS`` printed ``dryer_remain_time`` as minutes.  The ACE reports
   ``duration`` in minutes but ``remain_time`` in **seconds** — the two are passed
   straight through from the status payload in ``protocol_ace2.py``, and both
   other consumers treat remain_time as seconds::

       serial_manager.py:  f"(target={target_temp}°C, remaining={remain_time}s)"

       KlipperScreen/acepro.py:  hours = remain_time // 3600

       commands.py cmd_ACE_GET_STATUS:  remain_min = int(dryer['remain_time']) // 60

   Observed live 2026-10-24: ``DRYER_STATUS`` reported ``Remaining: 14191 min``
   for a 240-minute cycle.  14191 seconds is 236 minutes, so the label was right
   about the number and wrong about the unit by a factor of 60.

2. ``DRYER_STATUS`` labelled the ACE's own temperature ``Chamber Temp``.  There
   are two unrelated probes: ``mmu.unit[].temp`` is the drying enclosure where
   the spools sit (``temperature_sensor ace_dryer``), while
   ``temperature_sensor chamber`` is the *printer's* heated chamber -- the one
   ``PRINT_START`` soaks to ``TARGET_CHAMBER``.  Observed live 2026-10-24 with the
   ACE at 34.0°C and the printer chamber at 22.8°C: an 11°C error in whichever
   reading you believed you were looking at.  They are now printed as separate,
   correctly named lines.

3. ``PRINT_END`` never stopped the dryer.  ``PRINT_START`` can start one from
   ``DRYER_TEMP`` / ``DRYER_MATERIAL``, and the default 240-minute cycle easily
   outlives the print, leaving the chamber heater running unattended.

These tests render the *real* macro bodies out of the configs with Klipper's own
Jinja delimiters (``{%``/``%}``/``{``/``}``), so a syntax error or a regression in
the arithmetic fails here rather than at the printer.  That matters because a
Jinja error in a macro is invisible until the macro is actually run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip(
    "jinja2", reason="jinja2 is a declared dependency (requirements.txt)"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PRINTER_CFG = REPO_ROOT / "VORON" / "printer.cfg"
ACE_MACROS_CFG = REPO_ROOT / "config" / "voron24" / "ace_voron24_macros.cfg"


def _macro_body(cfg_path: Path, name: str) -> str:
    """Extract the indented gcode body of a [gcode_macro NAME] section."""
    text = cfg_path.read_text()
    m = re.search(
        r"^\[gcode_macro %s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(name),
        text, re.S | re.M,
    )
    if not m:
        raise AssertionError(f"[gcode_macro {name}] not found in {cfg_path}")
    body = re.search(r"^gcode:\s*$(.*)", m.group(0), re.S | re.M)
    if not body:
        raise AssertionError(f"[gcode_macro {name}] has no gcode: body")
    return body.group(1)


class _PrinterStatus:
    """Fake of Klipper's GetStatusWrapper.

    ``__getitem__`` raises KeyError for unknown objects, exactly as the real
    wrapper does, so ``printer['x'] is defined`` is genuinely exercised.
    """

    def __init__(self, objects):
        self._objects = objects

    def __getitem__(self, key):
        sval = str(key).strip()
        if sval not in self._objects:
            raise KeyError(key)
        return self._objects[sval]

    def __contains__(self, key):
        return str(key).strip() in self._objects

    def __iter__(self):
        return iter(self._objects)


def _render(cfg_path: Path, name: str, objects, params=None):
    """Render a real macro body.  Returns (rendered, info_messages)."""
    env = jinja2.Environment("{%", "%}", "{", "}")
    env.filters.setdefault("round", round)
    template = env.from_string(_macro_body(cfg_path, name))

    info = []
    context = {
        "printer": _PrinterStatus(objects),
        "params": params or {},
        "action_respond_info": lambda msg: info.append(msg) or "",
        "action_raise_error": lambda msg: info.append("RAISE: " + msg) or "",
    }
    return template.render(context), info


def _unit(**overrides):
    """One ACE Pro unit as mmu_shim.get_status() reports it."""
    unit = {
        "name": "ACE Pro 0",
        "temp": 32.5,
        "dryer_status": "stop",
        "dryer_target_temp": 0,
        "dryer_remain_time": 0,
    }
    unit.update(overrides)
    return unit


def _dryer_objects(unit, chamber_c=22.79, **overrides):
    """Printer status for DRYER_STATUS: one ACE unit plus a chamber sensor.

    The two temperatures are deliberately far apart, so a test that confuses
    them cannot accidentally pass.
    """
    objects = {
        "mmu": {"unit": [unit]},
        "temperature_sensor chamber": {"temperature": chamber_c},
    }
    objects.update(overrides)
    return objects


def _status_report(info):
    """The line DRYER_STATUS prints for the ACE unit itself."""
    lines = [m for m in info if m.startswith("ACE Dryer:")]
    assert len(lines) == 1, f"expected one ACE dryer line, got {info}"
    return lines[0]


def _chamber_report(info):
    """The line DRYER_STATUS prints for the printer chamber."""
    lines = [m for m in info if m.startswith("Printer Chamber:")]
    assert len(lines) == 1, f"expected one chamber line, got {info}"
    return lines[0]


# --------------------------------------------------------------------------
# DRYER_STATUS: units
# --------------------------------------------------------------------------


class TestRemainingTimeIsConvertedFromSeconds:
    def test_a_240_minute_cycle_reports_240_minutes_not_14400(self):
        """THE BUG: 14400 seconds was printed as "14400 min"."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            {"mmu": {"unit": [_unit(dryer_status="drying",
                                    dryer_target_temp=45,
                                    dryer_remain_time=14400)]}},
        )
        line = _status_report(info)
        assert "4h 00min" in line, line
        assert "14400" not in line, (
            f"raw seconds leaked into the output: {line}"
        )

    def test_the_observed_live_value_reads_as_hours(self):
        """Live 2026-10-24: 14191 was reported as "14191 min"."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            {"mmu": {"unit": [_unit(dryer_status="drying",
                                    dryer_target_temp=50,
                                    dryer_remain_time=14191)]}},
        )
        line = _status_report(info)
        # 14191s = 236min = 3h 56min
        assert "3h 56min" in line, line
        assert "14191" not in line, line

    def test_sub_hour_remainders_stay_in_minutes(self):
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            {"mmu": {"unit": [_unit(dryer_status="drying",
                                    dryer_remain_time=600)]}},
        )
        line = _status_report(info)
        assert "10 min" in line, line
        assert "h " not in line.split("Remaining:")[1], (
            f"a 10-minute remainder should not show hours: {line}"
        )

    def test_the_minute_component_is_zero_padded(self):
        """3h 5min reads as 3h 05min so the column does not jump."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            {"mmu": {"unit": [_unit(dryer_status="drying",
                                    dryer_remain_time=11100)]}},
        )
        line = _status_report(info)
        assert "3h 05min" in line, line

    def test_zero_seconds_is_zero_minutes(self):
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            _dryer_objects(_unit(dryer_status="stop", dryer_remain_time=0)),
        )
        assert "ACE Dryer:" in _status_report(info)


class TestIdleDryerShowsNoStaleTime:
    def test_a_stopped_dryer_does_not_report_a_leftover_remainder(self):
        """After a cycle finishes the ACE can leave remain_time behind; showing
        it would imply a cycle is still running."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            {"mmu": {"unit": [_unit(dryer_status="stop",
                                    dryer_remain_time=5400)]}},
        )
        line = _status_report(info)
        assert "n/a (idle)" in line, line
        assert "90 min" not in line, line

    def test_status_and_target_are_still_reported(self):
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            _dryer_objects(_unit(dryer_status="drying",
                                 dryer_target_temp=55,
                                 dryer_remain_time=600)),
        )
        line = _status_report(info)
        assert "32.5" in line, line          # ACE temperature
        assert "55" in line, line            # dryer target
        assert "DRYING" in line, line        # status, upper-cased


class TestChamberIsThePrinterNotTheAce:
    """The ACE's own chamber and the printer enclosure are different sensors.

    ``mmu.unit[].temp`` is the drying enclosure where the spools sit
    (``temperature_sensor ace_dryer``).  The printer's heated chamber is
    ``temperature_sensor chamber`` and is the one PRINT_START soaks to
    TARGET_CHAMBER.  Labelling the ACE reading "Chamber Temp" pointed the
    operator at the wrong box.
    """

    def test_both_temperatures_are_reported(self):
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            _dryer_objects(_unit(temp=34.0), chamber_c=22.8),
        )
        assert "34.0" in _status_report(info), info
        assert "22.8" in _chamber_report(info), info

    def test_the_ace_reading_is_not_labelled_as_the_chamber(self):
        """THE BUG: 34.0C from the ACE was presented as the chamber temp."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            _dryer_objects(_unit(temp=34.0), chamber_c=22.8),
        )
        assert "Chamber" not in _status_report(info), (
            f"the ACE temperature must not be presented as the chamber: {info}"
        )
        assert "34.0" not in _chamber_report(info), (
            f"the chamber line must not show the ACE temperature: {info}"
        )

    def test_the_two_are_printed_independently(self):
        """Changing one must not move the other."""
        _, info = _render(
            ACE_MACROS_CFG, "DRYER_STATUS",
            _dryer_objects(_unit(temp=60.0), chamber_c=45.5),
        )
        assert "60.0" in _status_report(info), info
        assert "45.5" in _chamber_report(info), info
        assert "45.5" not in _status_report(info), info
        assert "60.0" not in _chamber_report(info), info

    def test_a_missing_chamber_sensor_does_not_break_the_report(self):
        """Not every KLIPPACE machine has a chamber probe."""
        objects = _dryer_objects(_unit(temp=34.0))
        objects.pop("temperature_sensor chamber")

        _, info = _render(ACE_MACROS_CFG, "DRYER_STATUS", objects)

        assert "34.0" in _status_report(info), info
        assert "n/a" in _chamber_report(info), (
            f"say the probe is missing rather than showing 0.0C: {info}"
        )


class TestStatusSurvivesAMissingMmu:
    def test_no_mmu_object_falls_back_instead_of_undefined_error(self):
        """``printer['x']|default()`` cannot rescue an UndefinedError raised
        while evaluating, so the macro must test ``is defined`` first."""
        rendered, info = _render(ACE_MACROS_CFG, "DRYER_STATUS", {})
        assert "ACE_GET_STATUS" in rendered, (
            f"expected the fallback command, got {rendered!r}"
        )
        assert not [m for m in info if m.startswith("ACE Dryer:")]

    def test_an_mmu_without_units_falls_back_the_same_way(self):
        rendered, _ = _render(ACE_MACROS_CFG, "DRYER_STATUS", {"mmu": {}})
        assert "ACE_GET_STATUS" in rendered, rendered

    def test_an_empty_unit_list_falls_back_the_same_way(self):
        rendered, _ = _render(
            ACE_MACROS_CFG, "DRYER_STATUS", {"mmu": {"unit": []}}
        )
        assert "ACE_GET_STATUS" in rendered, rendered


# --------------------------------------------------------------------------
# PRINT_END: stop the dryer
# --------------------------------------------------------------------------


def _print_end_objects(mmu=None, **overrides):
    objects = {
        "toolhead": {
            # Dicts, not a list: PRINT_END reads th.position.x, and Jinja falls
            # back to getitem for attribute access on a mapping.
            "position": {"x": 175.0, "y": 175.0, "z": 50.0, "e": 0.0},
            "axis_maximum": {"x": 350.0, "y": 350.0, "z": 330.0},
        },
        "output_pin ACE_Pro": {"value": 1.0},
        "save_variables": {"variables": {"ace_current_index": 0}},
    }
    if mmu is not None:
        objects["mmu"] = mmu
    objects.update(overrides)
    return objects


class TestPrintEndStopsTheDryer:
    def test_a_running_dryer_is_stopped(self):
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END",
            _print_end_objects(
                mmu={"unit": [_unit(dryer_status="drying",
                                    dryer_target_temp=45,
                                    dryer_remain_time=7200)]}
            ),
        )
        assert "DRYER_STOP" in rendered, (
            "a 2-hour cycle would outlive the print and keep heating the chamber"
        )

    def test_an_idle_dryer_is_left_alone(self):
        """A user drying spools by hand must not get a spurious stop every job."""
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END",
            _print_end_objects(mmu={"unit": [_unit(dryer_status="stop")]}),
        )
        assert "DRYER_STOP" not in rendered, (
            "the dryer was not running, so there is nothing to stop"
        )

    def test_the_stop_is_emitted_when_any_instance_is_drying(self):
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END",
            _print_end_objects(
                mmu={"unit": [_unit(dryer_status="stop"),
                              _unit(dryer_status="drying",
                                    dryer_remain_time=3600)]}
            ),
        )
        assert "DRYER_STOP" in rendered, (
            "one drying instance is enough to warrant a stop"
        )

    def test_a_machine_without_mmu_is_unaffected(self):
        rendered, _ = _render(PRINTER_CFG, "PRINT_END", _print_end_objects())
        assert "DRYER_STOP" not in rendered
        # ...and the rest of the shutdown still happens.
        assert "TURN_OFF_HEATERS" in rendered, rendered
        assert "M84" in rendered, rendered


class TestTheStopCannotDelayTheShutdown:
    def test_the_stop_comes_after_the_heaters_are_off(self):
        """If stopping the dryer misbehaves, heaters must already be off."""
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END",
            _print_end_objects(
                mmu={"unit": [_unit(dryer_status="drying",
                                    dryer_remain_time=3600)]}
            ),
        )
        assert rendered.index("TURN_OFF_HEATERS") < rendered.index("DRYER_STOP"), (
            "the dryer stop must not run before the heaters are shut down"
        )

    def test_the_toolhead_still_parks_afterwards(self):
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END",
            _print_end_objects(
                mmu={"unit": [_unit(dryer_status="drying",
                                    dryer_remain_time=3600)]}
            ),
        )
        assert "G0 X175.0 Y354.0" in rendered, rendered
        assert rendered.index("DRYER_STOP") < rendered.index("G0 X175.0 Y354.0"), (
            "parking is part of the shutdown and must follow the dryer stop"
        )
        assert "M84" in rendered, rendered


class TestPrintEndStillRenders:
    def test_the_whole_macro_evaluates(self):
        """A Jinja error here would only surface at the end of a real print."""
        rendered, _ = _render(
            PRINTER_CFG, "PRINT_END", _print_end_objects()
        )
        assert "_ACE_HANDLE_PRINT_END CUT_TIP=1" in rendered, rendered
        assert "BLOBIFIER_SERVO POS=in" in rendered, rendered
        assert "RESTORE_GCODE_STATE" in rendered, rendered
