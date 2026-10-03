"""Shared pytest fixtures for the KLIPPACE test suite."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCA_PLUGIN_DIR = REPO_ROOT / "plugins" / "orcaslicer"
ORCA_PLUGIN_MODULE = "klippace_ace_sync"


@pytest.fixture(scope="session")
def orca_sync():
    """Import the OrcaSlicer sync plugin standing in for an installed plugin.

    The plugin lives in a hyphenated directory that is not a valid Python
    package name, so it is loaded by adding its directory to ``sys.path`` — the
    same approach ``scripts/sync_ace_to_orca.py`` uses. Importing outside
    OrcaSlicer is fine: ``import orca`` fails and capability registration is
    skipped.
    """
    plugin_path = str(ORCA_PLUGIN_DIR)
    if plugin_path not in sys.path:
        sys.path.insert(0, plugin_path)
    return importlib.import_module(ORCA_PLUGIN_MODULE)


@pytest.fixture
def ace_instance_cls():
    """The AceInstance class, exposing the authoritative material table."""
    from extras.ace.instance import AceInstance

    return AceInstance


@pytest.fixture
def orca_app_dir(tmp_path, monkeypatch, orca_sync):
    """Redirect the plugin's OrcaSlicer app directory into a temp directory."""
    app_dir = tmp_path / "OrcaSlicer"
    app_dir.mkdir()
    monkeypatch.setattr(orca_sync, "get_orca_app_dir", lambda: app_dir)
    return app_dir


@pytest.fixture
def user_filament_dirs(orca_app_dir):
    """Create two OrcaSlicer user filament directories inside the temp app dir."""
    dirs = []
    for name in ("default", "1111111111"):
        fil = orca_app_dir / "user" / name / "filament"
        fil.mkdir(parents=True)
        dirs.append(fil)
    return dirs
