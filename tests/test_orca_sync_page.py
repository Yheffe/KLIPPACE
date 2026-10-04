"""The ACE Pro tab's own data path.

The tab used to render once from a cached snapshot and then never change, so a
sync did nothing visible until OrcaSlicer was restarted. It can now ask for live
data and receive it, because the host delivers ``post_message`` payloads to the
page's ``window.orca.onMessage`` handlers:

    Registering orca.pages bindings
      get_ui, get_icon, post_message

``handle_page_action`` is module-level rather than a capability method for a
concrete reason: outside OrcaSlicer ``import orca`` fails, so the capability
classes are never defined and a method would be untestable.
"""

from __future__ import annotations

import json
import logging

import pytest


PRINTER = {"printer_name": "Voron 2.4 350", "base_url": "http://10.0.0.1:7125"}


def _slot(index=0, status="ready", material="PLA", color="#FFFFFF", **extra):
    slot = {
        "index": index, "status": status, "material": material, "color": color,
        "color_name": "", "temp": 210, "bed_temp": 60, "sku": "", "vendor": "",
        "custom_name": "",
    }
    slot.update(extra)
    return slot


class Collector:
    """Stands in for PagesPluginCapabilityBase.post_message."""

    def __init__(self, raises=False):
        self.payloads = []
        self.raises = raises

    def __call__(self, payload):
        if self.raises:
            raise RuntimeError("bridge down")
        self.payloads.append(payload)


class TestBuildPagePayload:
    def test_preset_label_matches_what_the_sync_writes(self, orca_sync):
        """The label and the filename must not diverge.

        The label used to include the colour, so a synced file named
        'ACE T0 - PLA' was described in the tab as 'ACE T0 - PLA White'.
        """
        payload = orca_sync.build_page_payload(
            [_slot(0, material="PETG", color="#0AC83C")], PRINTER)
        assert payload["slots"][0]["preset"] == "ACE T0 - PETG"

    def test_custom_name_wins(self, orca_sync):
        payload = orca_sync.build_page_payload(
            [_slot(3, custom_name="Galaxy Black")], PRINTER)
        assert payload["slots"][0]["preset"] == "Galaxy Black"
        assert payload["slots"][0]["custom_name"] == "Galaxy Black"

    def test_empty_slot_has_no_preset_and_is_not_ready(self, orca_sync):
        payload = orca_sync.build_page_payload(
            [_slot(1, status="empty", material="")], PRINTER)
        slot = payload["slots"][0]
        assert slot["ready"] is False
        assert slot["preset"] == ""
        assert slot["material"] == "Empty"

    def test_printer_and_flags_are_carried(self, orca_sync):
        payload = orca_sync.build_page_payload([_slot()], PRINTER, live=True)
        assert payload["printer"] == "Voron 2.4 350"
        assert payload["base_url"] == "http://10.0.0.1:7125"
        assert payload["live"] is True
        assert payload["error"] == ""

    def test_error_is_carried_through(self, orca_sync):
        payload = orca_sync.build_page_payload([], {}, live=False, error="offline")
        assert payload["error"] == "offline"
        assert payload["live"] is False

    @pytest.mark.parametrize("bad", [
        "not-a-dict",
        None,
        {"index": "not-a-number", "status": "ready", "material": "PLA"},
    ])
    def test_malformed_slots_degrade_instead_of_raising(self, orca_sync, bad):
        # One bad record must not blank the whole tab.
        payload = orca_sync.build_page_payload([bad, _slot(1)], PRINTER)
        assert isinstance(payload["slots"], list)

    def test_non_list_slots_is_tolerated(self, orca_sync):
        assert orca_sync.build_page_payload(None, None)["slots"] == []

    def test_payload_is_json_serialisable(self, orca_sync):
        payload = orca_sync.build_page_payload([_slot(), _slot(1, strict=False)], PRINTER)
        json.dumps(payload)  # must not raise


class TestHandlePageAction:
    def test_status_fetches_and_pushes_live_data(self, orca_sync):
        post = Collector()
        fetch = lambda: ([_slot(2, material="PETG")], PRINTER)
        assert orca_sync.handle_page_action("status", post, fetch_slots=fetch) == "status"
        assert len(post.payloads) == 1
        assert post.payloads[0]["live"] is True
        assert post.payloads[0]["slots"][0]["material"] == "PETG"

    def test_status_failure_falls_back_and_says_so(self, orca_sync, monkeypatch):
        """A dead printer must not leave the tab blank or lie about being live."""
        monkeypatch.setattr(orca_sync, "load_cached_snapshot",
                            lambda: ([_slot(0)], PRINTER))
        post = Collector()

        def boom():
            raise RuntimeError("printer offline")

        result = orca_sync.handle_page_action("status", post, fetch_slots=boom)

        assert result == "status-error"
        assert post.payloads[0]["live"] is False
        assert "printer offline" in post.payloads[0]["error"]
        assert post.payloads[0]["slots"]          # last snapshot still shown

    def test_sync_pushes_the_new_state(self, orca_sync):
        post = Collector()
        run_sync = lambda: {
            "success": True, "message": "ok", "slots": [_slot(1)], "network": PRINTER,
        }
        assert orca_sync.handle_page_action("sync", post, run_sync=run_sync) == "sync"
        assert post.payloads[0]["live"] is True
        assert post.payloads[0]["error"] == ""

    def test_failed_sync_is_reported_to_the_page(self, orca_sync):
        post = Collector()
        run_sync = lambda: {
            "success": False, "message": "no filament dirs", "slots": [], "network": {},
        }
        assert orca_sync.handle_page_action("sync", post, run_sync=run_sync) == "sync"
        assert "no filament dirs" in post.payloads[0]["error"]

    def test_sync_raising_does_not_escape(self, orca_sync):
        post = Collector()

        def boom():
            raise RuntimeError("kaboom")

        assert orca_sync.handle_page_action("sync", post, run_sync=boom) == "sync-error"
        assert "kaboom" in post.payloads[0]["error"]

    @pytest.mark.parametrize("action", ["", None, "nonsense", "Status"])
    def test_unknown_actions_are_ignored(self, orca_sync, action):
        post = Collector()
        assert orca_sync.handle_page_action(action, post) == "ignored"
        assert post.payloads == []

    def test_a_broken_bridge_does_not_raise(self, orca_sync, caplog):
        """A failing post_message must not escape into the host's dispatcher.

        This was a real bug: post() sat inside the status try block, so a bridge
        failure was caught and then post() was called AGAIN from the except
        handler, which propagated out of the function entirely.
        """
        post = Collector(raises=True)
        fetch = lambda: ([_slot()], PRINTER)
        with caplog.at_level(logging.ERROR):
            result = orca_sync.handle_page_action("status", post, fetch_slots=fetch)
        assert result == "status"            # the fetch itself succeeded
        assert any("Could not push" in r.getMessage() for r in caplog.records)

    def test_a_broken_bridge_does_not_break_sync_either(self, orca_sync):
        post = Collector(raises=True)
        run_sync = lambda: {"success": True, "message": "ok",
                            "slots": [_slot()], "network": PRINTER}
        assert orca_sync.handle_page_action("sync", post, run_sync=run_sync) == "sync"
