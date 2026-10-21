# Phase 3.7: reliability and final validation

**Hardware acceptance is pending.** Implementation/tests opened no camera and sent
no Windows input. No gesture, model, desktop action, dependency or thread was added.
Hardware acceptance remains a separate local testing step.

## Targeted follow-up: Left-hand pinch rearming

At clean commit `28383bc`, the baseline was 473 tests. Opt-in
`--control-gesture-rearm` now permits a stable Left OPEN/STARTED/HELD/RELEASED
sequence after routine Right tracking loss, with a default 800 ms hold and
300 ms stable two-hand association interval. Initial manual A remains mandatory.
Manual/emergency/watchdog/invariant/fault stops cannot be gesture-rearmed. The
controller rechecks generation/health through the existing arming path, skips all
input on completion, resets anchors and requires a fresh Right open/start for clicks.

[Rearming architecture, identity limitations, exact commands and acceptance plan](controls/REARMING.md)
document this focused addition. Existing recognition/mapping thresholds, safety
thread and Ctrl+Shift+F10 option are unchanged. No Phase 3.8 identity tracker or new
Windows action was added. All 531 tests pass (58 added); no physical acceptance
is claimed. The isolated prepared-input validator timing was mean 0.0222 ms,
P95 0.0258 ms, excluding inference, controller/backend work and OS delivery.

## Targeted follow-up: configurable emergency shortcut

The default remains Ctrl+Alt+Esc. The owner selected **Ctrl+Shift+F10** as the
alternative for Chrome Remote Desktop. Use
`--control-emergency-hotkey ctrl+shift+f10`; Ctrl+Shift+F9 and Ctrl+Shift+F11 are
also allowlisted. F12 is excluded under Microsoft's debugger reservation.
Case and modifier order normalize. No recognition, mapping or action behavior
was changed.

The selected value flows through immutable configuration, existing safety-thread
registration, preview status, startup logs and JSON reports. Registration failures
include the actual Windows error code, with conflict-specific guidance only for
1409, and still prevent live startup without fallback. Shutdown and partial startup
failures unregister on the owning thread. Existing cancellation latches, watchdog,
button-release recovery and default-disarmed behavior remain in place.

Follow [the exact simulation/live commands and receiving-computer verification
procedure](controls/README.md#configurable-global-emergency-shortcut-phase-37-safety-fix).
Successful registration does not establish delivery through remote software.
No actual registration, webcam or Windows input test was run for this follow-up.
The pre-change baseline was 445 passing tests; follow-up validation is recorded
below separately from the original milestone. Do not interpret prior acceptance
commands' default shortcut as a claim it is available in the owner's remote session.

Follow-up validation: **473 tests passed** (camera 16, gestures 154, hand_tracking
153, controls 150), up from 445. The 28 added tests cover parsing/rejections,
Win32 flags/error reporting, owner-thread registration cleanup, startup failure
and timeout, virtual held-button release, pending-action cancellation, in-flight
arming, watchdog/runtime failure, simulation isolation, preview/report values and
Q/H integration. All existing tests were retained. Syntax compilation, dependency
consistency and diff whitespace checks passed. No new dependency was added.

## Initial audit and scope

Git was clean at `8bad723` (the targeted POINTING follow-up). The measured baseline
was **410 passing tests**: camera 16, gestures 144, hand_tracking 137, controls 113.
Absolute mapping and mapping-specific inversion defaults were already implemented.
No prior changes were mixed into this milestone.

The inspected architecture remains MSMF BGR capture → optional inference resize/RGB
conversion → one synchronous MediaPipe call → landmark EMA → shared immutable
features → static/pinch/swipe/state arbitration → selected-hand action mapper →
simulation/Win32 backend → reused preview buffer → native Win32 pollKey. Recognition
imports no OS input. Feature extraction is already shared once per hand/frame.

| Finding | Evidence and response |
| --- | --- |
| Relative precision defect | 100 movements of .00005 normalized units produced zero output despite ~12 pixels net travel. Preserve fractional target/EMA state until final delivery. |
| Profiling attribution defect | A missing stage reused the previous frame's timing in WorkloadProfile. Track current-frame stages only; sum repeated calls within that frame. |
| Unsafe drag preparation ordering | Absolute pinch sent DOWN before querying cursor position. A blocked fake query reproduced the held-input window. Prepare the anchor/query before DOWN. |
| Pending emergency concern | Disarm waited on the frame lock before signaling cancellation. Latch stop before waiting; recheck after preparation and before new input. Blocked-query tests confirm no pending DOWN/MOVE. |
| Cleanup recovery gap | Failed immediate release/close could leave input owned in a faulted, disarmed controller until another explicit stop. Add three bounded retries at least 100 ms apart through the existing watchdog/frame loop. |
| Measured redundant CPU work | Profiling 300 feature extractions showed 40,800 nested `_vector` calls. Reuse validated coordinate/edge arithmetic inside geometry operations; retain public validation/overflow behavior and numerical/classifier parity. |
| Unmeasured concerns | Sensor/driver buffering, physical inference/GUI costs, cascaded-EMA feel and natural POINTING flicker need matched webcam tests. No adaptive filter, UNKNOWN tolerance, threshold adjustment or swipe-reset change is justified yet. |

Capture/model settings, two-hand tracking, feature reuse, pinch hysteresis, side
association, state/event contracts, cooldowns, bounded swipe history, preview
buffer reuse and pollKey were retained. No aesthetic refactor, speculative buffer
flushing, capture worker or GUI redesign was introduced.

## Implemented reliability and safety changes

- Relative mapping keeps subpixel motion without changing active margins, gain,
  X inversion, Y mapping, initial anchors or clipping. The former per-frame
  rounding could discard arbitrarily many slow movements.
- Absolute stays opt-in with **80% × 80%** region and **X inversion on** by default;
  relative still defaults to inversion off. Explicit flags override both. Its
  constant pinch offset, release/reset policy and fractional EMA are unchanged.
  Synthetic tests verify settling at all screen corners and bounded drag offsets.
- Fallible absolute position queries/drag preparation occur while the button is
  UP. First acquisition still sends no MOVE. HELD can move without static POINTING.
- Emergency/disarm/safety-failure requests latch before waiting for the frame lock.
  Gates recheck after preparation and before DOWN, MOVE and tab calls. A concurrent
  arm cannot clear a pending stop. Cleanup UP/key-up remains allowed while disarmed.
  Arming also verifies that no completed stop/safety failure occurred during its
  cursor-position query, so an in-flight A request cannot undo a newer emergency.
  Both backends also check the installed cancellation guard at the normal-input
  boundary, including after Win32 foreground/modifier preflight. Release cleanup
  deliberately bypasses that guard. Fake preflight-cancellation regressions send
  no pending shortcut or button-down and retain the emergency status.
- Backend faults remain latched until restart. After failed immediate cleanup,
  up to three retries run at least 100 ms apart. Successful cleanup clears owned
  DOWN status; permanent failure stays visible, without per-frame error spam.
- Read, inference and GUI errors fail closed through cleanup. Temporary inference
  failures stop the application; no stale-observation retry is silently attempted.

UNKNOWN/FIST alone never click or become POINTING. A separately confirmed PINCH
may have an underlying UNKNOWN static label, as required for existing click/drag.
Tracking cancellation forces safety UP without fabricating intentional PINCH
RELEASED. Selected-hand loss never transfers control. The foreground allowlist and
physical-modifier guards for tab shortcuts are preserved.

## Smoothing and preserved recognition policy

Landmark EMA stays .75 and screen EMA .6. These filters and static confirmation can
add perceived delay. Compare --control-alpha .6 versus .75 with every other setting
fixed, testing stationary jitter, large movement, edge precision and pinch
transitions. Do not tune both filters at once. No dead zone/adaptive filter was
added without hardware evidence; the subpixel fix preserves movement rather than
hiding jitter by withholding it.

POINTING preserves the **145° index PIP** calibration and relaxed distal curl
handling. UNKNOWN cancels immediately; subsequent POINTING confirms through the
existing timing/cooldown rules. Brief flicker may interrupt control. No prolonged
pose retention conceals occlusion, foreshortening or backward-facing ambiguity.
Use --gesture-debug to investigate actual failing measurements locally.

Swipe thresholds, OPEN_PALM eligibility, cooldown, **pose change then eligible
stationary rearming**, return-motion suppression and opposing-hand conflict policy
are unchanged. Priority remains PINCH → confirmed SWIPE → static intent, under
safety cancellation. Timing uses actual timestamps, never assumed application FPS.

## Automated and synthetic validation

**445 tests passed**, up from 410: camera 16, gestures 154, hand_tracking 145,
controls 130. Syntax/dependency/CLI/whitespace checks passed. No real input was sent.

Files changed: `controls/controller.py`, `controls/cursor.py`, `controls/models.py`,
`controls/backends.py`, `controls/windows.py`,
`gestures/geometry.py`, `hand_tracking/performance.py`; new offline benchmark
`hand_tracking/benchmark_synthetic.py`; new regression modules
`controls/tests/test_reliability.py`, `gestures/tests/test_geometry_parity.py`,
`gestures/tests/test_reliability.py`, `hand_tracking/test_reliability.py`; this
report plus `README.md`, `controls/README.md`, `gestures/README.md`,
`gestures/POINTING.md`, `gestures/SWIPES.md`, `hand_tracking/README.md` and
`hand_tracking/PERFORMANCE.md`. No camera, inference, classifier, pinch, swipe,
arbitration, Win32 API signatures or GUI implementation was changed.

The exact baseline/final test totals and matched performance table are recorded in
[PERFORMANCE.md](hand_tracking/PERFORMANCE.md). No existing tests were weakened.
New checks cover numerical/reference parity across poses/aspects/rotations,
overflow rejection, calibrated classifications, subpixel motion, corners, offsets,
blocked-query emergency, cleanup retries, variable timestamps, stale timing stages,
safe read/inference/GUI failure, and thousands of mixed gesture/control frames.

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m compileall -q camera gestures hand_tracking controls

# Offline workload costs: synthetic fixtures and virtual input only
.\.venv\Scripts\python.exe -m hand_tracking.benchmark_synthetic --frames 400 --warmup 120 --repeats 3 --report hand_tracking/benchmarks/phase37_synthetic.json
```

The offline tool measures 0/1/2-hand static, static+pinch, full recognition/swipes,
simulated relative and simulated absolute workloads. A repeatable 120-frame cycle
contains pointing, open-palm travel/gradual return, pinch and release. Only virtual
controls automatically arm in this offline harness; live controls remain manual.
Virtual action totals include warm-up. The tool cannot construct a Windows backend
or capture frames. It excludes capture, conversion, inference, preview, OS input
and emergency-thread latency. Synthetic throughput is **not webcam application
FPS** or camera-to-cursor delay. Reports use existing exclusive JSON creation;
choose fresh paths. No raw camera images or benchmark outputs are committed.

## Exact staged hardware commands

These are instructions for the owner, **not automatically executed tests**.
All control launches start DISARMED. A arms, D disarms, Q quits, H toggles help.
Live global emergency stop is **Ctrl+Alt+Esc**; verify it outside preview focus.
Keep the real cursor on the selected monitor. Complete simulation before live.

```powershell
# A: recognition only; both hands, static/UNKNOWN, pinch and swipes; no actions
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes

# Optional POINTING diagnosis; disable debug flags in performance comparisons
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --gesture-debug --gesture-event-debug

# B1: simulated relative cursor, click/drag and tab intent
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-mapping relative --control-hand right --control-invert-x --control-mouse --control-tabs

# B2: simulated absolute, current 80% x 80% region and default inverted X
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-mapping absolute --control-region-width .80 --control-region-height .80 --control-hand right --control-mouse --control-tabs

# C: LIVE CURSOR ONLY; verify emergency stop off-focus before enabling clicks
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-mapping absolute --control-region-width .80 --control-region-height .80 --control-hand right

# D: LIVE click/drag on harmless controls/disposable test objects; tabs off
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-mapping absolute --control-hand right --control-mouse

# E: LIVE browser tabs; Chrome explicitly permitted
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode live --control-mapping absolute --control-hand right --control-mouse --control-tabs --control-browser chrome.exe

# F: 15-minute mixed-workload SIMULATION, plus 5 s warm-up
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-mapping absolute --control-mouse --control-tabs --benchmark --warmup 5 --duration 900 --report hand_tracking/benchmarks/phase37_soak_sim.json

# Only after A-E pass: optional 15-minute LIVE soak on harmless surfaces
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode live --control-mapping absolute --control-mouse --control-tabs --control-browser chrome.exe --benchmark --warmup 5 --duration 900 --report hand_tracking/benchmarks/phase37_soak_live.json
```

Acceptance checklist:

1. **A:** 0/1/2 hands; natural rotated POINTING, OPEN_PALM/FIST/UNKNOWN; no action
   from ambiguous/unsupported poses. Observe confirmation/cancellation and recovery.
2. **B:** correct X/Y directions, four screen corners, region clipping, stationary
   jitter, slow precise motion, rapid motion, reset and reacquisition. No initial
   teleport. Compare alpha .6/.75 separately. Repeat with --control-hand left.
3. **C:** first verify off-focus Ctrl+Alt+Esc on a harmless other window, then A/D,
   boundaries, loss, overlap/crossing and safe reacquisition. Disarmed means no motion.
4. **D:** one DOWN/UP per quick pinch; drag while static POINTING disappears. Check
   closure/release, edges and offsets. In separate drags, test emergency, D, loss
   and exit: no stuck input or new click on closed-hand return. No destructive targets.
5. **E:** harmless browser tabs only; one switch per deliberate swipe, both
   directions, return suppressed, established pose reset, pinch/drag blocking,
   conservative opposite-hand conflicts, unsupported foreground unaffected.
6. **F:** run 10–15 minutes, mixing 0/1/2 hands, slow/fast pointing, clicks, drags,
   swipes, loss/reentry and A/D. Every 2–3 minutes note console FPS, responsiveness,
   jitter, misfires, stale states and button status. Finish with emergency and Q;
   verify release. Compare early/late notes; final bounded percentiles alone cannot
   prove latency never deteriorated. Store aggregate JSON only, no raw images.

## Limits and deferred work

Host read-to-GUI time excludes unknown exposure, USB/driver queue age, compositor,
display and physical response delays. Controller timing includes API calls, not
the eventual application response. Previous 36–39 FPS values are historical, not
Phase 3.7 acceptance; matched repeated webcam runs must determine regressions and
whether 35 FPS is attainable. Safety and recognition quality take priority.

Foreground validation/SendInput is not atomic; elevated/secure desktops may reject
input. An already-running blocked OS call cannot be revoked. The stop latch blocks
subsequent commands, not a hard real-time deadline. Permanent UP failure can need
a physical release/restart; ownership stays visible. Python cannot clean up after
process kill, native/OS crash or power loss. Side predictions are not persistent
identity: undetected same-side replacement may remain indistinguishable. Restart
after display/DPI/desktop reconfiguration. No new physical acceptance is claimed.
Synthetic bounded-state/resource checks do not establish leak-free MediaPipe,
camera-driver or native GUI behavior; those lifetimes need the manual soak test.

Future work only with separate evidence/approval: captured failing landmark
fixtures without raw-image retention, external latency measurement, hardware-led
smoothing tuning and driver queue investigation. No UNKNOWN grace period, adaptive
filter, capture worker, gesture, face, voice, motor or desktop-action expansion.

Suggested commit after review/hardware acceptance:
`fix(visioncontrol): harden gesture-control reliability`.
