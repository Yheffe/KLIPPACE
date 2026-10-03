# ACE Pro MMU Dashboard

Web assets and a Moonraker component for the Anycubic ACE Pro. This is the
**KLIPPACE fork**, not the upstream project — see [Provenance](#provenance) for
why that matters before you install anything from here.

## Contents

Two independent pieces live in this directory and they are not interchangeable:

| Path | What it is | Installed by |
| :--- | :--- | :--- |
| `moonraker/ace_status.py` | Moonraker component: the `/server/ace/*` REST API, plus automated MCU build/flash | `installer.sh` (symlinked into `moonraker/moonraker/components/`) |
| `web/ace*.{html,js,css}` | Standalone "ACE Dashboard" page, served at `http://<host>/ace.html` | `acepro-mmu-dashboard/install.sh` |
| `web/klippace-tool-mapper.{js,css}` | Card injected into Fluidd/Mainsail, with the slot editor and tool mapper | `installer.sh` (symlinked into the Fluidd/Mainsail web root) |

### `moonraker/ace_status.py` is not optional

It is the API layer, not a UI. It provides `/server/ace/status`, `/slots`,
`/command`, `/update_mcus`, the `update_all_mcus` remote method that Klipper's
`UPDATE_ALL_MCU` macro calls, and automated MCU compile + flash when a Klipper
update completes.

> [!WARNING]
> **`/server/ace/test_detect` is remote code execution.** Its `cmd` parameter is
> passed to a shell as the Moonraker user with no allow-list, protected only by
> Moonraker's own `trusted_clients` setting (a private-network CIDR list by
> default). It is used as this project's file-deployment mechanism and must not
> be reachable from an untrusted network. Full note in the docstring on
> `handle_test_detect`.

### Why the standalone page still exists

`ace.html` + `ace-dashboard.js` predates the injected card. The card covers slot
status, colours, metadata editing and load/unload, but the standalone page also
has **dryer start/stop, feed assist and manual feed/retract**, so it is not yet
redundant. Those controls are being ported into the card; once they all live
there this page can retire.

## Installing the standalone page

```bash
cd acepro-mmu-dashboard
chmod +x install.sh
./install.sh
```

Answer the prompts to choose which components to install and where, then open
`http://<host>/ace.html`. Adjust `ace-dashboard-config.js` if you need a fixed
API host.

The installer asks for **one** web interface — Fluidd or Mainsail — rather than
asking about each in turn. Almost everyone runs a single dashboard, and linking
into both is a common source of confusion: a path like `~/mainsail` is often
a symlink to `~/fluidd`, and a Mainsail older than **v2.15.0** has no MMU card
for the script to attach to. Choose *Neither* to install the Moonraker component
without touching any web UI.

## Provenance

Vendored from [`ducati1198/acepro-mmu-dashboard`](https://github.com/ducati1198/acepro-mmu-dashboard)
and extended since: the MCU build/flash automation, `cmd` support in
`test_detect`, and the whole `klippace-tool-mapper` card are local additions.

**Do not follow upstream's `git clone` instructions** — you would get upstream
without those additions. Install from this repository instead.

