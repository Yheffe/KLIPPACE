"""The injected card's cache-buster must track the card's content.

`index.html` belongs to Fluidd/Mainsail, so nothing regenerates the URLs that
load the card. The buster was originally a one-off epoch stamped when the card
was first injected, which meant it never changed again: after a card update the
browser kept serving its cached copy, and a fix that was provably live on disk
(and correct over HTTP) stayed invisible in the UI. That happened with the slot
editor colour fix on 2026-10-05.

`refresh_klippace_cache_buster` in the shared web library now re-stamps it from a
content fingerprint. These tests drive that function in bash against a fixture
that mirrors the real layout, including the `./assets/` path prefix and matching
symlinks in both directories.

The function is shared by installer.sh, acepro-mmu-dashboard/install.sh and
scripts/deploy.sh, so it is worth pinning.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = REPO_ROOT / "acepro-mmu-dashboard" / "web"
WEB_LIB = REPO_ROOT / "acepro-mmu-dashboard" / "shared" / "web_install.sh"
CARD_FILES = ["klippace-tool-mapper.js", "klippace-tool-mapper.css"]

bash = shutil.which("bash")


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bash, "-c", script], cwd=cwd, capture_output=True, text=True, timeout=60
    )


def _make_fixture(tmp_path: Path, index_body: str | None = None) -> Path:
    """Build a UI dir like the printer's: root + assets symlinks, an index.html."""
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    for name in CARD_FILES:
        (ui / name).symlink_to(WEB_SRC / name)
        (ui / "assets" / name).symlink_to(WEB_SRC / name)

    if index_body is None:
        index_body = (
            "<html><head>\n"
            '  <link rel="manifest" href="./manifest.webmanifest">'
            '  <link rel="stylesheet" href="./klippace-tool-mapper.css?v=1791034375">\n'
            "  </head><body>\n"
            '    <script type="module" src="./assets/klippace-tool-mapper.js?v=1791034375">'
            "</script>\n"
            "  </body></html>\n"
        )
    (ui / "index.html").write_text(index_body)
    return ui


def _preamble() -> str:
    return textwrap.dedent(
        """
        set -u
        print_info()    { echo "INFO $*"; }
        print_success() { echo "OK $*"; }
        print_warning() { echo "WARN $*"; }
        print_error()   { echo "ERR $*"; }
        create_or_replace_symlink() { :; }
        . "%s"
        """
    ) % WEB_LIB


def _buster(ui: Path, name: str) -> str:
    """The ?v= currently on the line that loads `name`."""
    text = (ui / "index.html").read_text()
    for line in text.splitlines():
        if name in line:
            _, _, rest = line.partition(name + "?v=")
            if rest:
                return rest.split('"')[0].split("'")[0]
    return ""


@pytest.mark.skipif(bash is None, reason="bash is required")
class TestCacheBuster:
    def test_stale_epoch_is_replaced(self, tmp_path):
        ui = _make_fixture(tmp_path)
        assert _buster(ui, "klippace-tool-mapper.js") == "1791034375"

        res = _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert res.returncode == 0, res.stderr

        got = _buster(ui, "klippace-tool-mapper.js")
        assert got != "1791034375", "the frozen epoch must be replaced"
        assert got, "a buster must be present"

    def test_path_prefix_is_preserved(self, tmp_path):
        """The live HTML loads ./assets/… — the rewrite must not drop that."""
        ui = _make_fixture(tmp_path)
        _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert "./assets/klippace-tool-mapper.js?v=" in (ui / "index.html").read_text()

    def test_both_card_files_are_stamped(self, tmp_path):
        ui = _make_fixture(tmp_path)
        _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert _buster(ui, "klippace-tool-mapper.js"), ".js not stamped"
        assert _buster(ui, "klippace-tool-mapper.css"), ".css not stamped"

    def test_buster_matches_the_content_fingerprint(self, tmp_path):
        ui = _make_fixture(tmp_path)
        res = _run(
            f"{_preamble()}\n"
            f"echo FINGERPRINT=$(_klippace_card_version '{ui}')\n"
            f"refresh_klippace_cache_buster '{ui}' test-ui",
            tmp_path,
        )
        expected = [
            l.split("=", 1)[1] for l in res.stdout.splitlines() if l.startswith("FINGERPRINT=")
        ][0]
        assert _buster(ui, "klippace-tool-mapper.js") == expected

    def test_idempotent_leaves_the_file_untouched(self, tmp_path):
        """Runs on every deploy, so an unchanged card must not rewrite index.html."""
        ui = _make_fixture(tmp_path)
        _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        before = (ui / "index.html").read_bytes()

        res = _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert res.returncode == 0, res.stderr
        assert (ui / "index.html").read_bytes() == before, (
            "a second run with unchanged content rewrote index.html; the mtime "
            "churn would defeat the point of a stable cache-buster"
        )

    def test_content_change_restamps(self, tmp_path):
        ui = _make_fixture(tmp_path)
        _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        first = _buster(ui, "klippace-tool-mapper.js")

        # Append to the file the symlink points at, i.e. the served bytes.
        target = WEB_SRC / "klippace-tool-mapper.js"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n// cache-buster probe\n")
            _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
            assert _buster(ui, "klippace-tool-mapper.js") != first, (
                "changed card content must produce a new buster or clients keep "
                "the stale copy"
            )
        finally:
            target.write_bytes(original)

    def test_unpatched_index_is_left_alone(self, tmp_path):
        """Don't touch a UI that never had the card injected."""
        ui = _make_fixture(tmp_path, index_body="<html><head></head><body></body></html>\n")
        before = (ui / "index.html").read_bytes()
        res = _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert res.returncode == 0, res.stderr
        assert (ui / "index.html").read_bytes() == before

    def test_missing_index_is_not_an_error(self, tmp_path):
        ui = tmp_path / "empty"
        ui.mkdir()
        res = _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        assert res.returncode == 0, res.stderr

    def test_fresh_patch_stamps_a_buster(self, tmp_path):
        """A brand new injection must not be left with a bare URL."""
        ui = _make_fixture(tmp_path, index_body="<html><head>\n  </head><body>\n  </body></html>\n")
        res = _run(f"{_preamble()}\npatch_klippace_index_html '{ui}' test-ui", tmp_path)
        assert res.returncode == 0, res.stderr
        assert _buster(ui, "klippace-tool-mapper.js"), (
            "a freshly injected card has no cache-buster, so a UI that caches by "
            "URL would keep serving the first card it ever loaded"
        )

    def test_other_lines_are_not_modified(self, tmp_path):
        ui = _make_fixture(tmp_path)
        before = [
            l for l in (ui / "index.html").read_text().splitlines()
            if "klippace" not in l
        ]
        _run(f"{_preamble()}\nrefresh_klippace_cache_buster '{ui}' test-ui", tmp_path)
        after = [
            l for l in (ui / "index.html").read_text().splitlines()
            if "klippace" not in l
        ]
        assert after == before, "only the card lines may be touched"
