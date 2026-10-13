"""End-to-end behaviour of the OrcaSlicer sync, driven through the real entry point.

The plugin's individual helpers are covered in ``test_orca_sync.py``, but
``sync_filaments_to_orcaslicer()`` itself had no test. That matters: the bug
this file guards against was not in any helper, it was in the *combination* of
how the preset name was built and how stale presets are cleaned up, which only
shows when the whole sync runs.

The regression: preset names used to include the resolved colour name
(``ACE T1 - PLA Brown``). When a spool's colour or its resolved name changed,
the name changed, so the sync wrote a new file and then deleted the old one.
OrcaSlicer's own config still referenced the deleted preset, so the filament
appeared broken. Colour now lives only in the payload
(``default_filament_colour``), which is what Orca draws the swatch from, and the
filename stays ``ACE T<slot> - <material>``.
"""

from __future__ import annotations

import json
import logging

import pytest


NET_INFO = {
    "host": "192.168.1.168",
    "port": 7125,
    "base_url": "http://192.168.1.168:7125",
    "printer_name": "Voron 2.4 350",
}


def _slot(index, material="PLA", color="#FF7F32", sku="", **extra):
    slot = {
        "index": index,
        "status": "ready",
        "material": material,
        "color": color,
        "temp": 210,
        "bed_temp": 60,
        "vendor": "Anycubic",
        "sku": sku,
        "custom_name": "",
        "color_name": "",
    }
    slot.update(extra)
    return slot


@pytest.fixture
def stub_printer(monkeypatch, orca_sync):
    """Replace the network layer so the sync can run without a printer."""
    state = {"slots": [_slot(0)], "material_temps": {"PLA": 210, "PETG": 240}}

    def fake_resolve(override_host=None):
        return dict(NET_INFO)

    def fake_fetch(net_info=None):
        return {
            "slots": [dict(s) for s in state["slots"]],
            "material_temps": dict(state["material_temps"]),
        }

    monkeypatch.setattr(orca_sync, "resolve_printer_network_info", fake_resolve)
    monkeypatch.setattr(orca_sync, "fetch_moonraker_ace_data", fake_fetch)
    # No Orca host outside the app, so the refresh probe must take its
    # "no API available" path rather than resolving a filename list.
    monkeypatch.setattr(orca_sync, "orca", None)
    return state


def _written_presets(filament_dirs):
    """Every ACE preset name present across the temp filament dirs."""
    names = set()
    for d in filament_dirs:
        for f in d.glob("ACE T*.json"):
            names.add(f.name)
    return names


class TestGeneratedPresetName:
    """The preset name must depend on nothing but the slot.

    OrcaSlicer names a preset file after the preset's own ``name``, so any change
    to the name is a rename: a new file appears and the old one is deleted. Orca
    then rewrites presets it holds in memory, so the deleted file comes back with
    its old contents - observed on 2026-10-13 as two presets for slot 0, one
    orange (correct) and one white (stale).

    Keeping the name a pure function of the slot means no rename, no delete, and
    therefore nothing for Orca to resurrect.
    """

    def test_name_is_the_slot_only(self, orca_sync, stub_printer,
                                  orca_app_dir, user_filament_dirs, monkeypatch):
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        result = orca_sync.sync_filaments_to_orcaslicer()

        assert result["success"] is True
        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}
        assert result["synced"][0]["name"] == "ACE T0"

    def test_colour_is_absent_from_the_filename(self, orca_sync, stub_printer,
                                                orca_app_dir, user_filament_dirs, monkeypatch):
        stub_printer["slots"] = [_slot(0, color="#FF7F32")]
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        orca_sync.sync_filaments_to_orcaslicer()

        for name in _written_presets(user_filament_dirs):
            for colour_word in ("Orange", "White", "Pink", "Brown", "Black"):
                assert colour_word not in name

    def test_material_is_absent_from_the_filename(self, orca_sync, stub_printer,
                                                  orca_app_dir, user_filament_dirs, monkeypatch):
        """Material is user-editable, so it must not be able to rename a preset."""
        stub_printer["slots"] = [_slot(0, material="PETG")]
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        orca_sync.sync_filaments_to_orcaslicer()

        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}

    def test_colour_still_reaches_the_preset_payload(self, orca_sync, stub_printer,
                                                     orca_app_dir, user_filament_dirs, monkeypatch):
        """Dropping colour from the name must not lose it from the preset.

        Orca draws the filament swatch from ``default_filament_colour``, so this
        is what keeps the colour visible in the UI without naming the file after
        it - and the swatch is now the only thing distinguishing the slots.
        """
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        orca_sync.sync_filaments_to_orcaslicer()

        payload = json.loads(
            (user_filament_dirs[0] / "ACE T0.json").read_text(encoding="utf-8")
        )
        assert payload["default_filament_colour"] == ["#FF7F32"]
        assert payload["name"] == "ACE T0"

    def test_custom_name_does_not_change_the_preset_name(self, orca_sync, stub_printer,
                                                         orca_app_dir, user_filament_dirs,
                                                         monkeypatch):
        """A custom name is a label, not the preset identity.

        It used to become the filename, which made every custom name a rename -
        and the rename is what resurrected the stale preset.
        """
        stub_printer["slots"] = [_slot(0, custom_name="Prusament Galaxy Black")]
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        result = orca_sync.sync_filaments_to_orcaslicer()

        assert result["synced"][0]["name"] == "ACE T0"
        assert not (user_filament_dirs[0] / "Prusament Galaxy Black.json").exists()
        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}
        # The label is still carried, for the tab and the summary.
        assert result["synced"][0]["custom_name"] == "Prusament Galaxy Black"


class TestNameIsImmutable:
    """The filename must not depend on anything the user can edit.

    This is the whole guarantee behind the design. Orca names a preset file after
    its internal ``name``, so any name change is a rename - and Orca rewrites
    presets it holds in memory, so the deleted file comes back with its old
    contents. No rename means no delete, and no delete means nothing to resurrect.

    Colour, material and the spool's custom name were all previously part of the
    name. Each is editable, so each was a way to trigger the bug.
    """

    # Every field the printer or the user can change, with a value deliberately
    # different from the default so the name would once have moved.
    EDITABLE = [
        ("colour -> white", {"color": "#FFFFFF"}),
        ("colour -> black", {"color": "#000000"}),
        ("material -> PETG", {"material": "PETG"}),
        ("custom name added", {"custom_name": "Prusament Galaxy Black"}),
        ("custom name cleared", {"custom_name": ""}),
        ("temperature", {"temp": 275}),
        ("vendor", {"vendor": "Somebody Else"}),
        ("sku", {"sku": "XYZ-1"}),
    ]

    @pytest.mark.parametrize("label,changes", EDITABLE, ids=[e[0] for e in EDITABLE])
    def test_field_cannot_change_the_filename(
        self, label, changes, orca_sync, stub_printer, orca_app_dir,
        user_filament_dirs, monkeypatch
    ):
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])

        slot = _slot(0)
        slot.update(changes)
        stub_printer["slots"] = [slot]
        orca_sync.sync_filaments_to_orcaslicer()

        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}, (
            f"changing {label} renamed the preset; a rename is what lets Orca "
            f"resurrect the deleted file"
        )

    def test_a_full_sweep_never_leaves_a_second_file(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        """Walk through every variant in sequence and check nothing accumulates.

        This is the scenario that produced the visible bug: a stale white preset
        sitting alongside the correct orange one for the same slot.
        """
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])

        for label, changes in self.EDITABLE:
            slot = _slot(0)
            slot.update(changes)
            stub_printer["slots"] = [slot]
            orca_sync.sync_filaments_to_orcaslicer()
            assert _written_presets(user_filament_dirs) == {"ACE T0.json"}, (
                f"after {label}: {sorted(_written_presets(user_filament_dirs))}"
            )

    def test_legacy_material_name_is_cleaned_on_first_run(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        """A profile synced by the previous version must migrate cleanly.

        Older plugins wrote ``ACE T0 - PLA.json``, so the first run of this one
        has to sweep that name too or the profile ends up with both.
        """
        stale = user_filament_dirs[0] / "ACE T0 - PLA.json"
        stale.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        orca_sync.sync_filaments_to_orcaslicer()

        assert not stale.exists(), "the legacy name must be swept, not left beside the new one"
        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}


class TestResyncStability:
    """The regression that made filaments look broken in Orca."""

    def test_changing_a_spool_colour_does_not_rename_the_preset(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        """A colour change must rewrite the same file, not rename it.

        Previously this produced a new name and deleted the old file, leaving
        Orca's config pointing at a preset that no longer existed.
        """
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])

        stub_printer["slots"] = [_slot(0, color="#FF7F32")]   # orange
        orca_sync.sync_filaments_to_orcaslicer()
        first = _written_presets(user_filament_dirs)

        stub_printer["slots"] = [_slot(0, color="#FFFFFF")]   # spool swapped to white
        orca_sync.sync_filaments_to_orcaslicer()
        second = _written_presets(user_filament_dirs)

        assert first == second == {"ACE T0.json"}

    def test_colour_change_updates_content_in_place(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        path = user_filament_dirs[0] / "ACE T0.json"

        stub_printer["slots"] = [_slot(0, color="#FF7F32")]
        orca_sync.sync_filaments_to_orcaslicer()
        assert json.loads(path.read_text(encoding="utf-8"))["default_filament_colour"] == ["#FF7F32"]

        stub_printer["slots"] = [_slot(0, color="#FFFFFF")]
        orca_sync.sync_filaments_to_orcaslicer()
        assert json.loads(path.read_text(encoding="utf-8"))["default_filament_colour"] == ["#FFFFFF"]

    def test_material_change_does_not_rename_the_preset(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        """Material is user-editable too, so it must not rename a preset either.

        It used to be part of the name, which made a material swap a rename - and
        a rename is what lets Orca resurrect the deleted file.
        """
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])

        stub_printer["slots"] = [_slot(0, material="PLA")]
        orca_sync.sync_filaments_to_orcaslicer()

        stub_printer["slots"] = [_slot(0, material="PETG")]
        orca_sync.sync_filaments_to_orcaslicer()

        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}

    def test_sync_is_idempotent(self, orca_sync, stub_printer, orca_app_dir,
                                user_filament_dirs, monkeypatch):
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])
        stub_printer["slots"] = [_slot(0), _slot(1, color="#FF3A2F")]

        orca_sync.sync_filaments_to_orcaslicer()
        first = _written_presets(user_filament_dirs)
        result = orca_sync.sync_filaments_to_orcaslicer()

        assert _written_presets(user_filament_dirs) == first
        assert len(result["synced"]) == 2


class TestRefreshOrcaslicerPresets:
    """The refresh must report honestly rather than implying success."""

    def test_no_host_reports_that_a_restart_is_needed(self, orca_sync, monkeypatch):
        monkeypatch.setattr(orca_sync, "orca", None)
        note = orca_sync.refresh_orcaslicer_presets()
        assert isinstance(note, str) and note
        assert "restart" in note.lower()

    def test_uses_a_reload_method_when_the_bundle_exposes_one(
        self, orca_sync, monkeypatch
    ):
        calls = []

        class Bundle:
            def load_presets(self):
                calls.append("load_presets")

        class Host:
            def preset_bundle(self):
                return Bundle()

        fake_orca = type("Orca", (), {"host": Host()})
        monkeypatch.setattr(orca_sync, "orca", fake_orca)

        note = orca_sync.refresh_orcaslicer_presets()

        assert calls == ["load_presets"]
        assert "load_presets" in note

    def test_falls_back_to_marking_presets_dirty(self, orca_sync, monkeypatch):
        class Host:
            def __init__(self):
                self.is_presets_dirty = False

        host = Host()
        fake_orca = type("Orca", (), {"host": host})
        monkeypatch.setattr(orca_sync, "orca", fake_orca)

        note = orca_sync.refresh_orcaslicer_presets()

        assert host.is_presets_dirty is True
        assert "dirty" in note.lower()

    def test_a_raising_host_api_does_not_break_the_sync(
        self, orca_sync, stub_printer, orca_app_dir, user_filament_dirs, monkeypatch
    ):
        """A refresh failure must never cost the user their written presets."""

        class ExplodingHost:
            def preset_bundle(self):
                raise RuntimeError("host API exploded")

        fake_orca = type("Orca", (), {"host": ExplodingHost()})
        monkeypatch.setattr(orca_sync, "orca", fake_orca)
        monkeypatch.setattr(orca_sync, "find_orcaslicer_user_filament_dirs",
                            lambda: [str(d) for d in user_filament_dirs])

        result = orca_sync.sync_filaments_to_orcaslicer()

        assert result["success"] is True
        assert _written_presets(user_filament_dirs) == {"ACE T0.json"}

    def test_api_surface_is_logged_once(self, orca_sync, monkeypatch, caplog):
        """The API dump is diagnostic, so it must not repeat every sync."""
        class Bundle:
            pass

        class Host:
            def preset_bundle(self):
                return Bundle()

        monkeypatch.setattr(orca_sync, "_API_LOGGED", False)
        monkeypatch.setattr(orca_sync, "orca", type("Orca", (), {"host": Host()})())

        with caplog.at_level(logging.INFO):
            first = orca_sync.refresh_orcaslicer_presets()
            orca_sync.refresh_orcaslicer_presets()

        assert orca_sync._API_LOGGED is True
        logged = sum("preset_bundle is" in r.getMessage() for r in caplog.records)
        assert logged == 1, "API surface should be dumped exactly once"
        # A bundle exposing no reload method and no dirty flag is the case that
        # used to fail silently, so the note must not claim success.
        assert "restart" in first.lower()

    def test_no_host_returns_a_string_without_raising(self, orca_sync, monkeypatch):
        monkeypatch.setattr(orca_sync, "orca", None)
        assert "restart" in orca_sync.refresh_orcaslicer_presets().lower()
