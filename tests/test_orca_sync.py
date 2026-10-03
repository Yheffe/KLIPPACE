"""Tests for the KLIPPACE -> OrcaSlicer filament sync plugin.

These cover the pure logic only: no network calls and no writes outside the
temporary directories supplied by fixtures.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Colour resolution
# ---------------------------------------------------------------------------

class TestColorResolution:
    @pytest.mark.parametrize("raw,expected", [
        ("#EFF0F1", ("#FFFFFF", "White")),   # off-white Anycubic RFID
        ("#FFFFFF", ("#FFFFFF", "White")),
        ("#FF7F32", ("#FF7F32", "Orange")),
        ("#FF3A2F", ("#FF3A2F", "Red")),
        ("#000000", ("#000000", "Black")),
        ("#0000FF", ("#0000FF", "Blue")),
    ])
    def test_exact_map_entries(self, orca_sync, raw, expected):
        assert orca_sync.resolve_filament_color(raw) == expected

    def test_near_white_snaps_to_pure_white(self, orca_sync):
        assert orca_sync.resolve_filament_color("#F4F4F4")[0] == "#FFFFFF"

    def test_near_black_snaps_to_pure_black(self, orca_sync):
        assert orca_sync.resolve_filament_color("#0A0A0A")[0] == "#000000"

    def test_shorthand_hex_is_expanded(self, orca_sync):
        assert orca_sync.resolve_filament_color("#FFF") == ("#FFFFFF", "White")

    def test_missing_hex_hash_is_tolerated(self, orca_sync):
        assert orca_sync.resolve_filament_color("FF0000")[0] == "#FF0000"

    def test_empty_input_defaults_to_white(self, orca_sync):
        assert orca_sync.resolve_filament_color("") == ("#FFFFFF", "White")

    def test_nearest_palette_name_for_unknown_hex(self, orca_sync):
        # A clearly green hex that is not an exact map entry.
        assert orca_sync.get_color_name("#0AC83C") == "Green"


# ---------------------------------------------------------------------------
# Preset naming
# ---------------------------------------------------------------------------

class TestPresetNaming:
    def test_simple_name_is_preserved(self, orca_sync):
        assert orca_sync.sanitize_preset_name("Prusament Galaxy Black") == "Prusament Galaxy Black"

    def test_path_separators_are_replaced(self, orca_sync):
        assert orca_sync.sanitize_preset_name("AC/DC: Back\\in") == "AC-DC- Back-in"

    def test_windows_reserved_characters_are_replaced(self, orca_sync):
        assert orca_sync.sanitize_preset_name('a*b?c"d<e>f|g') == "a-b-c-d-e-f-g"

    def test_control_characters_are_stripped(self, orca_sync):
        assert "\x00" not in orca_sync.sanitize_preset_name("bad\x00name")
        assert "\n" not in orca_sync.sanitize_preset_name("bad\nname")

    def test_whitespace_is_collapsed(self, orca_sync):
        assert orca_sync.sanitize_preset_name("  a   b  ") == "a b"

    def test_trailing_dots_and_spaces_removed(self, orca_sync):
        # Trailing dots are invalid on Windows.
        assert orca_sync.sanitize_preset_name("bad name.  ") == "bad name"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_input_yields_empty_string(self, orca_sync, value):
        assert orca_sync.sanitize_preset_name(value) == ""

    def test_slot_keys_match_orcaslicer_schema(self, orca_sync):
        assert orca_sync.filament_slot_key(0) == "filament"
        assert orca_sync.filament_slot_key(1) == "filament_01"
        assert orca_sync.filament_slot_key(12) == "filament_12"


# ---------------------------------------------------------------------------
# Material -> OrcaSlicer base preset mapping
# ---------------------------------------------------------------------------

class TestMaterialInherits:
    def test_every_mapping_targets_a_real_generic_preset(self, orca_sync):
        unknown = {
            target
            for target in orca_sync.MATERIAL_INHERITS.values()
            if target not in orca_sync.GENERIC_SYSTEM_FILAMENTS
        }
        assert unknown == set(), f"inherits targets not in Orca's library: {sorted(unknown)}"

    def test_mapping_is_case_insensitive(self, orca_sync):
        assert orca_sync.resolve_inherits_name("petg") == orca_sync.resolve_inherits_name("PETG")

    def test_mapping_tolerates_surrounding_whitespace(self, orca_sync):
        assert orca_sync.resolve_inherits_name("  ASA ") == "Generic ASA @System"

    @pytest.mark.parametrize("material,expected", [
        ("PLA", "Generic PLA @System"),
        ("PLA-CF", "Generic PLA-CF @System"),
        ("PETG", "Generic PETG @System"),
        ("PETG-CF", "Generic PETG-CF @System"),
        ("ABS", "Generic ABS @System"),
        ("ASA", "Generic ASA @System"),
        ("HIPS", "Generic HIPS @System"),
        ("TPU", "Generic TPU @System"),
        ("PVA", "Generic PVA @System"),
        ("PC", "Generic PC @System"),
    ])
    def test_families_map_to_their_own_generic(self, orca_sync, material, expected):
        assert orca_sync.resolve_inherits_name(material) == expected

    def test_materials_without_a_generic_map_to_nearest_family(self, orca_sync):
        # Nylon is PA, TPE is a flexible like TPU, PC-ABS is PC-based.
        assert orca_sync.resolve_inherits_name("Nylon") == "Generic PA @System"
        assert orca_sync.resolve_inherits_name("TPE") == "Generic TPU @System"
        assert orca_sync.resolve_inherits_name("PC-ABS") == "Generic PC @System"

    def test_unknown_material_uses_documented_fallback(self, orca_sync):
        assert orca_sync.resolve_inherits_name("Unobtainium") == orca_sync.FALLBACK_INHERITS

    def test_unknown_material_warns_only_once(self, orca_sync, caplog):
        orca_sync._WARNED_UNMAPPED_MATERIALS.clear()
        with caplog.at_level("WARNING"):
            for _ in range(3):
                orca_sync.resolve_inherits_name("AlsoUnobtainium")
        # The warning reports the upper-cased key it was normalised to.
        warnings = [r for r in caplog.records if "ALSOUNOBTAINIUM" in r.getMessage()]
        assert len(warnings) == 1

    def test_fallback_is_itself_a_real_preset(self, orca_sync):
        assert orca_sync.FALLBACK_INHERITS in orca_sync.GENERIC_SYSTEM_FILAMENTS


# ---------------------------------------------------------------------------
# Temperature resolution from the printer's material table
# ---------------------------------------------------------------------------

class TestMaterialTempLookup:
    TABLE = {"PLA": 210, "PETG": 240, "ASA": 260, "PEEK": 380, "PLA Matte": 210}

    def test_exact_lookup(self, orca_sync):
        assert orca_sync.lookup_material_temp(self.TABLE, "PETG") == 240

    def test_case_insensitive_lookup(self, orca_sync):
        assert orca_sync.lookup_material_temp(self.TABLE, "petg") == 240
        assert orca_sync.lookup_material_temp(self.TABLE, "Asa") == 260

    def test_multiword_material_lookup(self, orca_sync):
        assert orca_sync.lookup_material_temp(self.TABLE, "pla matte") == 210

    def test_unknown_material_uses_default(self, orca_sync):
        assert orca_sync.lookup_material_temp(self.TABLE, "Vibranium") == orca_sync.DEFAULT_NOZZLE_TEMP

    def test_zero_temp_in_table_is_treated_as_missing(self, orca_sync):
        assert orca_sync.lookup_material_temp({"PLA": 0}, "PLA") == orca_sync.DEFAULT_NOZZLE_TEMP

    def test_non_numeric_value_uses_default(self, orca_sync):
        assert orca_sync.lookup_material_temp({"PLA": "hot"}, "PLA") == orca_sync.DEFAULT_NOZZLE_TEMP

    @pytest.mark.parametrize("table", [None, {}, "nope", 5])
    def test_missing_table_uses_default(self, orca_sync, table):
        assert orca_sync.lookup_material_temp(table, "PLA") == orca_sync.DEFAULT_NOZZLE_TEMP

    def test_none_material_uses_default(self, orca_sync):
        assert orca_sync.lookup_material_temp(self.TABLE, None) == orca_sync.DEFAULT_NOZZLE_TEMP


# ---------------------------------------------------------------------------
# Multi-unit discovery
# ---------------------------------------------------------------------------

class TestInstanceDiscovery:
    def test_units_are_read_from_the_mmu_shim(self, orca_sync):
        mmu = {"unit": [
            {"first_gate": 0, "num_gates": 4},
            {"first_gate": 4, "num_gates": 4},
        ]}
        assert orca_sync.discover_ace_instances(mmu) == [
            ("ace_instance_0", 0, 4),
            ("ace_instance_1", 4, 4),
        ]

    def test_units_are_sorted_by_first_gate(self, orca_sync):
        mmu = {"unit": [
            {"first_gate": 4, "num_gates": 4},
            {"first_gate": 0, "num_gates": 4},
        ]}
        # The object name follows the list index, matching the backend naming.
        assert [first for _, first, _ in orca_sync.discover_ace_instances(mmu)] == [0, 4]

    def test_falls_back_to_one_unit_when_shim_reports_none(self, orca_sync):
        assert orca_sync.discover_ace_instances({}) == [("ace_instance_0", 0, orca_sync.MAX_SLOTS)]

    def test_falls_back_when_unit_metadata_is_malformed(self, orca_sync):
        mmu = {"unit": [{"first_gate": "x", "num_gates": "y"}, "nonsense"]}
        assert orca_sync.discover_ace_instances(mmu) == [("ace_instance_0", 0, orca_sync.MAX_SLOTS)]

    def test_skipping_a_unit_does_not_renumber_the_rest(self, orca_sync):
        # Object names come from the shim's unit index, so dropping the first
        # (empty/gate-less) unit must not promote the second to ace_instance_0.
        mmu = {"unit": [{"first_gate": 0, "num_gates": 0}, {"first_gate": 4, "num_gates": 4}]}
        assert orca_sync.discover_ace_instances(mmu) == [("ace_instance_1", 4, 4)]

    def test_gate_source_map_spans_units(self, orca_sync):
        instances = [("ace_instance_0", 0, 4), ("ace_instance_1", 4, 4)]
        mapping = orca_sync.build_gate_source_map(instances)
        assert len(mapping) == 8
        assert mapping[0] == ("ace_instance_0", 0)
        assert mapping[3] == ("ace_instance_0", 3)
        assert mapping[4] == ("ace_instance_1", 0)
        assert mapping[7] == ("ace_instance_1", 3)


# ---------------------------------------------------------------------------
# OrcaSlicer.conf mapping — regression tests for the filament_colors bug
# ---------------------------------------------------------------------------

def _preset(**overrides):
    base = {
        "machine": "Voron 2.4 350",
        "filament": "old0", "filament_01": "old1",
        "filament_02": "old2", "filament_03": "old3",
        "filament_colors": "#111111,#222222,#333333,#444444",
        "filament_multi_colors": "#111111,#222222,#333333,#444444",
    }
    base.update(overrides)
    return base


class TestPresetSlotCount:
    def test_four_extruder_machine(self, orca_sync):
        assert orca_sync._preset_slot_count(_preset()) == 4

    def test_single_extruder_machine_has_one_colour(self, orca_sync):
        assert orca_sync._preset_slot_count({
            "filament": "PLA", "filament_colors": "#FFFFFF",
        }) == 1

    def test_seven_extruder_machine(self, orca_sync):
        preset = {f"filament_{i:02d}": "x" for i in range(1, 7)}
        preset["filament"] = "y"
        assert orca_sync._preset_slot_count(preset) == 7

    def test_preset_without_slots(self, orca_sync):
        assert orca_sync._preset_slot_count({}) == 0

    def test_colour_keys_do_not_count_as_slots(self, orca_sync):
        # filament_colors / filament_multi_colors must not register as slots.
        assert orca_sync._preset_slot_count({
            "filament": "PLA", "filament_colors": "#FFF", "filament_multi_colors": "",
        }) == 1


class TestApplySlotPresets:
    def test_preset_names_and_colours_are_written(self, orca_sync):
        preset = _preset()
        items = {
            0: {"name": "newP0", "color": "#AAAAAA"},
            1: {"name": "newP1", "color": "#BBBBBB"},
            2: {"name": "newP2", "color": "#CCCCCC"},
            3: {"name": "newP3", "color": "#DDDDDD"},
        }
        assert orca_sync._apply_slot_presets(preset, items, 4) is True
        assert preset["filament"] == "newP0"
        assert preset["filament_03"] == "newP3"
        assert preset["filament_colors"] == "#AAAAAA,#BBBBBB,#CCCCCC,#DDDDDD"

    def test_partial_sync_never_writes_a_preset_name_into_colours(self, orca_sync):
        """Regression: an unfilled slot appended the old preset NAME to colours."""
        preset = _preset()
        items = {
            0: {"name": "newP0", "color": "#AAAAAA"},
            1: {"name": "newP1", "color": "#BBBBBB"},
            2: {"name": "newP2", "color": "#CCCCCC"},
        }
        orca_sync._apply_slot_presets(preset, items, 4)
        colours = preset["filament_colors"].split(",")
        assert len(colours) == 4
        assert all(c.startswith("#") for c in colours), colours
        assert "newP" not in preset["filament_colors"]
        # The unsynced slot keeps whatever colour Orca had.
        assert colours[3] == "#444444"
        # ...and its preset name is left alone.
        assert preset["filament_03"] == "old3"

    def test_colour_list_is_padded_when_shorter_than_slots(self, orca_sync):
        preset = _preset(filament_colors="#111111")
        orca_sync._apply_slot_presets(preset, {3: {"name": "P3", "color": "#ABCDEF"}}, 4)
        colours = preset["filament_colors"].split(",")
        assert len(colours) == 4
        assert colours[3] == "#ABCDEF"
        assert all(c.startswith("#") for c in colours)

    def test_multi_colors_only_mirrored_when_machine_supports_it(self, orca_sync):
        supported = _preset()
        orca_sync._apply_slot_presets(supported, {0: {"name": "P", "color": "#ABCDEF"}}, 1)
        assert supported["filament_multi_colors"].startswith("#ABCDEF")

        unsupported = _preset(filament_multi_colors="")
        orca_sync._apply_slot_presets(unsupported, {0: {"name": "P", "color": "#ABCDEF"}}, 1)
        assert unsupported["filament_multi_colors"] == ""

    def test_no_change_reports_false(self, orca_sync):
        preset = _preset(filament="same", filament_colors="#123456")
        assert orca_sync._apply_slot_presets(preset, {0: {"name": "same", "color": "#123456"}}, 1) is False

    def test_single_extruder_machine_only_touches_one_colour(self, orca_sync):
        preset = _preset(filament_colors="#111111")
        orca_sync._apply_slot_presets(preset, {0: {"name": "P0", "color": "#AAAAAA"}}, 1)
        assert preset["filament_colors"] == "#AAAAAA"


class TestManagedMachineMatching:
    def test_matches_by_printer_name(self, orca_sync):
        assert orca_sync._is_managed_machine({"machine": "Voron 2.4 350"}, "Voron 2.4 350")

    def test_matches_by_remembered_machine(self, orca_sync):
        assert orca_sync._is_managed_machine({"machine": "Voron 2.4 350"}, "", "Voron 2.4 350")

    def test_matches_legacy_generated_preset_names(self, orca_sync):
        preset = {"machine": "Other", "filament_01": "ACE T1 - PLA Red"}
        assert orca_sync._is_managed_machine(preset, "Voron 2.4 350")

    def test_custom_names_alone_do_not_match_an_unknown_machine(self, orca_sync):
        preset = {"machine": "Other", "filament": "Galaxy Black"}
        assert not orca_sync._is_managed_machine(preset, "Voron 2.4 350")

    def test_remembered_machine_rescues_custom_names(self, orca_sync):
        preset = {"machine": "Other", "filament": "Galaxy Black"}
        assert orca_sync._is_managed_machine(preset, "Voron 2.4 350", "Other")

    def test_unrelated_machine_is_not_touched(self, orca_sync):
        preset = {"machine": "Anycubic Kobra 3 0.4 nozzle", "filament": "Anycubic PLA"}
        assert not orca_sync._is_managed_machine(preset, "Voron 2.4 350")


class TestUpdateOrcaSlicerConf:
    def _write_conf(self, app_dir, presets):
        conf = {"presets": {"machine": "Voron 2.4 350"}, "orca_presets": presets}
        path = app_dir / "OrcaSlicer.conf"
        path.write_text(json.dumps(conf, indent=4), encoding="utf-8")
        return path

    def test_updates_only_the_matching_machine(self, orca_sync, orca_app_dir):
        other = {"machine": "Some Other Printer", "filament": "Unrelated PLA",
                 "filament_colors": "#123456"}
        self._write_conf(orca_app_dir, [_preset(), other])

        updated = orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "Synced", "color": "#ABCDEF"}],
            printer_name="Voron 2.4 350",
        )

        assert updated == ["Voron 2.4 350"]
        conf = json.loads((orca_app_dir / "OrcaSlicer.conf").read_text())
        machines = {p["machine"]: p for p in conf["orca_presets"]}
        assert machines["Voron 2.4 350"]["filament"] == "Synced"
        assert machines["Some Other Printer"] == other

    def test_returns_empty_when_nothing_changes(self, orca_sync, orca_app_dir):
        preset = _preset(filament="same", filament_colors="#123456")
        self._write_conf(orca_app_dir, [preset])
        updated = orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "same", "color": "#123456"}],
            printer_name="Voron 2.4 350",
        )
        assert updated == []

    def test_missing_conf_is_not_fatal(self, orca_sync, orca_app_dir):
        assert orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "x", "color": "#FFFFFF"}],
            printer_name="Voron 2.4 350",
        ) == []

    def test_corrupt_conf_is_not_fatal(self, orca_sync, orca_app_dir):
        (orca_app_dir / "OrcaSlicer.conf").write_text("{ not json", encoding="utf-8")
        assert orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "x", "color": "#FFFFFF"}],
            printer_name="Voron 2.4 350",
        ) == []

    def test_conf_without_orca_presets_is_not_fatal(self, orca_sync, orca_app_dir):
        (orca_app_dir / "OrcaSlicer.conf").write_text(json.dumps({"presets": {}}), encoding="utf-8")
        assert orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "x", "color": "#FFFFFF"}],
            printer_name="Voron 2.4 350",
        ) == []

    def test_junk_entries_in_orca_presets_are_skipped(self, orca_sync, orca_app_dir):
        self._write_conf(orca_app_dir, ["not a dict", None, _preset()])
        assert orca_sync.update_orcaslicer_conf(
            [{"slot": 0, "name": "Synced", "color": "#ABCDEF"}],
            printer_name="Voron 2.4 350",
        ) == ["Voron 2.4 350"]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_missing_manifest_returns_empty_default(self, orca_sync, orca_app_dir):
        manifest = orca_sync.load_manifest()
        assert manifest["slots"] == {}
        assert manifest["machine"] == ""

    def test_round_trip(self, orca_sync, orca_app_dir):
        data = {"version": 1, "machine": "Voron 2.4 350",
                "slots": {"0": ["/a/preset.json"], "1": ["/b/preset.json"]}}
        assert orca_sync.save_manifest(data) is True
        assert orca_sync.load_manifest() == data

    def test_corrupt_manifest_is_treated_as_empty(self, orca_sync, orca_app_dir):
        (orca_app_dir / orca_sync.MANIFEST_FILENAME).write_text("<<<not json", encoding="utf-8")
        assert orca_sync.load_manifest()["slots"] == {}

    def test_manifest_with_non_dict_slots_is_coerced(self, orca_sync, orca_app_dir):
        (orca_app_dir / orca_sync.MANIFEST_FILENAME).write_text(
            json.dumps({"slots": ["oops"]}), encoding="utf-8")
        assert orca_sync.load_manifest()["slots"] == {}


# ---------------------------------------------------------------------------
# Preset cleanup
# ---------------------------------------------------------------------------

class TestCleanSlotPresets:
    def test_removes_recorded_paths_no_longer_current(self, orca_sync, user_filament_dirs):
        old = user_filament_dirs[0] / "Prusament Galaxy Black.json"
        old.write_text("{}", encoding="utf-8")
        new = user_filament_dirs[0] / "Galaxy Black v2.json"
        new.write_text("{}", encoding="utf-8")

        cleaned = orca_sync.clean_slot_presets(
            [str(d) for d in user_filament_dirs], 3,
            keep_paths=[str(new)], previous_paths=[str(old)],
        )

        assert cleaned == [str(old)]
        assert not old.exists()
        assert new.exists()

    def test_removes_legacy_generated_presets_by_prefix(self, orca_sync, user_filament_dirs):
        legacy = user_filament_dirs[0] / "ACE T3 - PLA Black.json"
        legacy.write_text("{}", encoding="utf-8")
        sidecar = user_filament_dirs[0] / "ACE T3 - PLA Black.info"
        sidecar.write_text("{}", encoding="utf-8")

        cleaned = orca_sync.clean_slot_presets(
            [str(d) for d in user_filament_dirs], 3, keep_paths=[], previous_paths=[],
        )

        assert set(cleaned) == {str(legacy), str(sidecar)}
        assert not legacy.exists() and not sidecar.exists()

    def test_does_not_touch_other_slots(self, orca_sync, user_filament_dirs):
        keep_slot = user_filament_dirs[0] / "ACE T2 - PLA White.json"
        keep_slot.write_text("{}", encoding="utf-8")
        orca_sync.clean_slot_presets(
            [str(d) for d in user_filament_dirs], 3, keep_paths=[], previous_paths=[],
        )
        assert keep_slot.exists()

    def test_current_file_is_never_deleted(self, orca_sync, user_filament_dirs):
        current = user_filament_dirs[0] / "ACE T3 - PLA Black.json"
        current.write_text("{}", encoding="utf-8")
        orca_sync.clean_slot_presets(
            [str(d) for d in user_filament_dirs], 3,
            keep_paths=[str(current)], previous_paths=[str(current)],
        )
        assert current.exists()

    def test_missing_paths_are_ignored(self, orca_sync, user_filament_dirs):
        cleaned = orca_sync.clean_slot_presets(
            [str(d) for d in user_filament_dirs], 0,
            keep_paths=[], previous_paths=["/nonexistent/thing.json"],
        )
        assert cleaned == []
