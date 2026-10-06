# Live test plan — closed-loop slot feed

The change lives on the branch **`feed-closed-loop`**, not on `dev`. `dev` stays
on the last verified commit, so an accidental pull cannot put an untested change to
the busiest path in the system onto the printer.

Merge to `dev` only after this procedure passes. If it fails, delete the branch —
nothing on `dev` needs reverting.

The branch's `fix(ace): stop the slot-to-toolhead feed on the sensor` commit
changed the most-travelled path in the system: every print start and every
toolchange feeds through `_feed_to_toolhead_with_extruder_assist`.

Phase 1 (slot → entry sensor) used to command a fixed length and block until the
ACE finished it, then look at the sensor. It now stops the feed the moment the
sensor trips, matching what Phase 2 already did.

(Referred to by subject rather than hash: rebasing the branch changes the hash, and
a stale one in a procedure is worse than none.)

## What the unit tests do and do not cover

Covered by `tests/test_closed_loop_feed.py` (18 cases, mutation-tested five ways):

- the feed is issued before polling, and stopped on trigger, exactly once
- a timeout also stops the feed
- an unrecognised response code is **not** treated as fatal
- `FORBIDDEN` is retried, up to `MAX_RETRIES`, and is the only code retried
- `wait_ready()` precedes every attempt

Not covered — these need hardware:

- that the ACE honours `stop_feed` promptly mid-feed (the underlying assumption)
- what the firmware actually reports for an interrupted feed
- real timing: how much overshoot occurs between the sensor tripping and the feed
  physically stopping

## Procedure

Run from the printer, with the machine idle and nothing loaded.

### 0. Baseline

```bash
cd /home/pi/KLIPPACE && git rev-parse --short HEAD   # record this
curl -s http://localhost:7125/printer/objects/query?save_variables \
  | python3 -m json.tool | head -20                   # note ace_current_index
```

### 1. Deploy the branch, then restart properly

**Prerequisite — do this first.** The printer's installed `deploy.sh` predates the
`--branch` fix, and the old version *merges* the named branch into whatever is
checked out instead of switching to it. Running `--branch` before updating would
therefore pull this untested change onto `dev` on the printer — the exact thing the
branch exists to prevent.

So bring `dev` up first with an ordinary deploy, which is safe (it only carries the
deploy-script fix):

```bash
./scripts/deploy.sh --restart
grep -c 'would switch to branch' scripts/deploy.sh    # expect 1; 0 means still old
```

Then switch to the branch:

```bash
./scripts/deploy.sh --branch feed-closed-loop --restart
```

`--branch` now means "be on this branch": it fetches first, so a branch that exists
only on origin is found, then checks it out before pulling.

A **service** restart is required, not a config reload — this is Python under
`extras/`, and `POST /printer/restart` does not re-import it.

Confirm the new code is live:

```bash
grep -c '_feed_until_sensor' /home/pi/klipper/klippy/extras/ace/instance.py   # expect 2
```

### 2. First load — watch for the new messages

```bash
_ACE_SYS_EXEC CMD="tail -f /home/pi/printer_data/logs/klippy.log"
```

then from the console, with a spool present in a known slot:

```
ACE_CHANGE_TOOL GATE=0
```

Expect, in order:

```
ACE[0]: Feeding 1200.0mm at 60.0mm/s, stopping on the toolhead entry sensor (timeout 40s)...
ACE[0]: Toolhead entry sensor triggered after N.Ns of feeding - feed stopped
ACE[0]: Entry sensor reached. Building forward pressure ...
ACE[0]: Nozzle sensor triggered after N.Nmm coordinated feed
ACE[0]: Switching from feeding to feed_assist mode
```

**The result to look for**: `triggered after N.Ns` where N is **materially less
than 20s** (1200mm at 60mm/s). If it reports ~20s, the feed ran to completion and
the stop did not take effect — stop testing and report.

### 3. Timing sanity

From the same log, the interval between `Feeding 1200.0mm` and
`entry sensor triggered` is the real feed time. Compare against 20s:

- clearly less → the stop works, and the difference is the overfeed
- ~20s → the stop is not being honoured

Also check nothing else complained:

```bash
grep -iE 'Traceback|Exception|Feed failed' /home/pi/printer_data/logs/klippy.log | tail
```

A single `Feed reported '<msg>'` line is expected and benign (see below).

### 4. Full print start

Slice something small and start it. This exercises the load through
`PRINT_START` → `ACE_ON_PRINT_START`, including the blobifier purge and the new
`StartupToolchangeAbort` path. Confirm the print begins normally.

### 5. Mid-print toolchange

A two-colour test part is the real check: unload T0, load T1 mid-print, resume.

### 6. Rollback if anything looks wrong

Two levels, depending on how far you want to go.

**Return to `dev`** (keeps the branch for another attempt):

```bash
./scripts/deploy.sh --branch dev --restart
```

**Abandon the branch entirely**: delete it locally and on origin. `dev` was never
changed, so nothing needs reverting there.

`extras/ace/` is a symlink into the repo, so switching branches changes the live
Python on disk immediately — only the restart is needed to reload it.

## Reading the result

### One `Feed reported '<msg>'` line is expected

`_poll_feed_until_sensor` deliberately does not treat an unfamiliar code as fatal.
The firmware's reply to an intentionally halted feed is unknown — nothing in this
codebase ever interrupted one before — so it is logged once and the sensor reading
decides. If a genuinely stuck feed is ever reported as `Feed reported ...` followed
by the 60s feed-assist fallback, that is the intended behaviour, not a fault.

### If the sensor never triggers

The flow falls through to the existing 60-second feed-assist window, then raises.
That path is unchanged and is what produced the observed pumpkin-print behaviour.
The message now includes the timeout reason and any code seen, so a real jam is
easier to diagnose than before.

### If the feed overshoots noticeably

The stop is asynchronous: the ACE continues briefly after `stop_feed`. If the
overshoot pushes filament past the entry sensor into the nozzle before Phase 2
starts, Phase 2's coordinated feed would begin from a different point. Watch the
`Nozzle sensor triggered after N.Nmm` value — it is normally ~14mm. A much smaller
number would mean the overshoot already reached the nozzle.

If that happens the fix is to stop the feed slightly *before* the sensor trips, or
to reduce the feed speed near the sensor. Both are easy; neither is worth guessing
at without this measurement.

## If it works

Merge the branch to `dev`, then put the printer back on the mainline:

```bash
# on the laptop
git checkout dev && git merge --ff-only feed-closed-loop && git push origin dev

# on the printer
./scripts/deploy.sh --branch dev --restart
```

Then the retry becomes safe and trivial, because a stopped feed leaves the filament
at a known point — no park needed first. That was the whole reason the retry was
blocked.
