#!/usr/bin/env bash
# ============================================================================
# KLIPPACE - Deploy repo changes to this printer
#
# WHY THIS EXISTS
#   On this machine the live config files split into two kinds:
#
#     symlinked  - ace_voron24_macros.cfg is a symlink into the repo, so a
#                  `git pull` alone deploys it.
#     copied     - printer.cfg, blobifier.cfg, ace_voron24*.cfg and friends are
#                  PLAIN COPIES. A `git pull` does NOT update them. Editing the
#                  repo and forgetting the copy leaves the printer running old
#                  config while the repo looks fixed - which wastes hours
#                  debugging something already solved.
#
#   This script pulls, syncs the copies, and tells you which restart is needed.
#
# USAGE (runs on the printer)
#   ./scripts/deploy.sh                 # pull + sync, report restart needed
#   ./scripts/deploy.sh --dry-run       # show what would change, touch nothing
#   ./scripts/deploy.sh --restart       # ...then perform the restart
#   ./scripts/deploy.sh --branch main   # deploy a different branch
#
# USAGE (from your laptop, over SSH)
#   ssh pi@192.168.1.168 'cd /home/pi/KLIPPACE && ./scripts/deploy.sh --restart'
#
# From the Mainsail/Fluidd console (uses the existing _ACE_SYS_EXEC macro):
#   _ACE_SYS_EXEC CMD="bash /home/pi/KLIPPACE/scripts/deploy.sh --dry-run"
#
# EXIT CODES
#   0  up to date / synced successfully
#   1  usage or environment error
#   2  pull failed (dirty tree, or diverged branch)
#   3  restart was needed but not performed
# ============================================================================

set -euo pipefail

REPO_DIR="${KLIPPACE_REPO_DIR:-/home/pi/KLIPPACE}"
LIVE_DIR="${KLIPPACE_LIVE_DIR:-/home/pi/printer_data/config}"
BACKUP_ROOT="${LIVE_DIR}/.klippace-backups"
BRANCH="dev"
DO_PULL=1
DO_RESTART=0
DRY_RUN=0
FORCE=0
MOONRAKER="http://localhost:7125"

# ---------------------------------------------------------------------------
# File maps, as "live-name|repo-path" pairs.
#
# Deliberately not bash associative arrays: macOS ships bash 3.2, where
# `declare -A` silently degrades into an indexed array and then dies on
# arithmetic errors. This form works on bash 3.2 and 5.x alike.
#
# SYNC_FILES are plain copies: keep the live file in step with the repo.
# PROTECTED_FILES are machine-specific: report drift, never overwrite.
# ---------------------------------------------------------------------------
SYNC_FILES="
printer.cfg|VORON/printer.cfg
sensorless_homing.cfg|VORON/sensorless_homing.cfg
ace_voron24.cfg|config/voron24/ace_voron24.cfg
ace_voron24_hardware.cfg|config/voron24/ace_voron24_hardware.cfg
ace_voron24_setting.cfg|config/voron24/ace_voron24_setting.cfg
ace_voron24_vars.cfg|config/voron24/ace_voron24_vars.cfg
blobifier.cfg|config/voron24/blobifier.cfg
blobifier_hw.cfg|config/voron24/blobifier_hw.cfg
led_control.cfg|config/voron24/led_control.cfg
"

# Symlinks that should point into the repo. Recreated if wrong or missing.
LINK_FILES="
ace_voron24_macros.cfg|config/voron24/ace_voron24_macros.cfg
"

# Machine-specific. These carry tuned values measured on THIS printer and are
# deliberately not in the repo as the live version. Overwriting them degrades
# print quality:
#   ebb36_gen2.cfg    live has a tuned `pressure_advance` the repo does not.
# Report drift so it is visible, but never clobber.
PROTECTED_FILES=(
  ebb36_gen2.cfg
)

# Owned by other tools; we only report drift.
UNMANAGED_FILES=(
  moonraker.conf
  crowsnest.conf
)

# Runtime state (saved_variables.cfg and friends) is never touched: the sync list
# above is a whitelist, so anything not named there is left alone by design.

# ---------------------------------------------------------------------------
# Output helpers.  Plain text, no colour: this is read over SSH and through
# Moonraker's console, where escape codes are noise.
# ---------------------------------------------------------------------------
say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; }
chg()  { printf '   sync  %s\n' "$*"; }
warn() { printf '   warn  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }

usage() {
  # Print the header comment block, whatever its length.
  awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)   DRY_RUN=1 ;;
    --restart)   DO_RESTART=1 ;;
    --force)     FORCE=1 ;;
    --no-pull)   DO_PULL=0 ;;
    --branch)    BRANCH="${2:-}"; [ -n "$BRANCH" ] || { bad "--branch needs a value"; exit 1; }; shift ;;
    -h|--help)   usage ;;
    *)           bad "unknown option: $1"; usage ;;
  esac
  shift
done

[ "$DO_RESTART" -eq 1 ] && [ "$DRY_RUN" -eq 1 ] && {
  bad "--restart and --dry-run are mutually exclusive"
  exit 1
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
step "Preflight"
[ -d "${REPO_DIR}/.git" ]  || { bad "not a git repo: ${REPO_DIR}"; exit 1; }
[ -d "${LIVE_DIR}" ]       || { bad "live config dir missing: ${LIVE_DIR}"; exit 1; }
command -v git >/dev/null   || { bad "git not found"; exit 1; }
ok "repo   ${REPO_DIR}"
ok "live   ${LIVE_DIR}"
[ "$DRY_RUN" -eq 1 ] && say "   MODE  DRY RUN - nothing will be modified"

cd "${REPO_DIR}"

# Files we manage must be clean, or a pull could clobber local work.
DIRTY=""
if [ -n "$(git status --porcelain)" ]; then
  # Ignore untracked files outside our managed paths; only care about tracked edits.
  DIRTY="$(git status --porcelain --untracked-files=no)"
fi
if [ -n "${DIRTY}" ]; then
  warn "working tree has local modifications:"
  printf '%s\n' "${DIRTY}" | sed 's/^/         /'
  if [ "$DRY_RUN" -eq 0 ] && [ "$DO_PULL" -eq 1 ]; then
    bad "refusing to pull with a dirty tree. Commit, stash, or:"
    say "         git -C ${REPO_DIR} checkout -- <file>"
    exit 2
  fi
else
  ok "working tree clean"
fi

# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------
BEFORE="$(git rev-parse HEAD)"
AFTER="${BEFORE}"

if [ "$DO_PULL" -eq 1 ]; then
  step "Pull origin/${BRANCH}"
  if [ "$DRY_RUN" -eq 1 ]; then
    skip "would run: git pull --ff-only origin ${BRANCH}"
  else
    if ! git pull --ff-only origin "${BRANCH}" 2>&1 | sed 's/^/   /'; then
      bad "pull failed - the local branch has diverged, or the remote is unreachable"
      say "         resolve manually; this script will not force anything"
      exit 2
    fi
    AFTER="$(git rev-parse HEAD)"
  fi
else
  step "Pull"
  skip "skipped (--no-pull)"
fi

say ""
if [ "${BEFORE}" = "${AFTER}" ]; then
  ok "already at $(git rev-parse --short HEAD) - no new commits"
else
  ok "$(git rev-parse --short "${BEFORE}") -> $(git rev-parse --short "${AFTER}")"
  git --no-pager log --oneline "${BEFORE}..${AFTER}" | sed 's/^/         /'
fi

CHANGED="$(git diff --name-only "${BEFORE}" "${AFTER}" 2>/dev/null || true)"

# ---------------------------------------------------------------------------
# Which restart does this need?
#
# RESTART vs a plain config reload, which is easy to get wrong:
#   POST /printer/restart        re-reads config in-process. Python is NOT
#                                re-imported, so extras/ace/*.py changes are
#                                silently ignored.
#   service restart              real restart, re-imports Python.
# ---------------------------------------------------------------------------
NEEDS_SERVICE=0   # python under extras/
NEEDS_CONFIG=0    # printer config files

if printf '%s\n' "${CHANGED}" | grep -qE '^extras/'; then
  NEEDS_SERVICE=1
fi
if printf '%s\n' "${CHANGED}" | grep -qE '^(config/voron24/|VORON/).*\.cfg$'; then
  NEEDS_CONFIG=1
fi

# ---------------------------------------------------------------------------
# Sync copies
# ---------------------------------------------------------------------------
step "Config files"
BACKUP_DIR=""
if [ "$DRY_RUN" -eq 0 ]; then
  BACKUP_DIR="${BACKUP_ROOT}/$(date +%Y%m%d-%H%M%S)"
fi
SYNCED=0
UNCHANGED=0

while IFS='|' read -r live_name repo_rel; do
  [ -n "${live_name}" ] || continue
  live_path="${LIVE_DIR}/${live_name}"
  repo_path="${REPO_DIR}/${repo_rel}"

  if [ ! -f "${repo_path}" ]; then
    warn "${live_name}: repo source missing (${repo_rel}) - skipped"
    continue
  fi
  if [ ! -e "${live_path}" ]; then
    chg "${live_name}: not present on this printer - would create from ${repo_rel}"
    if [ "$DRY_RUN" -eq 0 ]; then
      mkdir -p "${BACKUP_DIR}"
      cp -a "${repo_path}" "${live_path}"
    fi
    SYNCED=$((SYNCED + 1))
    continue
  fi
  if cmp -s "${live_path}" "${repo_path}"; then
    UNCHANGED=$((UNCHANGED + 1))
    continue
  fi

  # Differ. Show how much, so a one-line drift is obvious.
  nlines="$(diff "${live_path}" "${repo_path}" 2>/dev/null | grep -c '^[<>]' || true)"
  chg "${live_name}: ${nlines} line(s) differ from ${repo_rel}"
  if [ "$DRY_RUN" -eq 1 ]; then
    diff -u "${live_path}" "${repo_path}" | sed -n '1,40p' | sed 's/^/         /' || true
    say "         ... (truncated to 40 lines)"
  else
    mkdir -p "${BACKUP_DIR}"
    cp -a "${live_path}" "${BACKUP_DIR}/${live_name}"
    cp -f "${repo_path}" "${live_path}"
    ok "${live_name}: updated (backup in $(basename "${BACKUP_DIR}"))"
  fi
  SYNCED=$((SYNCED + 1))
done <<< "${SYNC_FILES}"

[ "${UNCHANGED}" -gt 0 ] && ok "${UNCHANGED} file(s) already in step"

# ---------------------------------------------------------------------------
# Symlinks (self-heal if wrong or missing)
#
# Compares the raw link target rather than using `readlink -f`, which does not
# exist on macOS. Targets we create are absolute, so a literal compare is exact.
# ---------------------------------------------------------------------------
while IFS='|' read -r live_name repo_rel; do
  [ -n "${live_name}" ] || continue
  live_path="${LIVE_DIR}/${live_name}"
  want="${REPO_DIR}/${repo_rel}"
  if [ -L "${live_path}" ] && [ "$(readlink "${live_path}")" = "${want}" ]; then
    continue
  fi
  chg "${live_name}: symlink -> ${repo_rel}"
  if [ "$DRY_RUN" -eq 0 ]; then
    # A regular file in the way holds whatever was there before; keep it.
    if [ -e "${live_path}" ] && [ ! -L "${live_path}" ]; then
      mkdir -p "${BACKUP_DIR}"
      cp -a "${live_path}" "${BACKUP_DIR}/${live_name}.pre-symlink"
      say "         saved old regular file as ${live_name}.pre-symlink"
    fi
    ln -sfn "${want}" "${live_path}"
  fi
done <<< "${LINK_FILES}"

# ---------------------------------------------------------------------------
# Protected files: report drift, never overwrite
# ---------------------------------------------------------------------------
for name in "${PROTECTED_FILES[@]}"; do
  live_path="${LIVE_DIR}/${name}"
  [ -e "${live_path}" ] || continue
  repo_rel=""
  for cand in "VORON/${name}" "config/voron24/${name}"; do
    [ -f "${REPO_DIR}/${cand}" ] && { repo_rel="${cand}"; break; }
  done
  [ -n "${repo_rel}" ] || continue
  if cmp -s "${live_path}" "${REPO_DIR}/${repo_rel}"; then
    ok "${name}: matches repo"
  else
    warn "${name} is MACHINE-SPECIFIC and differs from ${repo_rel}:"
    diff -u "${REPO_DIR}/${repo_rel}" "${live_path}" 2>/dev/null \
      | grep -E '^[+-][^+-]' | sed 's/^/         /' || true
    say "         left alone on purpose - this holds tuned values for this printer."
    say "         If the repo needs to carry that value, port it by hand."
  fi
done

# ---------------------------------------------------------------------------
# Unmanaged files: report only
# ---------------------------------------------------------------------------
for name in "${UNMANAGED_FILES[@]}"; do
  live_path="${LIVE_DIR}/${name}"
  repo_path="${REPO_DIR}/config/voron24/${name}"
  [ -f "${live_path}" ] && [ -f "${repo_path}" ] || continue
  if ! cmp -s "${live_path}" "${repo_path}"; then
    warn "${name} differs from config/voron24/${name} (not managed by this script)"
  fi
done

# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------
step "Restart"

if [ "${NEEDS_SERVICE}" -eq 0 ] && [ "${NEEDS_CONFIG}" -eq 0 ]; then
  if [ "${SYNCED}" -gt 0 ]; then
    # Files changed on disk even though git saw no matching diff (e.g. a
    # previous deploy was interrupted). A config reload covers those.
    NEEDS_CONFIG=1
  fi
fi

if [ "${NEEDS_SERVICE}" -eq 0 ] && [ "${NEEDS_CONFIG}" -eq 0 ]; then
  ok "no restart needed"
  say ""
  ok "up to date"
  exit 0
fi

if [ "${NEEDS_SERVICE}" -eq 1 ]; then
  kind="service"
  why="Python under extras/ changed - a plain config reload would NOT re-import it"
else
  kind="config"
  why="printer config changed"
fi
say "   need    ${kind} restart (${why})"

# Never interrupt a print without an explicit override.
if [ "$DO_RESTART" -eq 1 ]; then
  PSTATE="$(curl -fsS "${MOONRAKER}/printer/objects/query?print_stats" 2>/dev/null \
            | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["status"]["print_stats"]["state"])' 2>/dev/null \
            || echo unknown)"
  if [ "${PSTATE}" = "printing" ] || [ "${PSTATE}" = "paused" ]; then
    if [ "${FORCE}" -eq 1 ]; then
      warn "print is '${PSTATE}' - restarting anyway because --force"
    else
      bad "print is '${PSTATE}'. Refusing to restart."
      say "         re-run with --force if you really mean it"
      exit 3
    fi
  fi
fi

restart_cmd() {
  if [ "${kind}" = "service" ]; then
    curl -fsS -X POST "${MOONRAKER}/machine/services/restart?service=klipper" >/dev/null
  else
    curl -fsS -X POST "${MOONRAKER}/printer/restart" >/dev/null
  fi
}

if [ "$DRY_RUN" -eq 1 ]; then
  skip "would request a ${kind} restart"
  say ""
  warn "dry run: config changed but not applied"
  exit 3
fi

if [ "$DO_RESTART" -eq 0 ]; then
  if [ "${kind}" = "service" ]; then
    say "         run: curl -X POST ${MOONRAKER}/machine/services/restart?service=klipper"
  else
    say "         run: curl -X POST ${MOONRAKER}/printer/restart"
  fi
  say "         or re-run with --restart"
  exit 3
fi

say "   ->      requesting ${kind} restart"
if ! restart_cmd; then
  bad "restart request failed - is Moonraker reachable at ${MOONRAKER}?"
  exit 3
fi

# ---------------------------------------------------------------------------
# Verify it actually came back clean
# ---------------------------------------------------------------------------
say "   ...     waiting for Klipper"
for _ in $(seq 1 45); do
  ST="$(curl -fsS "${MOONRAKER}/printer/info" 2>/dev/null \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"].get("state",""))' 2>/dev/null || true)"
  [ "${ST}" = "ready" ] && break
  sleep 2
done

if [ "${ST:-}" != "ready" ]; then
  bad "Klipper did not report 'ready' within ~90s"
  say "         check: /home/pi/printer_data/logs/klippy.log"
  exit 3
fi
ok "Klipper ready"

# The restart itself can succeed while the config fails to load. Say so.
LOG="${HOME}/printer_data/logs/klippy.log"
if [ -f "${LOG}" ]; then
  RECENT="$(tail -500 "${LOG}" | grep -iE 'config error|unable to parse|error loading template|UndefinedError' || true)"
  if [ -n "${RECENT}" ]; then
    bad "config problems in the log:"
    printf '%s\n' "${RECENT}" | head -10 | sed 's/^/         /'
    exit 3
  fi
  ok "no config errors in the log"
fi

say ""
ok "deployed $(git rev-parse --short HEAD) - ${kind} restart complete"
[ -n "${BACKUP_DIR}" ] && [ -d "${BACKUP_DIR}" ] && \
  say "   backups: ${BACKUP_DIR}"
say "   prune old backups: rm -rf ${BACKUP_ROOT}/*"
