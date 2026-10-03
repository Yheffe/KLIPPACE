"""Tests for the KLIPPACE -> OrcaSlicer filament sync plugin.

These cover the pure logic only: no network calls and no writes outside the
temporary directories supplied by fixtures.
"""

from __future__ import annotations

import json
import pathlib
import types

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
# Printer network resolution (sandbox-safe: never touches OrcaSlicer.conf)
# ---------------------------------------------------------------------------

def _write_machine_profile(app_dir, user, name, **fields):
    """Create a machine profile under ``<app_dir>/user/<user>/machine/``."""
    machine_dir = app_dir / "user" / user / "machine"
    machine_dir.mkdir(parents=True, exist_ok=True)
    body = {"name": name, "from": "User"}
    body.update(fields)
    (machine_dir / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


class TestMachineProfileDiscovery:
    def test_finds_only_profiles_that_define_a_host(self, orca_sync, orca_app_dir):
        _write_machine_profile(orca_app_dir, "default", "Voron 2.4 350",
                               print_host="192.168.1.168")
        _write_machine_profile(orca_app_dir, "default", "No Host Machine")

        found = orca_sync.find_machine_profiles_with_host(orca_app_dir)
        assert [name for name, _ in found] == ["Voron 2.4 350"]

    def test_missing_user_tree_returns_empty(self, orca_sync, orca_app_dir):
        assert orca_sync.find_machine_profiles_with_host(orca_app_dir) == []

    def test_corrupt_profile_is_skipped(self, orca_sync, orca_app_dir):
        machine_dir = orca_app_dir / "user" / "default" / "machine"
        machine_dir.mkdir(parents=True)
        (machine_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        assert orca_sync.find_machine_profiles_with_host(orca_app_dir) == []

    def test_non_dict_profile_is_skipped(self, orca_sync, orca_app_dir):
        machine_dir = orca_app_dir / "user" / "default" / "machine"
        machine_dir.mkdir(parents=True)
        (machine_dir / "list.json").write_text(json.dumps(["nope"]), encoding="utf-8")
        assert orca_sync.find_machine_profiles_with_host(orca_app_dir) == []

    def test_prefers_the_named_printer(self, orca_sync, orca_app_dir):
        _write_machine_profile(orca_app_dir, "default", "Alpha", print_host="10.0.0.1")
        _write_machine_profile(orca_app_dir, "default", "Beta", print_host="10.0.0.2")

        found = orca_sync.find_machine_profiles_with_host(orca_app_dir, "Beta")
        assert [name for name, _ in found] == ["Beta"]

    def test_falls_back_to_all_when_the_name_is_unknown(self, orca_sync, orca_app_dir):
        _write_machine_profile(orca_app_dir, "default", "Alpha", print_host="10.0.0.1")
        found = orca_sync.find_machine_profiles_with_host(orca_app_dir, "Gamma")
        assert [name for name, _ in found] == ["Alpha"]

    def test_resolution_reads_host_from_a_machine_profile(self, orca_sync, orca_app_dir, monkeypatch):
        # Disable the runtime orca.host path so this exercises the JSON fallback.
        monkeypatch.setattr(orca_sync, "orca", None)
        _write_machine_profile(orca_app_dir, "default", "Voron 2.4 350",
                               print_host="10.9.8.7", printhost_port="7125",
                               printhost_apikey="secret-key")

        info = orca_sync.resolve_printer_network_info()
        assert info["host"] == "10.9.8.7"
        assert str(info["port"]) == "7125"
        assert info["apikey"] == "secret-key"
        assert info["base_url"] == "http://10.9.8.7:7125"

    def test_resolution_never_opens_the_denied_conf(self, orca_sync, orca_app_dir, monkeypatch):
        """While the sandbox is active, OrcaSlicer.conf must not be opened."""
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text(json.dumps({
            "presets": {"machine": "Voron 2.4 350"},
            "local_machines": {"1.2.3.4": {"dev_ip": "1.2.3.4"}},
            "user_last_selected_machine": "9.9.9.9",
        }), encoding="utf-8")
        # A bare orca module stands in for 'running inside OrcaSlicer'.
        monkeypatch.setattr(orca_sync, "orca", types.SimpleNamespace())

        opened = []
        real_open = open

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr("builtins.open", spy_open)
        try:
            info = orca_sync.resolve_printer_network_info()
        finally:
            monkeypatch.undo()

        assert not any(p.endswith("OrcaSlicer.conf") for p in opened), opened
        # None of the conf-only values leaked in either.
        assert info["host"] == orca_sync.DEFAULT_PRINTER_HOST

    def test_resolution_uses_the_conf_outside_the_sandbox(self, orca_sync, orca_app_dir, monkeypatch):
        """A CLI run has no audit hook, so the saved machine list is usable."""
        monkeypatch.setattr(orca_sync, "orca", None)
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text(json.dumps({
            "presets": {"machine": "Voron 2.4 350"},
            "local_machines": {
                "192.168.1.50": {"dev_ip": "192.168.1.50",
                                 "access_code": "12345678",
                                 "printer_type": "Voron 2.4 350"},
            },
        }), encoding="utf-8")

        info = orca_sync.resolve_printer_network_info()
        assert info["host"] == "192.168.1.50"
        assert info["apikey"] == "12345678"
        assert info["printer_name"] == "Voron 2.4 350"

    def test_override_host_wins_over_everything(self, orca_sync, orca_app_dir):
        _write_machine_profile(orca_app_dir, "default", "Voron 2.4 350",
                               print_host="10.0.0.1")
        info = orca_sync.resolve_printer_network_info(override_host="192.168.5.5")
        assert info["host"] == "192.168.5.5"


# ---------------------------------------------------------------------------
# Snapshot cache for the embedded page
# ---------------------------------------------------------------------------

class TestConfAccessGuard:
    """OrcaSlicer.conf is readable only when the plugin sandbox is inactive."""

    def test_not_read_while_the_sandbox_is_active(self, orca_sync, orca_app_dir, monkeypatch):
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text(
            json.dumps({"presets": {"machine": "Voron 2.4 350"}}), encoding="utf-8")
        monkeypatch.setattr(orca_sync, "orca", types.SimpleNamespace())
        assert orca_sync.read_conf_unrestricted() == {}

    def test_read_outside_the_sandbox(self, orca_sync, orca_app_dir, monkeypatch):
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text(
            json.dumps({"presets": {"machine": "Voron 2.4 350"}}), encoding="utf-8")
        monkeypatch.setattr(orca_sync, "orca", None)
        assert orca_sync.read_conf_unrestricted()["presets"]["machine"] == "Voron 2.4 350"

    def test_missing_conf_returns_empty(self, orca_sync, orca_app_dir, monkeypatch):
        monkeypatch.setattr(orca_sync, "orca", None)
        assert orca_sync.read_conf_unrestricted() == {}

    def test_corrupt_conf_returns_empty(self, orca_sync, orca_app_dir, monkeypatch):
        monkeypatch.setattr(orca_sync, "orca", None)
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text("{ nope", encoding="utf-8")
        assert orca_sync.read_conf_unrestricted() == {}

    def test_non_dict_conf_returns_empty(self, orca_sync, orca_app_dir, monkeypatch):
        monkeypatch.setattr(orca_sync, "orca", None)
        (orca_app_dir / orca_sync.CONFIG_FILENAME).write_text("[1, 2]", encoding="utf-8")
        assert orca_sync.read_conf_unrestricted() == {}


class TestSnapshotCache:
    SLOTS = [{"index": 0, "material": "PLA", "color": "#FF7F32", "status": "ready"}]
    NET = {"host": "192.168.1.168", "base_url": "http://192.168.1.168:7125",
           "printer_name": "Voron 2.4 350"}

    def test_missing_cache_returns_empty(self, orca_sync, orca_app_dir):
        assert orca_sync.load_cached_snapshot() == ([], {})

    def test_round_trip(self, orca_sync, orca_app_dir):
        orca_sync.save_cached_snapshot(self.SLOTS, self.NET)
        slots, net = orca_sync.load_cached_snapshot()
        assert slots == self.SLOTS
        assert net == self.NET

    def test_corrupt_cache_returns_empty(self, orca_sync, orca_app_dir):
        (orca_app_dir / orca_sync.CACHE_FILENAME).write_text("<<<", encoding="utf-8")
        assert orca_sync.load_cached_snapshot() == ([], {})

    def test_wrong_shaped_cache_is_coerced(self, orca_sync, orca_app_dir):
        (orca_app_dir / orca_sync.CACHE_FILENAME).write_text(
            json.dumps({"slots": "nope", "network": 5}), encoding="utf-8")
        assert orca_sync.load_cached_snapshot() == ([], {})

    def test_save_failure_is_not_fatal(self, orca_sync, monkeypatch):
        # An unwritable app dir must not raise out of the sync.
        monkeypatch.setattr(
            orca_sync, "get_cache_path",
            lambda: pathlib.Path("/proc/definitely-not-writable/cache.json"),
        )
        orca_sync.save_cached_snapshot(self.SLOTS, self.NET)  # must not raise


# ---------------------------------------------------------------------------
# Embedded page rendering
# ---------------------------------------------------------------------------

class TestRenderHtmlPage:
    def test_empty_snapshot_prompts_the_user_to_sync(self, orca_sync):
        html = orca_sync.render_html_page([], {})
        assert "Sync Filaments to Slicer" in html
        assert "No snapshot yet" in html

    def test_slots_are_rendered_with_material_and_colour(self, orca_sync):
        html = orca_sync.render_html_page(
            [{"index": 2, "status": "ready", "material": "PETG",
              "color": "#0AC83C", "color_name": "Green", "temp": 245,
              "bed_temp": 70, "vendor": "AC", "sku": "X1", "custom_name": ""}],
            {"printer_name": "Voron 2.4 350", "base_url": "http://10.0.0.1:7125"},
        )
        assert "PETG" in html
        assert "#0AC83C" in html
        assert "Slot 2" in html

    def test_custom_name_is_shown_as_the_preset(self, orca_sync):
        html = orca_sync.render_html_page(
            [{"index": 3, "status": "ready", "material": "PETG",
              "color": "#0AC83C", "color_name": "Green", "temp": 245,
              "bed_temp": 70, "vendor": "AC", "sku": "", "custom_name": "Galaxy Black"}],
            {"printer_name": "Voron 2.4 350", "base_url": "http://10.0.0.1:7125"},
        )
        assert "Galaxy Black" in html

    def test_empty_snapshot_does_not_claim_a_connection(self, orca_sync):
        html = orca_sync.render_html_page([], {})
        assert "Connected to" not in html


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
