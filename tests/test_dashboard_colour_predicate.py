"""The dashboard's "unknown slot" predicate must have exactly one definition.

The card swatch and the slot editor each need to know whether a slot's colour is
real or just the ACE module's "no colour data" sentinel. They used to answer that
question differently:

  isUnknownGate()      no colour AND no material     <- the swatch
  inline in the editor no material OR colour == #000000

So a genuinely black spool (colour ``#000000`` with a real material) was "unknown"
to the editor but not to the swatch. Clicking T3 opened the colour picker on white
while the swatch correctly showed black — reported 2026-10-05.

These tests evaluate the *real* `isUnknownGate` source lifted out of the shipped
JS, so the predicate itself cannot regress, and separately assert the editor still
delegates to it instead of growing a second copy.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

DASHBOARD_JS = (
    Path(__file__).resolve().parent.parent
    / "acepro-mmu-dashboard" / "web" / "klippace-tool-mapper.js"
)

node = shutil.which("node")


def _extract_function(name: str) -> str:
    """Return the full source of `function name(...) { ... }` by brace matching."""
    src = DASHBOARD_JS.read_text()
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % re.escape(name), src)
    if not m:
        raise AssertionError(f"function {name}() not found in {DASHBOARD_JS.name}")
    depth = 0
    for i in range(m.end() - 1, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
    raise AssertionError(f"unbalanced braces in {name}()")


def _editor_body() -> str:
    """Approximate body of openSlotEditor, enough to see how it builds the colour."""
    src = DASHBOARD_JS.read_text()
    i = src.index("async function openSlotEditor")
    return src[i:i + 6000]


@pytest.mark.skipif(node is None, reason="node is required to evaluate the shipped JS")
class TestUnknownPredicate:
    CASES = [
        # (color, material, expected, why)
        ("#000000", "PLA", False, "THE BUG: a black spool with a real material is real data"),
        ("#000000", "pla", False, "case-insensitive material"),
        ("#000000", "", True, "all-zero colour and no material is the sentinel"),
        ("#000000", "unknown", True, "explicit Unknown is the sentinel"),
        ("#000000", "Unknown", True, "case-insensitive Unknown"),
        ("", "", True, "no colour and no material"),
        ("", "PLA", False, "a material is known, so the slot is not unknown"),
        ("#23a3c7", "PLA", False, "ordinary colour"),
        ("#23a3c7", "unknown", False, "AND, not OR: colour present means not the sentinel"),
        ("#ffffff", "unknown", False, "white is a real colour"),
        ("#000001", "unknown", False, "near-black is still a real colour"),
    ]

    @staticmethod
    def _evaluate(cases):
        fn = _extract_function("isUnknownGate")
        harness = textwrap.dedent(
            """
            %s
            const cases = %s;
            const out = cases.map(([color, material]) =>
              isUnknownGate({ color, material }));
            console.log(JSON.stringify(out));
            """
        ) % (fn, json.dumps([[c, m] for c, m, _, _ in cases]))
        tmp = Path("/tmp/klippace_predicate_check.js")
        tmp.write_text(harness)
        res = subprocess.run([node, str(tmp)], capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise AssertionError(f"node failed:\n{res.stderr}")
        return json.loads(res.stdout.strip())

    def test_truth_table(self):
        got = self._evaluate(self.CASES)
        for (color, material, expected, why), actual in zip(self.CASES, got):
            assert actual is expected, (
                f"isUnknownGate(color={color!r}, material={material!r}) "
                f"returned {actual}, expected {expected} - {why}"
            )

    def test_black_with_material_is_not_unknown(self):
        """Pin the specific regression, named so a failure is self-explanatory."""
        color, material, expected, _ = self.CASES[0]
        assert self._evaluate([self.CASES[0]])[0] is expected, (
            f"a black spool with material {material!r} must not be treated as 'no "
            f"colour data', or the editor and swatch disagree again"
        )


def _strip_js_comments(code: str) -> str:
    """Remove /* */ and // comments.

    Needed before scanning for hex literals or assignments: the explanatory
    comments in this file talk *about* `color: gateColor` and `'#888'`, and a
    naive scan reports the prose as if it were code.
    """
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


class TestSingleDefinition:
    """Two definitions of the same idea drift. Keep it at one."""

    def test_predicate_is_defined_once(self):
        src = DASHBOARD_JS.read_text()
        n = len(re.findall(r"function\s+isUnknownGate\s*\(", src))
        assert n == 1, f"isUnknownGate is defined {n} times; expected exactly 1"

    def test_editor_delegates_to_the_shared_predicate(self):
        code = _strip_js_comments(_editor_body())
        assert "isUnknownGate(" in code, (
            "openSlotEditor must call the shared predicate, not derive its own"
        )

    def test_editor_does_not_re_derive_the_sentinel(self):
        code = _strip_js_comments(_editor_body())
        assert "=== '000000'" not in code, (
            "openSlotEditor is testing the colour sentinel inline again; that is how "
            "it drifted from the swatch the first time"
        )
        assert re.search(r"\bisUnknown\s*=", code) is None, (
            "openSlotEditor defines its own isUnknown again; use isUnknownGate()"
        )

    def test_colour_picker_gets_a_six_digit_colour(self):
        """<input type=color> rejects 3-digit hex and snaps to #000000."""
        code = _strip_js_comments(_editor_body())

        assignment = re.search(r"color:\s*gateIsUnknown[^\n]*", code)
        assert assignment, (
            "openSlotEditor no longer derives its colour from gateIsUnknown; if the "
            "colour source changed, update this test rather than deleting it"
        )
        assert "'#888888'" in assignment.group(0), (
            f"the grey fallback must be 6-digit hex: {assignment.group(0).strip()}"
        )

        short = re.findall(r"['\"]#[0-9a-fA-F]{3}['\"]", code)
        assert not short, (
            f"3-digit hex literals would silently become #000000 in a colour input: {short}"
        )
