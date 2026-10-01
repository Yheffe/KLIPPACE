# /// script
# name = "KLIPPACE ACE Pro Sync"
# version = "1.1.0"
# description = "One-click filament and color sync from Anycubic ACE Pro via Moonraker"
# ///

"""
KLIPPACE ACE Pro Sync Plugin for OrcaSlicer.

Dynamically retrieves printer network connection parameters (host, port, API key)
directly from the active OrcaSlicer printer profile (or OrcaSlicer configuration),
then queries Moonraker to synchronize ACE Pro filaments, colors, temperatures,
and RFID tags into OrcaSlicer user profiles.
"""

import json
import logging
import os
import platform
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

COLOR_NAMES = {
    "#FF7F32": "Orange",
    "#FF3A2F": "Red",
    "#000000": "Black",
    "#FFFFFF": "White",
    "#0000FF": "Blue",
    "#00FF00": "Green",
    "#FFFF00": "Yellow",
    "#808080": "Gray",
    "#A52A2A": "Brown",
    "#800080": "Purple",
    "#FFC0CB": "Pink",
    "#00FFFF": "Cyan",
}


def get_color_name(hex_code):
    """Return friendly name for common filament hex colors."""
    if not hex_code:
        return ""
    code = hex_code.upper()
    if code in COLOR_NAMES:
        return COLOR_NAMES[code]
    return code


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


def fetch_moonraker_ace_data(net_info=None):
    """Fetch ACE Pro and lane_data objects from Moonraker API."""
    info = net_info or resolve_printer_network_info()
    base_url = info["base_url"]
    headers = {"User-Agent": "OrcaSlicer-KlippaceSync"}
    if info.get("apikey"):
        headers["X-Api-Key"] = info["apikey"]

    results = {
        "slots": [],
        "raw_mmu": {},
        "raw_ace": {},
        "host": info["host"],
        "base_url": base_url,
        "printer_name": info["printer_name"],
    }

    # 1. Fetch lane_data from Moonraker database
    lane_data = {}
    try:
        url = f"{base_url}/server/database/item?namespace=lane_data"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            lane_data = data.get("result", {}).get("value", {})
    except Exception as e:
        logging.warning("Failed to fetch lane_data from %s: %s", base_url, e)

    # 2. Fetch printer objects (mmu, ace_instance_0)
    printer_objects = {}
    try:
        url = f"{base_url}/printer/objects/query?mmu&mmu_machine&ace_instance_0"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            printer_objects = data.get("result", {}).get("status", {})
    except Exception as e:
        logging.warning("Failed to fetch printer objects from %s: %s", base_url, e)

    results["raw_mmu"] = printer_objects.get("mmu", {})
    results["raw_ace"] = printer_objects.get("ace_instance_0", {})

    # Extract 4 slots
    ace_slots = results["raw_ace"].get("slots", [])
    mmu_colors = results["raw_mmu"].get("gate_color", ["", "", "", ""])
    mmu_materials = results["raw_mmu"].get("gate_material", ["", "", "", ""])
    mmu_status = results["raw_mmu"].get("gate_status", [0, 0, 0, 0])

    for i in range(4):
        slot_data = {
            "index": i,
            "tool": i,
            "status": "empty",
            "material": "PLA",
            "color": "#FFFFFF",
            "color_name": "",
            "temp": 210,
            "bed_temp": 60,
            "vendor": "Anycubic",
            "sku": "",
            "rfid": False,
        }

        # Priority 1: ace_instance_0 data
        if i < len(ace_slots):
            raw_s = ace_slots[i]
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

        # Fallback to MMU shim gate attributes if present
        if i < len(mmu_colors) and mmu_colors[i]:
            if slot_data["color"] in ("#FFFFFF", "#000000") and mmu_colors[i].startswith("#"):
                slot_data["color"] = mmu_colors[i].upper()
        if i < len(mmu_materials) and mmu_materials[i] and mmu_materials[i] != "Unknown":
            slot_data["material"] = mmu_materials[i]
        if i < len(mmu_status) and mmu_status[i] == 1:
            slot_data["status"] = "ready"

        # Default fallback for unconfigured non-RFID slots
        if not slot_data["material"] or slot_data["material"].upper() in ("UNKNOWN", "???", "NONE", "N/A"):
            slot_data["material"] = "PLA"
        if slot_data["temp"] <= 0:
            slot_data["temp"] = 210
        if slot_data["bed_temp"] <= 0:
            slot_data["bed_temp"] = 60

        slot_data["color_name"] = get_color_name(slot_data["color"])
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
    builds universal filament presets for ready slots, and writes to OrcaSlicer user profiles.
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

    synced_items = []
    for s in slots:
        if s["status"] != "ready":
            continue

        slot_idx = s["index"]
        mat = s.get("material") or "PLA"
        if not mat or mat.upper() in ("UNKNOWN", "???", "NONE", "N/A"):
            mat = "PLA"

        col = s.get("color") or "#000000"
        col_name = s.get("color_name") or get_color_name(col) or col
        temp = s.get("temp", 0)
        if not temp or temp <= 0:
            temp = 210
        bed_temp = s.get("bed_temp", 0)
        if not bed_temp or bed_temp <= 0:
            bed_temp = 60

        vendor = s.get("vendor") or "Anycubic"
        sku = s.get("sku", "")

        preset_name = f"ACE T{slot_idx} - {mat} {col_name}".strip()
        inherits_map = {
            "PLA": "Generic PLA @System",
            "PETG": "Generic PETG @System",
            "ABS": "Generic ABS @System",
            "ASA": "Generic ASA @System",
            "TPU": "Generic TPU @System",
        }
        inherits_name = inherits_map.get(mat.upper(), "Generic PLA @System")

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

        # Write to all discovered user directories
        for fdir in filament_dirs:
            out_path = os.path.join(fdir, f"{preset_name}.json")
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(preset_payload, f, indent=4)
            except Exception as e:
                logging.error("Failed writing preset %s: %s", out_path, e)

        synced_items.append({
            "slot": slot_idx,
            "name": preset_name,
            "material": mat,
            "color": col,
            "temp": temp,
            "sku": sku,
        })

    printer_label = f"{net_info['printer_name']} ({net_info['base_url']})"
    msg_lines = [f"Synced {len(synced_items)} slots from ACE Pro on {printer_label}:"]
    for it in synced_items:
        sku_str = f" [{it['sku']}]" if it["sku"] else ""
        msg_lines.append(f"• T{it['slot']}: {it['material']} ({it['color']}) @ {it['temp']}°C{sku_str}")

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
