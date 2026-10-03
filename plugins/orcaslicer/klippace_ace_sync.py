# /// script
# name = "KLIPPACE ACE Pro Sync"
# version = "1.2.0"
# description = "One-click filament and color sync from Anycubic ACE Pro via Moonraker"
# ///

"""
KLIPPACE ACE Pro Sync Plugin for OrcaSlicer.

Dynamically retrieves printer network connection parameters (host, port, API key)
directly from the active OrcaSlicer printer profile (or OrcaSlicer configuration),
then queries Moonraker to synchronize ACE Pro filaments, colors, temperatures,
and RFID tags into OrcaSlicer user profiles.

Slots that carry a custom preset name (set via ``ACE_SET_SLOT
FILAMENT_SETTINGS_ID=`` and surfaced by ``moonraker_lane_sync`` as
``filament_settings_id``) are written under that name instead of the generated
``ACE T<slot> - <material> <colour>`` default.
"""

import json
import logging
import os
import platform
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import orca
except ImportError:
    orca = None

DEFAULT_PRINTER_HOST = "192.168.1.168"
DEFAULT_PRINTER_PORT = 7125

# An ACE Pro unit exposes four filament lanes.
MAX_SLOTS = 4

# Tracks the preset files this plugin wrote so that renaming a slot (or giving it
# a custom preset name) removes the previous filename. Without it, a rename would
# leave an orphaned preset behind, because a custom name carries no slot marker.
MANIFEST_VERSION = 1
MANIFEST_FILENAME = "klippace_ace_sync_manifest.json"

COLOR_THRESHOLD_WHITE = 35
COLOR_THRESHOLD_BLACK = 30
COLOR_THRESHOLD_PALETTE = 80

EXACT_COLOR_MAP = {
    "#EFF0F1": ("#FFFFFF", "White"),  # Anycubic Basic White RFID (AHPLBW-106)
    "#FF7F32": ("#FF7F32", "Orange"), # Anycubic Vibrant Orange (AHPLVO-106)
    "#FF3A2F": ("#FF3A2F", "Red"),    # Anycubic RFID Red (AHPLBK-101)
    "#000000": ("#000000", "Black"),
    "#FFFFFF": ("#FFFFFF", "White"),
    "#0000FF": ("#0000FF", "Blue"),
    "#00FF00": ("#00FF00", "Green"),
    "#FFFF00": ("#FFFF00", "Yellow"),
    "#808080": ("#808080", "Gray"),
    "#A52A2A": ("#A52A2A", "Brown"),
    "#800080": ("#800080", "Purple"),
    "#FFC0CB": ("#FFC0CB", "Pink"),
    "#00FFFF": ("#00FFFF", "Cyan"),
}

SKU_HINTS = {
    "BW": ("#FFFFFF", "White"),
    "WHT": ("#FFFFFF", "White"),
    "BK": ("#000000", "Black"),
    "BLK": ("#000000", "Black"),
    "VO": ("#FF7F32", "Orange"),
    "ORG": ("#FF7F32", "Orange"),
    "RD": ("#FF3A2F", "Red"),
    "RED": ("#FF3A2F", "Red"),
    "BL": ("#0000FF", "Blue"),
    "BLU": ("#0000FF", "Blue"),
    "GN": ("#00FF00", "Green"),
    "GRN": ("#00FF00", "Green"),
    "YL": ("#FFFF00", "Yellow"),
    "YEL": ("#FFFF00", "Yellow"),
    "GY": ("#808080", "Gray"),
    "GRY": ("#808080", "Gray"),
}

STANDARD_PALETTE = {
    "White": (255, 255, 255),
    "Black": (0, 0, 0),
    "Red": (255, 0, 0),
    "Orange": (255, 127, 50),
    "Yellow": (255, 255, 0),
    "Green": (0, 200, 0),
    "Blue": (0, 100, 255),
    "Cyan": (0, 255, 255),
    "Purple": (128, 0, 128),
    "Pink": (255, 192, 203),
    "Gray": (128, 128, 128),
    "Brown": (165, 42, 42),
}

# ---------------------------------------------------------------------------
# OrcaSlicer system filament library integration
# ---------------------------------------------------------------------------

# Every ``Generic * @System`` filament preset shipped in OrcaSlicer's
# OrcaFilamentLibrary, captured from a 2.4.0.4 install. A synced preset's
# ``inherits`` must name one of these (or another resolvable preset) or Orca
# cannot resolve the chain, so tests assert our mapping stays inside this set.
GENERIC_SYSTEM_FILAMENTS = frozenset({
    "Generic ABS @System",
    "Generic ASA @System",
    "Generic BVOH @System",
    "Generic CoPE @System",
    "Generic EVA @System",
    "Generic HIPS @System",
    "Generic PA @System",
    "Generic PA-CF @System",
    "Generic PC @System",
    "Generic PCTG @System",
    "Generic PE @System",
    "Generic PE-CF @System",
    "Generic PETG @System",
    "Generic PETG HF @System",
    "Generic PETG-CF @System",
    "Generic PHA @System",
    "Generic PLA @System",
    "Generic PLA High Speed @System",
    "Generic PLA Matte @System",
    "Generic PLA Silk @System",
    "Generic PLA-CF @System",
    "Generic PP @System",
    "Generic PP-CF @System",
    "Generic PP-GF @System",
    "Generic PPA-CF @System",
    "Generic PPA-GF @System",
    "Generic PVA @System",
    "Generic SBS @System",
    "Generic Silk PLA @System",
    "Generic TPU @System",
})

# Best available Generic preset for each material the ACE can carry.
#
# Several materials have no Generic equivalent in Orca's library, so they map to
# the nearest family preset. ``inherits`` only supplies defaults (flow, cooling,
# pressure advance); the real material is written to ``filament_type`` by the
# payload, so an approximate base is safe and far better than inheriting PLA for
# everything.
MATERIAL_INHERITS = {
    # --- PLA family ---
    "PLA": "Generic PLA @System",
    "PLA+": "Generic PLA @System",
    "PLA-CF": "Generic PLA-CF @System",
    "PLA GLOW": "Generic PLA @System",
    "PLA HIGH SPEED": "Generic PLA High Speed @System",
    "PLA MARBLE": "Generic PLA @System",
    "PLA MATTE": "Generic PLA Matte @System",
    "PLA SE": "Generic PLA @System",
    "PLA SILK": "Generic PLA Silk @System",
    # --- PETG family ---
    "PETG": "Generic PETG @System",
    "PETG-CF": "Generic PETG-CF @System",
    # --- Styrenics ---
    "ABS": "Generic ABS @System",
    "ASA": "Generic ASA @System",
    "HIPS": "Generic HIPS @System",
    "SBS": "Generic SBS @System",
    # --- Flexible: no Generic TPE, TPU is the equivalent family ---
    "TPU": "Generic TPU @System",
    "TPE": "Generic TPU @System",
    # --- Soluble support ---
    "PVA": "Generic PVA @System",
    "BVOH": "Generic BVOH @System",
    # --- Engineering ---
    "PC": "Generic PC @System",
    "PC-ABS": "Generic PC @System",
    "PA": "Generic PA @System",
    "NYLON": "Generic PA @System",
    "PA-CF": "Generic PA-CF @System",
    "PCTG": "Generic PCTG @System",
    # Orca ships no Generic POM/PPS/PEEK/PPA. Map to the closest available
    # high-temperature base and rely on the payload's explicit temperatures.
    "POM": "Generic PLA @System",
    "PPS": "Generic PPA-CF @System",
    "PP": "Generic PP @System",
    "PPA": "Generic PPA-CF @System",
    "PEEK": "Generic PPA-CF @System",
}

# Used when a material has no mapping at all.
FALLBACK_INHERITS = "Generic PLA @System"

# Materials already reported as unmapped, so the warning is logged once each.
_WARNED_UNMAPPED_MATERIALS = set()

# Last-resort nozzle temperature when neither the slot nor the printer's
# material table knows better.
DEFAULT_NOZZLE_TEMP = 210
DEFAULT_BED_TEMP = 60


def resolve_filament_color(hex_code, sku="", vendor=""):
    """
    Normalize hex code and resolve a clean, friendly color name.
    Handles off-white RFID tags (e.g. Anycubic #EFF0F1), SKU substring codes,
    and nearest-neighbor Euclidean distance matching in RGB color space.
    Returns tuple: (normalized_hex, color_name).
    """
    if not hex_code:
        return "#FFFFFF", "White"

    hex_clean = str(hex_code).strip().upper()
    if not hex_clean.startswith("#"):
        hex_clean = f"#{hex_clean}"

    # Expand shorthand 3-character hex (e.g. #FFF -> #FFFFFF)
    if len(hex_clean) == 4:
        hex_clean = "#" + "".join([c * 2 for c in hex_clean[1:]])
    elif len(hex_clean) != 7:
        return hex_clean, hex_clean

    # 1. Exact match lookup
    if hex_clean in EXACT_COLOR_MAP:
        return EXACT_COLOR_MAP[hex_clean]

    # 2. Check SKU hints if available
    sku_upper = (sku or "").upper()
    for code, (norm_hex, name) in SKU_HINTS.items():
        if code in sku_upper:
            return norm_hex, name

    # 3. Distance matching in RGB
    try:
        r = int(hex_clean[1:3], 16)
        g = int(hex_clean[3:5], 16)
        b = int(hex_clean[5:7], 16)

        # Near white (e.g. #EFF0F1 dist sq = 677 <= 1225) -> snap to pure White #FFFFFF
        dist_sq_white = (255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2
        if dist_sq_white <= COLOR_THRESHOLD_WHITE ** 2:
            return "#FFFFFF", "White"

        # Near black (dist sq <= 900) -> snap to pure Black #000000
        dist_sq_black = r ** 2 + g ** 2 + b ** 2
        if dist_sq_black <= COLOR_THRESHOLD_BLACK ** 2:
            return "#000000", "Black"

        best_name = None
        best_dist_sq = float("inf")
        for name, prgb in STANDARD_PALETTE.items():
            dist_sq = (r - prgb[0]) ** 2 + (g - prgb[1]) ** 2 + (b - prgb[2]) ** 2
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_name = name

        if best_dist_sq <= COLOR_THRESHOLD_PALETTE ** 2:
            return hex_clean, best_name
    except (ValueError, IndexError):
        logging.warning("Invalid hex format: %s", hex_code)

    return hex_clean, hex_clean


def get_color_name(hex_code, sku="", vendor=""):
    """Return friendly name for common filament hex colors."""
    _, name = resolve_filament_color(hex_code, sku=sku, vendor=vendor)
    return name


def sanitize_preset_name(name):
    """Make *name* safe to use as a filename on every supported platform."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned


def filament_slot_key(slot_idx):
    """OrcaSlicer's key for a filament slot: T0 is 'filament', T1+ is 'filament_NN'."""
    return "filament" if slot_idx == 0 else f"filament_{slot_idx:02d}"


def get_manifest_path():
    return get_orca_app_dir() / MANIFEST_FILENAME


def load_manifest():
    """Read the record of presets written by previous syncs.

    Returns ``{"version": int, "machine": str, "slots": {slot: [paths]}}``. An
    unreadable or corrupt manifest is treated as empty rather than fatal.
    """
    manifest = {"version": MANIFEST_VERSION, "machine": "", "slots": {}}
    path = get_manifest_path()
    if not path.exists():
        return manifest
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("manifest root is not an object")
        slots = data.get("slots")
        manifest["slots"] = slots if isinstance(slots, dict) else {}
        machine = data.get("machine")
        manifest["machine"] = str(machine) if machine else ""
        return manifest
    except Exception as e:
        logging.warning("Ignoring unreadable manifest %s: %s", path, e)
        return manifest


def save_manifest(manifest):
    path = get_manifest_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        tmp_path.replace(path)
        return True
    except Exception as e:
        logging.error("Failed to write manifest %s: %s", path, e)
        return False


def clean_slot_presets(filament_dirs, slot_idx, keep_paths, previous_paths):
    """
    Remove presets that a previous sync wrote for *slot_idx* but that are no
    longer current.

    Two sources are swept:
      * files recorded for this slot in the manifest (handles custom names)
      * legacy ``ACE T<slot> - *`` presets from syncs predating the manifest

    Anything in *keep_paths* is spared.
    """
    keep = {str(Path(p).resolve()) for p in keep_paths if p}
    candidates = []

    for recorded in previous_paths or []:
        candidates.append(Path(recorded))

    slot_prefix = f"ACE T{slot_idx} - "
    for fdir in filament_dirs:
        directory = Path(fdir)
        if not directory.exists():
            continue
        for item in directory.glob(f"{slot_prefix}*"):
            if item.suffix in (".json", ".info"):
                candidates.append(item)

    cleaned = []
    for item in candidates:
        try:
            if str(item.resolve()) in keep:
                continue
            if item.exists():
                item.unlink()
                cleaned.append(str(item))
                logging.info("Cleaned stale preset: %s", item)
        except OSError as e:
            logging.warning("Failed to remove stale preset %s: %s", item, e)
    return cleaned


def _split_list(value):
    """Parse an OrcaSlicer comma-separated field into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value]
    raw = str(value)
    if not raw.strip():
        return []
    return [part.strip() for part in raw.split(",")]


def _preset_slot_count(preset):
    """How many filament slots this orca_presets bundle actually defines.

    Taken from the keys Orca itself wrote (``filament`` plus ``filament_NN``)
    rather than assumed to be MAX_SLOTS, so a single-extruder machine is not
    handed four colours.
    """
    count = 1 if "filament" in preset else 0
    for key in preset:
        if key.startswith("filament_") and key[9:].isdigit():
            count = max(count, int(key[9:]) + 1)
    return count


def _is_managed_machine(preset, printer_name, last_machine=""):
    """True when this orca_presets bundle belongs to the printer being synced."""
    machine = str(preset.get("machine") or "")
    if printer_name and machine == printer_name:
        return True
    if last_machine and machine == last_machine:
        return True
    # Last resort for an unresolvable active machine: recognise a bundle whose
    # filament slots we generated. Custom preset names defeat this, which is why
    # the machine is also recorded in the manifest.
    for key in ("filament", "filament_01", "filament_02", "filament_03"):
        if str(preset.get(key) or "").startswith("ACE T"):
            return True
    return False


def _apply_slot_presets(preset, items_by_slot, slot_count):
    """Map synced presets/colours onto one orca_presets bundle. Returns True if changed."""
    colors = _split_list(preset.get("filament_colors"))
    while len(colors) < slot_count:
        colors.append("#000000")

    changed = False
    for slot in range(slot_count):
        item = items_by_slot.get(slot)
        if not item:
            continue
        key = filament_slot_key(slot)
        if str(preset.get(key) or "") != item["name"]:
            preset[key] = item["name"]
            changed = True
        # Only the colour list is index-aligned; never write a preset name into it.
        if colors[slot] != item["color"]:
            colors[slot] = item["color"]
            changed = True

    if not changed:
        return False

    color_str = ",".join(colors)
    preset["filament_colors"] = color_str
    # filament_multi_colors is only maintained by Orca on machines that support
    # mixed filaments; it is "" elsewhere and must stay that way.
    if str(preset.get("filament_multi_colors") or "").strip():
        preset["filament_multi_colors"] = color_str
    return True


def update_orcaslicer_conf(synced_items, printer_name=None, last_machine=""):
    """
    Map synced slot presets and colours onto the matching machine profile in
    ``orca_presets``.

    Returns the list of machine names that were updated (empty when nothing
    matched or nothing changed).
    """
    app_dir = get_orca_app_dir()
    conf_path = app_dir / "OrcaSlicer.conf"
    if not conf_path.exists():
        return []

    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            conf = json.load(f)

        items_by_slot = {int(it["slot"]): it for it in synced_items}
        orca_presets = conf.get("orca_presets")
        if not isinstance(orca_presets, list):
            logging.warning("OrcaSlicer.conf has no orca_presets list; skipping.")
            return []

        updated_machines = []
        for p in orca_presets:
            if not isinstance(p, dict):
                continue
            if not _is_managed_machine(p, printer_name, last_machine):
                continue
            slot_count = _preset_slot_count(p)
            if slot_count < 1:
                continue
            if _apply_slot_presets(p, items_by_slot, slot_count):
                updated_machines.append(str(p.get("machine") or ""))

        if updated_machines:
            tmp_path = conf_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=4)
            tmp_path.replace(conf_path)
            logging.info(
                "Updated OrcaSlicer.conf machine preset(s): %s",
                ", ".join(m for m in updated_machines if m) or "(unnamed)",
            )
        return updated_machines
    except Exception as e:
        logging.error("Failed to update OrcaSlicer.conf: %s", e)
    return []


def resolve_inherits_name(material):
    """OrcaSlicer base preset for *material*.

    Matches case-insensitively against MATERIAL_INHERITS and falls back to
    FALLBACK_INHERITS for anything unmapped, logging once so an unexpected
    material does not pass silently.
    """
    key = str(material or "").strip().upper()
    if key in MATERIAL_INHERITS:
        return MATERIAL_INHERITS[key]

    unmapped = key or "(empty)"
    if unmapped not in _WARNED_UNMAPPED_MATERIALS:
        _WARNED_UNMAPPED_MATERIALS.add(unmapped)
        logging.warning(
            "No OrcaSlicer base preset mapped for material %r; using %s",
            unmapped, FALLBACK_INHERITS,
        )
    return FALLBACK_INHERITS


def lookup_material_temp(material_temps, material, default=DEFAULT_NOZZLE_TEMP):
    """Nozzle temperature for *material* from the printer's published table.

    ``material_temps`` is ``mmu.material_temps``, which the ACE module derives
    from ``AceInstance.MATERIAL_TEMPS``. Matching is case-insensitive so RFID
    spellings resolve. Returns *default* when the material is unknown.
    """
    if not isinstance(material_temps, dict) or not material:
        return default
    key = str(material).strip()
    if key in material_temps:
        value = material_temps[key]
    else:
        lowered = key.lower()
        value = next(
            (v for k, v in material_temps.items() if str(k).lower() == lowered),
            None,
        )
    try:
        temp = int(value)
    except (TypeError, ValueError):
        return default
    return temp if temp > 0 else default


def get_orca_app_dir():
    """Return the platform-specific OrcaSlicer application configuration directory."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return Path.home() / "Library/Application Support/OrcaSlicer"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "OrcaSlicer"
        return Path.home() / "AppData/Roaming/OrcaSlicer"
    else:  # Linux
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "OrcaSlicer"
        return Path.home() / ".config/OrcaSlicer"


def parse_network_endpoint(raw_host, port=None):
    """Safely parse host, port, scheme, and base_url using urllib.parse."""
    if not raw_host:
        raw_host = DEFAULT_PRINTER_HOST

    clean = str(raw_host).strip()
    if not clean.startswith("http://") and not clean.startswith("https://"):
        clean_url = f"http://{clean}"
        scheme = "http"
    else:
        clean_url = clean
        scheme = "https" if clean.startswith("https://") else "http"

    parsed = urllib.parse.urlparse(clean_url)
    hostname = parsed.hostname or clean.split("/")[0].split(":")[0]
    parsed_port = parsed.port or port

    if parsed_port and str(parsed_port).strip() not in ("80", "443"):
        base_url = f"{scheme}://{hostname}:{parsed_port}"
    else:
        base_url = f"{scheme}://{hostname}"

    return hostname, parsed_port, base_url


def resolve_printer_network_info(override_host=None):
    """
    Dynamically resolve printer network connection details from OrcaSlicer.

    Resolution hierarchy:
    1. If override_host is explicitly passed, parse and return immediately.
    2. Inspect active runtime orca.host preset bundle for current_printer_preset()
       -> 'print_host', 'printhost_port', 'printhost_apikey'.
    3. Inspect OrcaSlicer.conf for active selected machine and matching user profile JSON.
    4. Inspect OrcaSlicer.conf 'local_machines' dictionary.
    5. Fallback to DEFAULT_PRINTER_HOST if not configured.
    """
    if override_host:
        hostname, parsed_port, base_url = parse_network_endpoint(override_host)
        return {
            "host": hostname,
            "port": parsed_port,
            "apikey": None,
            "base_url": base_url,
            "printer_name": "Override Host",
        }

    host = None
    port = None
    apikey = None
    printer_name = None

    # 1. Query runtime OrcaSlicer API if running inside the slicer
    if orca and hasattr(orca, "host"):
        try:
            bundle = orca.host.preset_bundle()
            current = bundle.current_printer_preset()
            if current:
                printer_name = str(getattr(current, "name", "") or "").strip()

                def _get_preset_val(p, key):
                    try:
                        v = p.config_value(key)
                        if isinstance(v, (list, tuple)):
                            v = next((x for x in v if x not in (None, "")), "")
                        return str(v or "").strip()
                    except Exception:
                        return ""

                h = _get_preset_val(current, "print_host")
                if not h:
                    try:
                        h = str(bundle.full_config_value("print_host") or "").strip()
                    except Exception:
                        pass
                if h:
                    host = h
                p = _get_preset_val(current, "printhost_port")
                if p:
                    port = p
                k = _get_preset_val(current, "printhost_apikey")
                if k:
                    apikey = k
        except Exception as e:
            logging.debug("orca.host runtime preset lookup: %s", e)

    # 2. Inspect OrcaSlicer.conf and user machine JSON profiles
    app_dir = get_orca_app_dir()
    conf_path = app_dir / "OrcaSlicer.conf"

    if conf_path.exists():
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                conf = json.load(f)

            if not printer_name:
                printer_name = conf.get("presets", {}).get("machine")

            # Look up matching machine profile in user directories
            if not host and printer_name:
                user_base = app_dir / "user"
                if user_base.exists():
                    for mp in user_base.rglob("*.json"):
                        try:
                            if mp.parent.name != "machine":
                                continue
                            with open(mp, "r", encoding="utf-8") as mf_f:
                                m_data = json.load(mf_f)
                            m_name = m_data.get("name") or mp.stem
                            if m_name == printer_name:
                                if m_data.get("print_host"):
                                    host = str(m_data["print_host"]).strip()
                                if m_data.get("printhost_apikey"):
                                    apikey = str(m_data["printhost_apikey"]).strip()
                                if m_data.get("printhost_port"):
                                    port = str(m_data["printhost_port"]).strip()
                                if host:
                                    break
                        except (json.JSONDecodeError, IOError):
                            continue

            # Look up in OrcaSlicer.conf local_machines
            if not host:
                local_machines = conf.get("local_machines", {})
                for ip, dev in local_machines.items():
                    if printer_name and (dev.get("printer_type") == printer_name or dev.get("dev_name") == printer_name):
                        host = dev.get("dev_ip") or ip
                        apikey = apikey or dev.get("access_code")
                        break

            # Fallback to user_last_selected_machine in OrcaSlicer.conf
            if not host and conf.get("user_last_selected_machine"):
                host = str(conf["user_last_selected_machine"]).strip()
        except Exception as e:
            logging.debug("OrcaSlicer.conf lookup error: %s", e)

    # 3. Fallback default if not detected anywhere
    if not host:
        host = DEFAULT_PRINTER_HOST

    hostname, parsed_port, base_url = parse_network_endpoint(host, port)

    return {
        "host": hostname,
        "port": parsed_port,
        "apikey": apikey,
        "base_url": base_url,
        "printer_name": printer_name or "Active Printer",
    }


def _http_get_json(url, headers, timeout=3.5):
    """GET *url* and return the decoded JSON body, or None on any failure."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discover_ace_instances(raw_mmu):
    """Locate each ACE unit on the printer.

    Returns a list of ``(object_name, first_gate, num_gates)``. The MMU shim
    publishes ``unit`` with each unit's ``first_gate``/``num_gates``; when that
    is unavailable (older module, query failed) fall back to a single unit so a
    minimal setup still syncs.
    """
    units = raw_mmu.get("unit")
    discovered = []
    if isinstance(units, list):
        for idx, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            try:
                first_gate = int(unit.get("first_gate", idx * MAX_SLOTS))
                num_gates = int(unit.get("num_gates", MAX_SLOTS))
            except (TypeError, ValueError):
                continue
            if num_gates > 0 and first_gate >= 0:
                discovered.append((f"ace_instance_{idx}", first_gate, num_gates))

    if not discovered:
        discovered.append(("ace_instance_0", 0, MAX_SLOTS))

    discovered.sort(key=lambda entry: entry[1])
    return discovered


def build_gate_source_map(instances):
    """Map a global gate index to ``(object_name, local_slot)``."""
    mapping = {}
    for object_name, first_gate, num_gates in instances:
        for local_slot in range(num_gates):
            mapping[first_gate + local_slot] = (object_name, local_slot)
    return mapping


def fetch_moonraker_ace_data(net_info=None):
    """Fetch ACE Pro and lane_data objects from Moonraker API.

    Handles any number of ACE units: units are discovered from the MMU shim and
    every ``ace_instance_N`` object is queried, so a second ACE is synced
    instead of being silently ignored.
    """
    info = net_info or resolve_printer_network_info()
    base_url = info["base_url"]
    headers = {"User-Agent": "OrcaSlicer-KlippaceSync"}
    if info.get("apikey"):
        headers["X-Api-Key"] = info["apikey"]

    results = {
        "slots": [],
        "raw_mmu": {},
        "raw_ace": {},
        "ace_instances": [],
        "material_temps": {},
        "host": info["host"],
        "base_url": base_url,
        "printer_name": info["printer_name"],
    }

    # 1. Fetch lane_data from Moonraker database
    lane_data = {}
    try:
        url = f"{base_url}/server/database/item?namespace=lane_data"
        data = _http_get_json(url, headers)
        lane_data = (data.get("result", {}) or {}).get("value", {}) or {}
    except Exception as e:
        logging.warning("Failed to fetch lane_data from %s: %s", base_url, e)

    # 2. Fetch the MMU shim first: it tells us how many ACE units exist.
    printer_objects = {}
    try:
        url = f"{base_url}/printer/objects/query?mmu&mmu_machine"
        data = _http_get_json(url, headers)
        printer_objects = (data.get("result", {}) or {}).get("status", {}) or {}
    except Exception as e:
        logging.warning("Failed to fetch mmu object from %s: %s", base_url, e)

    results["raw_mmu"] = printer_objects.get("mmu", {}) or {}
    material_temps = results["raw_mmu"].get("material_temps")
    results["material_temps"] = material_temps if isinstance(material_temps, dict) else {}

    # 3. Query every ACE instance the shim reported
    instances = discover_ace_instances(results["raw_mmu"])
    results["ace_instances"] = [
        {"object": name, "first_gate": first, "num_gates": count}
        for name, first, count in instances
    ]

    instance_query = "&".join(name for name, _, _ in instances)
    instance_objects = {}
    if instance_query:
        try:
            url = f"{base_url}/printer/objects/query?{instance_query}"
            data = _http_get_json(url, headers)
            instance_objects = (data.get("result", {}) or {}).get("status", {}) or {}
        except Exception as e:
            logging.warning(
                "Failed to fetch ACE instances (%s) from %s: %s",
                instance_query, base_url, e,
            )

    results["raw_ace"] = instance_objects.get("ace_instance_0", {}) or {}

    # 4. Build one entry per ACE lane across every unit
    gate_source = build_gate_source_map(instances)
    total_gates = len(gate_source)
    try:
        reported_gates = int(results["raw_mmu"].get("num_gates") or 0)
    except (TypeError, ValueError):
        reported_gates = 0
    total_gates = max(total_gates, reported_gates)

    mmu_colors = results["raw_mmu"].get("gate_color") or []
    mmu_materials = results["raw_mmu"].get("gate_material") or []
    mmu_status = results["raw_mmu"].get("gate_status") or []

    for i in range(total_gates):
        ace_object, local_slot = gate_source.get(i, (instances[0][0], i))
        ace_slots = (instance_objects.get(ace_object) or {}).get("slots") or []

        slot_data = {
            "index": i,
            "tool": i,
            "ace_instance": ace_object,
            "local_slot": local_slot,
            "status": "empty",
            "material": "PLA",
            "color": "#FFFFFF",
            "color_name": "",
            "temp": 0,
            "bed_temp": 0,
            "vendor": "Anycubic",
            "sku": "",
            "rfid": False,
            "custom_name": "",
        }

        # Priority 1: the ACE instance owning this gate
        raw_s = ace_slots[local_slot] if local_slot < len(ace_slots) else None
        if raw_s:
            slot_data["status"] = raw_s.get("status", "empty")
            if raw_s.get("material") and raw_s.get("material") not in ("Unknown", "???"):
                slot_data["material"] = raw_s.get("material")
            if raw_s.get("temp", 0) > 0:
                slot_data["temp"] = raw_s.get("temp")
            if raw_s.get("rfid"):
                slot_data["rfid"] = True
            if raw_s.get("brand"):
                slot_data["vendor"] = raw_s.get("brand")
            if raw_s.get("sku"):
                slot_data["sku"] = raw_s.get("sku")
            # User-supplied preset name (ACE_SET_SLOT FILAMENT_SETTINGS_ID=)
            if raw_s.get("custom_name"):
                slot_data["custom_name"] = str(raw_s["custom_name"]).strip()

            rgb = raw_s.get("color")
            if rgb and len(rgb) >= 3 and any(c > 0 for c in rgb[:3]):
                slot_data["color"] = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

            hotbed = raw_s.get("hotbed_temp", {})
            if isinstance(hotbed, dict) and hotbed.get("min"):
                slot_data["bed_temp"] = hotbed.get("min")

        # Priority 2: lane_data overlay
        lane_key = f"lane{i + 1}"
        if lane_key in lane_data:
            ld = lane_data[lane_key]
            if ld.get("color"):
                slot_data["color"] = ld.get("color").upper()
            if ld.get("material") and ld.get("material") not in ("Unknown", "???"):
                slot_data["material"] = ld.get("material")
                if slot_data["status"] == "empty":
                    slot_data["status"] = "ready"
            if ld.get("nozzle_temp"):
                slot_data["temp"] = int(ld.get("nozzle_temp"))
            if ld.get("bed_temp"):
                slot_data["bed_temp"] = int(ld.get("bed_temp"))
            if ld.get("vendor"):
                slot_data["vendor"] = ld.get("vendor")
            if ld.get("sku"):
                slot_data["sku"] = ld.get("sku")
            # moonraker_lane_sync publishes the custom preset name under the
            # Happy Hare compatible key filament_settings_id.
            if ld.get("filament_settings_id"):
                slot_data["custom_name"] = str(ld["filament_settings_id"]).strip()

        # Fallback to MMU shim gate attributes if present. The shim aggregates
        # every ACE unit, so these arrays are already global gate indices.
        if i < len(mmu_colors) and mmu_colors[i]:
            if slot_data["color"] in ("#FFFFFF", "#000000") and str(mmu_colors[i]).startswith("#"):
                slot_data["color"] = mmu_colors[i].upper()
        if i < len(mmu_materials) and mmu_materials[i] and mmu_materials[i] != "Unknown":
            slot_data["material"] = mmu_materials[i]
        if i < len(mmu_status):
            # 1 = spool present, 0 = empty, -1 = unknown (keep what we have)
            if mmu_status[i] == 1:
                slot_data["status"] = "ready"
            elif mmu_status[i] == 0:
                slot_data["status"] = "empty"

        # Default fallback for unconfigured non-RFID slots
        if not slot_data["material"] or slot_data["material"].upper() in ("UNKNOWN", "???", "NONE", "N/A"):
            slot_data["material"] = "PLA"
        # Temperature: the slot's own value first, otherwise ask the printer's
        # material table (mmu.material_temps) rather than assuming PLA.
        if slot_data["temp"] <= 0:
            slot_data["temp"] = lookup_material_temp(material_temps, slot_data["material"])
        if slot_data["bed_temp"] <= 0:
            slot_data["bed_temp"] = DEFAULT_BED_TEMP

        # Resolve normalized color and friendly color name
        norm_col, col_name = resolve_filament_color(
            slot_data["color"],
            sku=slot_data.get("sku", ""),
            vendor=slot_data.get("vendor", ""),
        )
        slot_data["color"] = norm_col
        slot_data["color_name"] = col_name
        results["slots"].append(slot_data)

    return results


def find_orcaslicer_user_filament_dirs():
    """Find all OrcaSlicer user filament preset directories on the system."""
    dirs = []
    base_user = get_orca_app_dir() / "user"
    if base_user.exists():
        for user_path in base_user.iterdir():
            if user_path.is_dir():
                fil_dir = user_path / "filament"
                if fil_dir.exists():
                    dirs.append(str(fil_dir))
    return dirs


def sync_filaments_to_orcaslicer(host=None):
    """
    Main sync action:
    Dynamically queries Moonraker using network info from OrcaSlicer printer profile,
    builds universal filament presets for ready slots, cleans stale presets,
    updates OrcaSlicer configuration, and writes to OrcaSlicer user profiles.

    A slot with a custom preset name is written under that name; otherwise the
    generated ``ACE T<slot> - <material> <colour>`` name is used.
    """
    net_info = resolve_printer_network_info(override_host=host)
    ace_info = fetch_moonraker_ace_data(net_info=net_info)
    slots = ace_info["slots"]
    filament_dirs = find_orcaslicer_user_filament_dirs()

    if not filament_dirs:
        return {
            "success": False,
            "message": "Could not locate OrcaSlicer user filament profile directory.",
            "synced": [],
        }

    manifest = load_manifest()
    manifest_slots = manifest.get("slots") or {}

    synced_items = []
    new_manifest_slots = {}
    for s in slots:
        if s["status"] != "ready":
            continue

        slot_idx = s["index"]
        mat = s.get("material") or "PLA"
        if not mat or mat.upper() in ("UNKNOWN", "???", "NONE", "N/A"):
            mat = "PLA"

        col = s.get("color") or "#000000"
        col_name = s.get("color_name") or get_color_name(col, sku=s.get("sku", "")) or col
        temp = s.get("temp", 0)
        if not temp or temp <= 0:
            temp = lookup_material_temp(ace_info.get("material_temps"), mat)
        bed_temp = s.get("bed_temp", 0)
        if not bed_temp or bed_temp <= 0:
            bed_temp = DEFAULT_BED_TEMP

        vendor = s.get("vendor") or "Anycubic"
        sku = s.get("sku", "")

        # A user-supplied preset name wins, so a named spool lands in Orca under
        # the name the user chose on the printer.
        custom_name = sanitize_preset_name(s.get("custom_name"))
        generated_name = sanitize_preset_name(f"ACE T{slot_idx} - {mat} {col_name}")
        preset_name = custom_name or generated_name
        inherits_name = resolve_inherits_name(mat)

        # Empty compatible_printers means universal compatibility in OrcaSlicer
        preset_payload = {
            "compatible_printers": [],
            "default_filament_colour": [col],
            "filament_settings_id": [preset_name],
            "filament_type": [mat],
            "filament_vendor": [vendor],
            "from": "User",
            "hot_plate_temp": [str(bed_temp)],
            "hot_plate_temp_initial_layer": [str(bed_temp)],
            "textured_plate_temp": [str(bed_temp)],
            "textured_plate_temp_initial_layer": [str(bed_temp)],
            "inherits": inherits_name,
            "is_custom_defined": "0",
            "name": preset_name,
            "nozzle_temperature": [str(temp)],
            "nozzle_temperature_initial_layer": [str(temp)],
            "version": "2.4.0.0",
        }

        # Write to all discovered user directories, tracking exactly what we
        # produced so a later rename can be cleaned up.
        written_paths = []
        for fdir in filament_dirs:
            out_path = os.path.join(fdir, f"{preset_name}.json")
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(preset_payload, f, indent=4)
                written_paths.append(out_path)
            except Exception as e:
                logging.error("Failed writing preset %s: %s", out_path, e)

        # Drop anything a previous sync wrote for this slot that is no longer
        # current (renames, material/colour changes, legacy naming).
        clean_slot_presets(
            filament_dirs,
            slot_idx,
            keep_paths=written_paths,
            previous_paths=manifest_slots.get(str(slot_idx)),
        )
        new_manifest_slots[str(slot_idx)] = written_paths

        synced_items.append({
            "slot": slot_idx,
            "name": preset_name,
            "material": mat,
            "color": col,
            "temp": temp,
            "sku": sku,
            "custom_name": custom_name,
            "files": written_paths,
        })

    # Update OrcaSlicer.conf active presets, then remember which machine we
    # touched so a later sync can still find it if the active machine cannot be
    # resolved and the slots carry custom names.
    updated_machines = update_orcaslicer_conf(
        synced_items,
        printer_name=net_info.get("printer_name"),
        last_machine=manifest.get("machine", ""),
    )

    manifest["version"] = MANIFEST_VERSION
    manifest["slots"] = new_manifest_slots
    for machine in updated_machines:
        if machine:
            manifest["machine"] = machine
            break
    save_manifest(manifest)

    printer_label = f"{net_info['printer_name']} ({net_info['base_url']})"
    msg_lines = [f"Synced {len(synced_items)} slots from ACE Pro on {printer_label}:"]
    for it in synced_items:
        sku_str = f" [{it['sku']}]" if it["sku"] else ""
        named_str = " (custom preset name)" if it.get("custom_name") else ""
        msg_lines.append(
            f"• T{it['slot']}: {it['name']} — {it['material']} ({it['color']}) "
            f"@ {it['temp']}°C{sku_str}{named_str}"
        )

    if not synced_items:
        msg_lines.append("• No slots with filament were reported as ready.")

    summary_text = "\n".join(msg_lines)

    # Trigger OrcaSlicer preset bundle reload if available
    if orca and hasattr(orca, "host"):
        try:
            reload_fn = getattr(orca.host, "reload_local_bundle", None)
            if callable(reload_fn):
                reload_fn()
        except Exception:
            pass

    return {
        "success": True,
        "message": summary_text,
        "synced": synced_items,
        "slots": slots,
        "network": net_info,
    }


def render_html_page(slots, net_info):
    """Render sleek dark-mode HTML page for OrcaSlicer Pages capability."""
    printer_name = net_info.get("printer_name", "Active Printer")
    base_url = net_info.get("base_url", "http://192.168.1.168")

    slots_html = ""
    for s in slots:
        idx = s["index"]
        status = s["status"]
        color = s["color"]
        mat = s["material"] if status == "ready" else "Empty"
        temp = f"{s['temp']}°C" if status == "ready" else "---"
        bed = f"{s['bed_temp']}°C" if status == "ready" else "---"
        sku = s.get("sku") or (s.get("vendor") if status == "ready" else "No Spool")
        is_ready = status == "ready"

        # Show the preset name this slot will land under, so a custom name is
        # visible before syncing.
        custom = str(s.get("custom_name") or "").strip()
        if custom:
            preset_label = f"{custom} (custom)"
        elif is_ready:
            preset_label = f"ACE T{idx} - {mat} {s.get('color_name') or color}"
        else:
            preset_label = "---"

        badge_class = "badge-ready" if is_ready else "badge-empty"
        badge_text = "READY" if is_ready else "EMPTY"

        slots_html += f"""
        <div class="slot-card {'slot-active' if is_ready else 'slot-inactive'}">
            <div class="slot-header">
                <div class="slot-title">
                    <span class="slot-swatch" style="background-color: {color};"></span>
                    <span class="slot-name">Slot {idx} (T{idx})</span>
                </div>
                <span class="slot-badge {badge_class}">{badge_text}</span>
            </div>
            <div class="slot-details">
                <div class="detail-row"><span class="detail-label">Material:</span> <span class="detail-val">{mat}</span></div>
                <div class="detail-row"><span class="detail-label">Color:</span> <span class="detail-val">{color}</span></div>
                <div class="detail-row"><span class="detail-label">Nozzle / Bed:</span> <span class="detail-val">{temp} / {bed}</span></div>
                <div class="detail-row"><span class="detail-label">Spool Info:</span> <span class="detail-val">{sku}</span></div>
                <div class="detail-row"><span class="detail-label">Preset:</span> <span class="detail-val">{preset_label}</span></div>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: #18181c;
    color: #e4e4e7;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 24px;
}}
.container {{ max-width: 820px; margin: 0 auto; }}
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #27272a;
    padding-bottom: 16px;
    margin-bottom: 24px;
}}
.title-group h1 {{ font-size: 22px; font-weight: 700; color: #f43f5e; }}
.title-group p {{ font-size: 13px; color: #a1a1aa; margin-top: 4px; }}
.sync-btn {{
    background: #f43f5e;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
}}
.sync-btn:hover {{ background: #e11d48; }}
.slots-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 16px;
}}
.slot-card {{
    background: #27272a;
    border: 1px solid #3f3f46;
    border-radius: 10px;
    padding: 16px;
}}
.slot-active {{ border-left: 4px solid #10b981; }}
.slot-inactive {{ border-left: 4px solid #71717a; opacity: 0.7; }}
.slot-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}}
.slot-title {{ display: flex; align-items: center; gap: 10px; }}
.slot-swatch {{
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2px solid rgba(255,255,255,0.4);
    box-shadow: 0 0 8px rgba(0,0,0,0.5);
}}
.slot-name {{ font-size: 16px; font-weight: 600; color: #f4f4f5; }}
.slot-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
}}
.badge-ready {{ background: #064e3b; color: #34d399; }}
.badge-empty {{ background: #3f3f46; color: #a1a1aa; }}
.slot-details {{ display: flex; flex-direction: column; gap: 6px; }}
.detail-row {{ display: flex; justify-content: space-between; font-size: 13px; }}
.detail-label {{ color: #a1a1aa; }}
.detail-val {{ color: #f4f4f5; font-weight: 500; }}
.footer-note {{
    margin-top: 24px;
    font-size: 12px;
    color: #71717a;
    text-align: center;
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="title-group">
            <h1>Anycubic ACE Pro Filament Sync</h1>
            <p>Connected to <strong>{printer_name}</strong> at <strong>{base_url}</strong></p>
        </div>
        <button class="sync-btn" onclick="syncNow()">🔄 Sync Filaments to Slicer</button>
    </div>

    <div class="slots-grid">
        {slots_html}
    </div>

    <div class="footer-note">
        Clicking 'Sync Filaments' generates universal OrcaSlicer presets compatible with all printer profiles.
    </div>
</div>

<script>
function syncNow() {{
    if (window.orca && window.orca.postMessage) {{
        window.orca.postMessage(JSON.stringify({{"action": "sync"}}));
    }} else {{
        alert("Syncing filaments with host...");
    }}
}}
</script>
</body>
</html>"""


# OrcaSlicer Plugin Capabilities
if orca:
    class AceSyncScript(orca.script.ScriptPluginCapabilityBase):
        """Instant script capability under File > Plugins / Run."""

        def get_name(self):
            return "Sync ACE Pro Filaments"

        def execute(self, ctx=None):
            result = sync_filaments_to_orcaslicer()
            if hasattr(orca, "host") and hasattr(orca.host, "ui"):
                msg_fn = getattr(orca.host.ui, "message", None)
                if callable(msg_fn):
                    msg_fn(result["message"], title="ACE Pro Sync", icon="info")
            if result.get("success"):
                return orca.ExecutionResult.success(result["message"])
            return orca.ExecutionResult.failure(result["message"])


    _PAGES = getattr(orca, "pages", None)
    _PAGE_BASE = getattr(_PAGES, "PagesPluginCapabilityBase", None)

    if _PAGE_BASE is not None:
        class AceSyncPage(_PAGE_BASE):
            """Embedded interactive ACE Pro Page / Tab in OrcaSlicer."""

            def get_name(self):
                return "ACE Pro"

            def get_ui(self):
                net_info = resolve_printer_network_info()
                data = fetch_moonraker_ace_data(net_info=net_info)
                return render_html_page(data["slots"], net_info)

            def on_message(self, message):
                try:
                    payload = json.loads(message) if isinstance(message, str) else message
                    if payload.get("action") == "sync":
                        res = sync_filaments_to_orcaslicer()
                        if hasattr(orca, "host") and hasattr(orca.host, "ui"):
                            msg_fn = getattr(orca.host.ui, "message", None)
                            if callable(msg_fn):
                                msg_fn(res["message"], title="ACE Pro Sync", icon="info")
                except Exception as e:
                    logging.error("ACE Pro Page message error: %s", e)
    else:
        AceSyncPage = None


    @orca.plugin
    class KlippaceAceSyncPlugin(orca.base):
        """Plugin package entry point."""

        def register_capabilities(self):
            orca.register_capability(AceSyncScript)
            if AceSyncPage is not None:
                orca.register_capability(AceSyncPage)


if __name__ == "__main__":
    # Standalone CLI test mode
    print("Testing KLIPPACE ACE Pro Sync...")
    res = sync_filaments_to_orcaslicer()
    print("Success:", res["success"])
    print(res["message"])
