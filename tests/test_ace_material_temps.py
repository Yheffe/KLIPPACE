"""Tests for the ACE backend's material temperature table.

The table is the single source of truth for material temperatures: it backs the
RFID no-range fallback, the MMU shim's reported gate temps, and the preset list
the dashboard's slot editor renders. These tests pin that contract so the
dashboard and the OrcaSlicer plugin cannot silently drift from the backend.
"""

from __future__ import annotations

import pytest


class TestMaterialTempTable:
    def test_table_is_not_empty(self, ace_instance_cls):
        assert len(ace_instance_cls.MATERIAL_TEMPS) > 0

    def test_all_temperatures_are_positive_integers(self, ace_instance_cls):
        for material, temp in ace_instance_cls.MATERIAL_TEMPS.items():
            assert isinstance(temp, int), f"{material} has non-int temp {temp!r}"
            assert 0 < temp <= 500, f"{material} has implausible temp {temp}"

    def test_material_names_are_unique_case_insensitively(self, ace_instance_cls):
        seen = [m.lower() for m in ace_instance_cls.MATERIAL_TEMPS]
        assert len(seen) == len(set(seen)), "duplicate material names differing only in case"

    def test_placeholder_names_are_absent(self, ace_instance_cls):
        # 'Unknown' must never be a preset: it is the slot's no-data sentinel.
        assert "Unknown" not in ace_instance_cls.MATERIAL_TEMPS

    @pytest.mark.parametrize("material,expected", [
        ("PLA", 210),
        ("PETG", 240),
        ("ABS", 250),
        ("ASA", 260),
        ("TPU", 230),
        ("PEEK", 380),
    ])
    def test_known_materials_have_expected_temps(self, ace_instance_cls, material, expected):
        assert ace_instance_cls.MATERIAL_TEMPS[material] == expected

    def test_pla_variants_are_grouped_first(self, ace_instance_cls):
        # Insertion order drives the slot editor's dropdown, so the PLA family
        # is expected to lead the table.
        order = list(ace_instance_cls.MATERIAL_TEMPS)
        assert all(name.startswith("PLA") for name in order[:5])


class TestMaterialTempLookup:
    @pytest.mark.parametrize("query", ["PLA", "pla", "Pla", " PLA ", "pLa"])
    def test_lookup_is_case_and_whitespace_insensitive(self, ace_instance_cls, query):
        assert ace_instance_cls.material_temp(query) == ace_instance_cls.MATERIAL_TEMPS["PLA"]

    def test_multiword_material_resolves(self, ace_instance_cls):
        assert ace_instance_cls.material_temp("PLA Matte") == ace_instance_cls.MATERIAL_TEMPS["PLA Matte"]

    def test_unknown_material_returns_default_temp(self, ace_instance_cls):
        assert ace_instance_cls.material_temp("Unobtainium") == ace_instance_cls.DEFAULT_TEMP

    def test_default_argument_is_honoured(self, ace_instance_cls):
        assert ace_instance_cls.material_temp("Unobtainium", default=999) == 999

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_material_returns_default(self, ace_instance_cls, value):
        assert ace_instance_cls.material_temp(value) == ace_instance_cls.DEFAULT_TEMP


class TestMmuShimMaterialTable:
    """The shim publishes the table so the UI has one source to read."""

    def test_shim_table_matches_instance_table(self, ace_instance_cls):
        from extras.ace import mmu_shim

        published = mmu_shim._material_table()
        assert published == ace_instance_cls.MATERIAL_TEMPS

    def test_shim_table_preserves_declaration_order(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert list(mmu_shim._material_table()) == list(ace_instance_cls.MATERIAL_TEMPS)

    def test_gate_temp_prefers_the_slot_value(self, ace_instance_cls):
        from extras.ace import mmu_shim

        # A slot holding PEEK but storing 350C must report 350, not the 380 default.
        assert mmu_shim._resolve_gate_temp({"temp": 350}, "PEEK") == 350

    def test_gate_temp_falls_back_to_the_material_default(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert mmu_shim._resolve_gate_temp({"temp": 0}, "PEEK") == 380

    def test_gate_temp_falls_back_for_absent_temp_key(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert mmu_shim._resolve_gate_temp({}, "PETG") == 240

    def test_gate_temp_handles_junk_values(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert mmu_shim._resolve_gate_temp({"temp": "hot"}, "PETG") == 240
        assert mmu_shim._resolve_gate_temp({"temp": None}, "PETG") == 240

    def test_gate_temp_for_unknown_material_is_zero(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert mmu_shim._resolve_gate_temp({"temp": 0}, "Unobtainium") == 0

    def test_material_lookup_is_case_insensitive(self, ace_instance_cls):
        from extras.ace import mmu_shim

        assert mmu_shim._resolve_gate_temp({"temp": 0}, "petg") == 240


class TestPluginAlignmentWithBackend:
    """The OrcaSlicer plugin must cover every material the ACE can carry."""

    def test_every_backend_material_has_an_inherits_mapping(self, orca_sync, ace_instance_cls):
        unmapped = [
            material for material in ace_instance_cls.MATERIAL_TEMPS
            if material.upper() not in orca_sync.MATERIAL_INHERITS
        ]
        assert unmapped == [], f"materials with no OrcaSlicer base preset: {unmapped}"

    def test_fallback_temp_matches_backend_pla(self, orca_sync, ace_instance_cls):
        # The plugin's last-resort temperature should agree with the backend's
        # PLA default, so a slot with no metadata is not synced inconsistently.
        assert orca_sync.DEFAULT_NOZZLE_TEMP == ace_instance_cls.MATERIAL_TEMPS["PLA"]

    def test_shared_material_temps_agree(self, orca_sync, ace_instance_cls):
        """Temps the plugin would derive from the backend table must round-trip."""
        for material, expected in ace_instance_cls.MATERIAL_TEMPS.items():
            assert orca_sync.lookup_material_temp(
                ace_instance_cls.MATERIAL_TEMPS, material
            ) == expected
