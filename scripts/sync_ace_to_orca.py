#!/usr/bin/env python3
"""
Command-line entry point for the KLIPPACE ACE Pro -> OrcaSlicer filament sync.

The implementation lives in the OrcaSlicer plugin so there is only ever one
copy of the logic:

    plugins/orcaslicer/klippace_ace_sync.py

This launcher imports that module (it degrades gracefully outside OrcaSlicer,
where `import orca` fails and capability registration is skipped) and calls the
same `sync_filaments_to_orcaslicer()` the plugin's Script and Page capabilities
use.

Usage:
    python3 scripts/sync_ace_to_orca.py
    python3 scripts/sync_ace_to_orca.py --host 192.168.1.168
    python3 scripts/sync_ace_to_orca.py --json

Exit codes:
    0  sync succeeded
    1  sync ran but reported failure
    2  the plugin module could not be located
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "orcaslicer"
PLUGIN_MODULE = "klippace_ace_sync"


def load_plugin():
    """Import the OrcaSlicer plugin module from the repo checkout."""
    if not (PLUGIN_DIR / f"{PLUGIN_MODULE}.py").is_file():
        sys.stderr.write(
            f"error: {PLUGIN_MODULE}.py not found in {PLUGIN_DIR}\n"
        )
        raise SystemExit(2)

    plugin_path = str(PLUGIN_DIR)
    if plugin_path not in sys.path:
        sys.path.insert(0, plugin_path)

    import importlib

    return importlib.import_module(PLUGIN_MODULE)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sync_ace_to_orca.py",
        description=(
            "Sync ACE Pro filament slots into OrcaSlicer user filament presets. "
            "Printer connection details are read from the active OrcaSlicer "
            "printer profile unless --host is given."
        ),
    )
    parser.add_argument(
        "--host",
        metavar="HOST",
        help="Override the printer address. Accepts 'host', 'host:port' or a full URL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the full result payload as JSON instead of a summary.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    plugin = load_plugin()

    result = plugin.sync_filaments_to_orcaslicer(host=args.host)

    if args.as_json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(result.get("message", "No message returned."))

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
