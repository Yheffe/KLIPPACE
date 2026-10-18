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

## Live result so far — 2026-10-18

**Phase 1 verified working.** With the machine idle, `tool=-1` and filament in the
bowden, `ACE_CHANGE_TOOL GATE=0` produced:

```
ACE[0]: Feeding 1200.0mm at 60.0mm/s, stopping on the toolhead entry sensor (timeout 40s)...
ACE[0]: Stop feed successful: {'code': 0, 'msg': 'success'}
ACE[0]: Toolhead entry sensor triggered after 19.5s of feeding - feed stopped
```

Stopped by the **sensor at 19.5s**, not by the 40s timeout, so the loop really is
watching during the feed rather than checking afterwards. This is the claim the
whole branch rests on, and it holds.

### Phase 2 needed a real fix — found by the new diagnostics

The first live run failed at Phase 2's cap. The diagnostic line added in
`6309364` then said exactly what was wrong:

```
ACE[0]: Phase 2 diagnostics - ACE link connected, feed assist index -1,
        extruder moved 80.0mm at 8.0mm/s
```

The link was **connected**, so it was not a hardware dropout and not the cap. The
cause is a design assumption this branch invalidated:

- Old Phase 1 left the ACE feeding, so Phase 2 called `_change_feed_speed()` to
  **slow down a running feed**.
- New Phase 1 **stops** the feed on the entry sensor. There is no running feed for
  a speed change to act on.
- The ACE still answers `code: 0` to an update on a feed that is not running, so
  the old `Change feed speed not confirmed` fallback never fired. Nothing pushed,
  and the extruder dragged 80mm of filament without moving it.

Phase 2 now **starts its own bounded feed** (`max_entry_to_nozzle_length + 50` at
`ace_entry_feeding_speed`), which runs concurrently with the extruder loop and is
stopped on either exit — success or the cap. Four tests pin this, and reverting to
the speed-change call fails two of them.

This also explains why `max_entry_to_nozzle_length` looked too small: with nothing
pushing, no distance would have been enough.

### Mid-print toolchange — observed 2026-10-18

The first real colour change (T0 → T1, mid-print at 17% of a 44-minute job)
completed correctly:

```
ACE: Retracting T0 (25.000mm at 15.000mm/s)
ACE[0]: Retraction completed in 26.31s (sensor: 2.01s, 9.4% of expected, 117 polls)
ACE[0]: ✓ Toolhead sensor clear
ACE[0]: Tool 0 unloaded successfully
ACE[0]: Feeding 1200.0mm at 60.0mm/s, stopping on the toolhead entry sensor (timeout 40s)...
ACE[0]: Nozzle sensor triggered after 18.0mm coordinated feed
ACE: Applying purge multiplier 1.00 to purge length 106.02mm, final purge length: 106.02mm
ACE: Post-toolchange sequence completed
ACE: perform_tool_change result status: Tool 0 → 1 (ACE[0])
```

But Phase 1 **timed out** on the T1 load:

```
ACE[0]: Toolhead entry sensor not triggered after feed (40.0s, reason=timeout)
ACE[0]: Toolhead entry sensor finally triggered after running feed-assist for 60s
```

This is the pre-existing slipping signature described below — the ACE ran the
commanded 1200mm without the filament travelling it — and the 60s feed-assist
fallback recovered it, exactly as designed. The toolchange still succeeded.

**What it exposed:** 1200mm at 60mm/s is 20s of travel with a 40s timeout, so once
the ACE reports the feed complete and the sensor still has not tripped, the
remaining 20s is dead time — the feed is over and waiting cannot help. The loop now
notices a `code: 0` completion response, logs that the filament is probably not
moving, waits `FEED_COMPLETE_GRACE_S` (1s) for the switch to settle, and hands over
to feed-assist. Three tests cover it, including one that a late sensor trip inside
the grace period still counts.

### The over-feed figure in this file is probably too high

This plan says Phase 1 over-fed by about 150mm (1200 commanded against a 1050
configured distance). The live run suggests otherwise: 19.5s at 60mm/s is about
**1170mm** of actual travel, which against a 1050mm route implies roughly 30mm of
over-feed, not 150mm.

Caveat: the test started from `filament_pos='bowden'`, not from the park position,
so this is not a clean measurement. Re-measure from a known park position before
quoting a number. It does not change the value of the change — stopping at the
sensor is still what leaves the filament at a known point — but the benefit is
smaller than the plan implies, and the plan should not claim a figure it has not
measured.

## What the unit tests do and do not cover

Covered by `tests/test_closed_loop_feed.py` (27 cases, mutation-tested four
ways):

- the feed is issued before polling, and stopped on trigger, exactly once
- a timeout also stops the feed
- an unrecognised response code is **not** treated as fatal
- `FORBIDDEN` is retried, up to `MAX_RETRIES`, and is the only code retried
- `wait_ready()` precedes every attempt
- the sensor is sampled often enough to keep overshoot small (see below)

The mutations actually run, and what they produced:

| mutation | result |
|---|---|
| never stop on the sensor | 7 failures |
| feed an already-satisfied sensor | 7 failures |
| treat `FORBIDDEN` as fatal | 4 failures |
| never time out | **used to hang the suite** |

The last one is worth knowing about. With a simulated clock, deleting the timeout
branch is an infinite loop, so the run never terminated — a broken timeout would
have hung CI rather than reported. The harness now raises once the simulated
clock passes `MAX_SIMULATED_SECONDS`, which turns that mutant into two failures
in 0.13s.

### Sensor sampling is part of the overshoot budget

The loop only reads the sensor once per poll, so filament keeps moving for up to
one interval after the switch closes. `FEED_SENSOR_POLL_INTERVAL_S` in
`extras/ace/config.py` is therefore a tuning decision, not an incidental
literal: at 60mm/s the shipped **0.02s is 1.2mm** of overshoot, while the 0.1s
this loop used to use was **6.0mm**. The read is free — `filament_present` is
pushed from the endstop callback, not queried over serial — so a tighter
interval costs only reactor wake-ups. A test asserts the budget directly, because
a self-referential "detected within N intervals" check passes at any interval.

Note that both sensors here are plain `filament_switch_sensor`, so
`get_switch_state` is already instantaneous — there is no `absence_timeout`
debounce to bypass, and `get_instant_switch_state` would behave identically.

Not covered — these need hardware:

- that the ACE honours `stop_feed` promptly mid-feed (the underlying assumption)
- what the firmware actually reports for an interrupted feed
- real timing: how much overshoot occurs between the sensor tripping and the feed
  physically stopping. The unit tests bound only our own share of it (one poll
  interval); the ACE's stop latency has to be measured on the machine.

## Procedure

Run from the printer, with the machine idle and nothing loaded.

### 0. Baseline

```bash
cd /home/pi/KLIPPACE && git rev-parse --short HEAD   # record this
curl -s http://localhost:7125/printer/objects/query?save_variables \
  | python3 -m json.tool | head -20                   # note ace_current_index
```

### 1. Deploy the branch, then restart properly

**Prerequisite — check this first.** The `--branch` fix has to be in the
installed `deploy.sh` before `--branch` is used, because the old version
*merges* the named branch into whatever is checked out instead of switching to
it, and would therefore pull this untested change onto `dev` on the printer —
the exact thing the branch exists to prevent.

A printer already tracking `dev` satisfies this. Confirm rather than assume; if
the check reports 0, bring `dev` up first with an ordinary deploy, which is safe
(it only carries the deploy-script fix):

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

### The Phase 2 interaction — read this before testing

Phase 1 and Phase 2 share one function and now behave differently from before, so
this is the part most likely to surprise.

**What the old flow actually did.** Phase 1 commanded **1200mm** for a route whose
sensor sits at **1050mm** (`parkposition_to_toolhead_length`), so it over-fed by
about 150mm *before* looking at anything. Evidence from the logs:

| event | count |
|---|---|
| Phase 2 reached (`Entry sensor reached. Building forward pressure`) | 9 |
| `Change feed speed not confirmed, restarting feed` | 0 |
| `failed to reach nozzle sensor after Nmm` (Phase 2's cap) | 0 |
| nozzle sensor reached at | 14mm ×6, 16mm, 18mm, **0.0mm** |

The `0.0mm` is the giveaway: on that run the nozzle sensor was **already**
triggered when Phase 2 began. Phase 2 was not doing the real work — the over-feed
had already pushed filament most of the way, and Phase 2 only nudged it the last
14–18mm.

**Consequence for this change.** Phase 1 now stops at the entry sensor, so the
filament starts Phase 2 *earlier* than before, and Phase 2 has more to do. Its work
is bounded by `max_entry_to_nozzle_length` (**80** on this machine), a limit that
was never exercised because over-feed had already covered the distance.

### If Phase 2 fails, read the diagnostics before changing anything

An earlier version of this file said the cap was too small and to raise it to 150.
**The first live test does not support that, and the advice is withdrawn.**

The cap fired on 2026-10-18:

```
ACE[0]: Entry sensor reached. Building forward pressure (ACE: 16.0mm/s, Extruder: 8.0mm/s)...
ACE[0]: Requesting feed speed change to 16.0mm/s (slot 0)
ACE[0]: Filament failed to reach nozzle sensor after 80.0mm (safety limit: 80.0mm)
```

There was no `Change feed speed not confirmed`, so the ACE accepted the speed
change — and Phase 2 had only ever reported **14–18mm** before this change. If the
real entry-to-nozzle distance were above 80mm, those historical runs could not have
completed. So the cap is almost certainly *ample*, and something stopped the
filament from advancing — most plausibly the ACE dropping off USB mid-move (145
re-enumerations were recorded in one burst on that date).

The failure path now logs which it was:

```
ACE[0]: Phase 2 diagnostics - ACE link DISCONNECTED, feed assist index -1,
        extruder moved 80.0mm at 8.0mm/s
```

Read that line first:

| diagnostic | meaning |
|---|---|
| `ACE link DISCONNECTED` | The ACE was not pushing. The extruder was dragging filament that nothing was feeding, so the gears slipped. **Not** a cap problem — fix the link. |
| `ACE link connected` | The ACE was pushing and the filament still did not arrive. Now the cap, a blockage, or a slipping extruder are all live. |

Only raise `max_entry_to_nozzle_length` when the link was **connected**. And note
that the setting is not purely a safety limit: `mmu_shim._extruder_only_length()`
also uses it as the real travel distance for Happy Hare `EXTRUDER_ONLY` moves, so
raising it makes those moves longer too. Measure the real distance before changing
it.

### What this change does and does not fix — correcting an earlier claim

An earlier draft of this file said the over-feed was "a plausible cause of the
recurring feed failures". **The logs do not support that, and the claim is
withdrawn.** All three failures share one signature:

```
feed_filament_with_wait_for_response() completed -> length=1200.0mm, result_code=0
Feed timeout for 1200.0mm after 40.0 seconds
Toolhead entry sensor not triggered after feed
```

The ACE reported the full 1200mm fed, **yet a sensor only 1050mm away never
triggered**. Had the filament actually moved 1200mm it would have passed the sensor
long before. So in those failures the filament barely moved at all: the ACE's feed
rollers were slipping or not gripping, most likely a mis-seated spool or filament
stuck on the reel.

**This change does not address that.** Expect those failures to continue if the
cause recurs. What the change does fix:

- genuine over-feed (~150mm) when the filament *is* gripped — it now stops at the
  sensor instead of running past it
- the unknown filament position left behind by any failed feed, which is what made
  a retry unsafe
- one specific pointless motion: refusing to feed at all when the sensor is
  already satisfied

So judge the change on *how far a successful load over-feeds* (the feed should
stop at the sensor), not on the disappearance of jam-shaped failures.

### If it does go wrong

Two ways to know, both in the log:

1. `Filament failed to reach nozzle sensor after 80.0mm` — Phase 2's cap. Not a
   jam; raise `max_entry_to_nozzle_length` in `[ace]`. See above.
2. A load that took about the full timeout and still did not trigger the sensor —
   the old slipping behaviour, unchanged by this work.

If loads become *less* reliable rather than more, revert: the change is meant to be
strictly a reduction in movement, so extra failures mean the reasoning is wrong.


## If the sensor never triggers

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
