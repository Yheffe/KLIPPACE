"""Render-time checks for every shipped gcode macro.

A config typo that only bites at runtime is expensive: this repo has already had
one whole-config outage from a literal Jinja delimiter pair written inside a
comment, and one safety guard (``_BLOBIFIER_SAFE_DESCEND``) sit inert for weeks
because nothing ever rendered it.

These tests do two things:

* **Parse** every ``[gcode_macro]`` body with Klipper's own Jinja settings.  A
  syntax error here means the *entire* printer config fails to load, so this is
  worth pinning for every macro, not just the ones we can fully render.
* **Render** the handful of macros whose full dependency set is modelled, so
  that expression-level traps (reaching through a missing printer object) are
  caught too.  Those are opt-in per macro; rendering everything would need a
  stub for every printer object and would drown in false positives.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2", reason="jinja2 is a declared dependency (requirements.txt)")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIRS = [REPO_ROOT / "config", REPO_ROOT / "VORON"]

# Klipper builds its environment like this -- see klippy/extras/gcode_macro.py.
# The single-brace delimiters matter: a literal brace pair in a comment is still
# parsed as template syntax.
def _klipper_env():
    env = jinja2.Environment("{%", "%}", "{", "}")
    env.filters.setdefault("round", round)
    return env


def _cfg_files():
    files = []
    for d in CONFIG_DIRS:
        files.extend(sorted(d.rglob("*.cfg")))
    return files


def _strip_comments(text: str) -> str:
    """Strip '#' comments the way Klipper does before Jinja ever sees the text.

    ``klippy/configfile.py:_parse_config`` does, for every line::

        pos = line.find('#')
        if pos >= 0:
            line = line[:pos]

    This matters for the tests below: commented-out macro blocks in these config
    files contain Jinja expressions, and without this step the extractor would
    hand them to Jinja and report syntax errors that Klipper never sees.
    """
    return "\n".join(line.split("#", 1)[0] for line in text.split("\n"))


def _macro_bodies(path: Path):
    """Yield (kind, name, body) for every [gcode_macro]/[delayed_gcode] in a cfg file.

    Bodies are comment-stripped exactly as Klipper would parse them.
    """
    text = _strip_comments(path.read_text(errors="replace"))
    for m in re.finditer(
        r"^\[(gcode_macro|delayed_gcode)\s+(\S+)\](.*?)(?=^\[|\Z)",
        text, re.S | re.M,
    ):
        kind, name, section = m.group(1), m.group(2), m.group(3)
        gcode_block = None
        for opt in ("gcode", "initial_duration"):
            b = re.search(r"^%s:\s*$(.*)" % opt, section, re.S | re.M)
            if b:
                gcode_block = b.group(1)
                break
        if gcode_block is None:
            continue
        yield kind, name, gcode_block


ALL_MACROS = [
    (path, kind, name, body)
    for path in _cfg_files()
    for kind, name, body in _macro_bodies(path)
]


def _id(param):
    path, kind, name, _ = param
    return f"{path.relative_to(REPO_ROOT)}::{name}"


class TestEveryMacroParses:
    """A syntax error here takes out the whole printer config."""

    def test_macros_were_found(self):
        assert len(ALL_MACROS) > 50, (
            f"only found {len(ALL_MACROS)} macros - the extractor is probably broken"
        )

    @pytest.mark.parametrize("macro", ALL_MACROS, ids=_id)
    def test_body_compiles(self, macro):
        path, kind, name, body = macro
        env = _klipper_env()
        try:
            env.from_string(body)
        except jinja2.TemplateSyntaxError as e:
            pytest.fail(
                f"{path.relative_to(REPO_ROOT)} [{kind} {name}] does not compile:\n"
                f"  line {e.lineno}: {e.message}\n"
                f"  source: {(e.source or '').strip()}\n"
                f"  Note: Klipper uses single braces for expressions, so a "
                f"literal delimiter pair inside a comment is still parsed."
            )

    def test_commented_out_config_is_not_parsed(self):
        """Comment stripping is what makes large commented-out macro blocks safe.

        These config files carry whole disabled macros in comments (for example
        the G9111 block in acepro.cfg) which contain Jinja expressions.  Klipper
        removes them before parsing, so they must never reach Jinja here either.
        """
        src = (
            "[gcode_macro demo]\n"
            "gcode:\n"
            "    G28\n"
            "# [gcode_macro disabled]\n"
            "# gcode:\n"
            "#     {% if broken %}\n"
            "    M400\n"
        )
        stripped = _strip_comments(src)
        assert "{%" not in stripped, stripped
        assert "G28" in stripped and "M400" in stripped

    def test_extractor_strips_comments_from_real_configs(self):
        bodies = [body for _, _, _, body in ALL_MACROS]
        offenders = [
            b[:120] for b in bodies
            if any(tok in b for tok in ("{%", "%}"))
            and _strip_comments(b) != b
        ]
        assert not offenders, f"comment stripping incomplete: {offenders[:3]}"


# --------------------------------------------------------------------------
# opt-in full rendering, for macros whose dependencies are modelled
# --------------------------------------------------------------------------

class _Raise(Exception):
    pass


class _Status:
    """Fake of Klipper's GetStatusWrapper: raises KeyError for unknown objects,
    which Jinja turns into Undefined, making `is defined` behave as in Klipper."""

    def __init__(self, objects):
        self._o = objects

    def __getitem__(self, key):
        k = str(key).strip()
        if k not in self._o:
            raise KeyError(key)
        return self._o[k]

    def __contains__(self, key):
        return str(key).strip() in self._o

    def __iter__(self):
        return iter(self._o)


class _Tracker:
    def __init__(self):
        self.raised = []
        self.info = []
        self.gcode = []


def _render(cfg_rel, macro_name, objects, params=None):
    """Render one macro body from a config file. Returns (text, tracker)."""
    from tests.test_line_purge_guard import _macro_body  # reuse the extractor

    body = _macro_body(REPO_ROOT / cfg_rel, macro_name)
    env = _klipper_env()
    t = _Tracker()
    ctx = {
        "printer": _Status(objects),
        "params": params or {},
        "rawparams": "",
        "action_respond_info": lambda m: t.info.append(m) or "",
        "action_raise_error": lambda m: t.raised.append(m) or (_ for _ in ()).throw(_Raise(m)),
        "action_emergency_stop": lambda m="": t.raised.append(m) or "",
        "action_call_remote_method": lambda method, **kw: "",
    }
    try:
        return env.from_string(body).render(ctx), t
    except _Raise:
        return None, t


def _minimal_objects():
    """Bare-minimum printer stub.

    Includes each modelled macro's own ``gcode_macro`` object, because Klipper
    macros read their own variables that way (``printer["gcode_macro X"]``).
    """
    return {
        "toolhead": {
            "position": {"x": 10.0, "y": 10.0, "z": 5.0},
            "axis_maximum": {"x": 355.0, "y": 360.0, "z": 230.0},
            "max_velocity": 300.0,
            "homed_axes": "xyz",
        },
        "extruder": {"temperature": 25.0, "target": 0},
        "fan": {"speed": 0.0},
        "output_pin ACE_Pro": {"value": 1.0},
        "save_variables": {"variables": {"ace_current_index": -1, "ace_filament_pos": "bowden"}},
        "gcode_macro _ACE_STATE": {"active": -1, "startup_toolchange": 0},
        "gcode_macro ACE_ON_PRINT_START": {
            "purge_same_tool": 50.0,
            "purge_different_tool": 100.0,
            "requested_tool": 0,
        },
    }


class TestAcePrintStartIsPortable:
    """`ACE_ON_PRINT_START` must not explode on a machine with no ACE pin.

    It reads the pin as ``printer["output_pin ACE_Pro"].value|default(1)``.  The
    subscript yields Undefined for a missing object, and touching ``.value`` on
    Undefined raises UndefinedError -- a trailing ``|default()`` cannot rescue it,
    because the exception happens while evaluating the expression, before the
    filter runs.  On a machine without ACE this turns an unrelated macro call into
    a hard config error.
    """

    CFG = "config/voron24/ace_voron24_macros.cfg"
    MACRO = "ACE_ON_PRINT_START"

    def test_present_pin_renders(self):
        _, t = _render(self.CFG, self.MACRO, _minimal_objects())
        assert not t.raised

    def test_missing_pin_does_not_raise_undefined_error(self):
        objects = _minimal_objects()
        del objects["output_pin ACE_Pro"]
        try:
            _, t = _render(self.CFG, self.MACRO, objects)
        except jinja2.UndefinedError as e:
            pytest.fail(
                "ACE_ON_PRINT_START dereferences the ACE pin without an "
                f"`is defined` test, so it breaks on a machine without ACE: {e}"
            )


class TestPrintEndIsPortable:
    CFG = "VORON/printer.cfg"
    MACRO = "PRINT_END"

    def test_missing_pin_does_not_raise_undefined_error(self):
        objects = _minimal_objects()
        del objects["output_pin ACE_Pro"]
        try:
            _render(self.CFG, self.MACRO, objects)
        except jinja2.UndefinedError as e:
            pytest.fail(
                f"PRINT_END dereferences the ACE pin without an `is defined` test: {e}"
            )


class TestGenericMacrosArePortable:
    """Same trap in the generic ACE config set, which ships for other machines."""

    CFG = "config/acepro.cfg"

    @pytest.mark.parametrize("macro", ["SFS_ENABLE_ACE_ENCODER", "UPDATE_ACE_ENCODER"])
    def test_missing_pin_does_not_raise_undefined_error(self, macro):
        objects = _minimal_objects()
        del objects["output_pin ACE_Pro"]
        try:
            _render(self.CFG, macro, objects)
        except jinja2.UndefinedError as e:
            pytest.fail(
                f"{macro} dereferences the ACE pin without an `is defined` test: {e}"
            )

    @pytest.mark.parametrize("macro", ["SFS_ENABLE_ACE_ENCODER", "UPDATE_ACE_ENCODER"])
    def test_present_pin_renders(self, macro):
        _, t = _render(self.CFG, macro, _minimal_objects())
        assert not t.raised, t.raised
