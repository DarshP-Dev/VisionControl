# Phase 3.7: optional Left-hand pinch rearming

This reduces keyboard use after routine tracking interruptions. It reuses existing
pinch recognition; it adds no gesture classifier or Windows action. It is disabled
by default. Right remains the only desktop-control hand, including clicks/drags
and browser shortcuts. Left only requests a checked rearm while disarmed.

## Sequence and defaults

1. Start DISARMED in simulation or live. Show a valid Right hand and press **A**.
   A must have succeeded at least once in this running controller.
2. After a routine tracking/association interruption, input stops, owned buttons
   are released, and cursor anchors are reset. Restored tracking alone never arms.
3. Show **both** distinct hands with separated Left thumb/index. Allow at least
   **300 ms** of uninterrupted confident association before starting the gesture.
4. Complete Left **OPEN → STARTED → HELD → RELEASED** through the existing pinch
   detector and gesture manager. Hold for at least **800 ms**, then release.
   A HELD observation must actually reach 800 ms before the release observation;
   time spent between the last HELD and RELEASED does not extend the hold.
5. The controller rechecks eligibility and backend position through the same
   trusted arming path used by A. Completion sends **no MOVE, DOWN or shortcut**.
   A subsequent valid Right observation acquires a fresh cursor anchor. Right
   must open after arming before a fresh Right STARTED can click. A Right pinch
   already held during rearming cannot replay a click.

Observation timestamps come from the existing monotonic pipeline, never frame
counts. Repeated/backward timestamps or gaps over 250 ms cannot complete a hold.
Missing OPEN, momentary pinches, missing release, orphan HELD, absent/invalid hands,
or interrupted associations cancel progress. Require fresh stable OPEN and a new
complete sequence. Repeated HELD observations never request multiple arms.
Closed Right reacquisition is also subject to the existing pinch detector's
open-before-rearming policy; show separated Right thumb/index after tracking loss.

## Routine loss versus safety stop

The controller explicitly distinguishes routine tracking disarms from hard/manual
stops; it does not infer eligibility by matching display strings. An eligible
routine stop must descend from a successful arm or an already eligible routine
stop, and must have no newer hard stop.

| Condition | Gesture recovery |
| --- | --- |
| Startup, before first A | Blocked; manual A required |
| Selected hand absent; uncertain/duplicate labels; overlap; wrist discontinuity; association/pinch tracking cancellation | Available only after safe reacquisition and the full Left sequence |
| D or global emergency shortcut | Blocked; explicit A required after safe tracking returns |
| Watchdog stall or invalid/non-monotonic timestamp/channel/geometry invariant | Blocked; manual recovery required |
| Backend failure, release failure or emergency-monitor failure | Blocked; existing latched faults require restart, not gesture/A bypass |
| Shutdown | Blocked |

Later routine tracking loss does not clear a manual/emergency latch. After a
healthy D/global-stop recovery with **A**, a *new* routine interruption may become
eligible again. A cannot override an unresolved backend/monitor fault. Resolve
the cause, restart when required, verify emergency delivery, then manually arm.

Critical stops latch cancellation and revoke gesture eligibility **before** waiting
for the controller lock. Each gesture request carries the stop-generation token
from its validated frame. Arming rechecks that token, pending stops, health and
eligibility both before and after the fallible cursor query. An older or in-flight
request cannot undo a newer emergency. Existing backend gates, watchdog, button-up
cleanup and bounded release retries remain in place.

## Association safeguards and limitations

Both hands must have exactly one unique Left/Right prediction, score at least
**0.90**, compatible image geometry, valid existing pinch channels and no unsafe
manager association/cancellation. Prediction scores are model metadata, not
calibrated identity probabilities. The returned detection-list order has no role.

Overlap and close wrists use existing association gates. Consecutive wrists for
each side must also remain continuous on aspect-correct image-width axes. The
allowed per-frame displacement is `min(0.10, 0.015 + 1.5 * elapsed_seconds)`.
The cap reuses the existing pinch wrist-jump limit. Sudden jumps, label swaps,
low confidence, image-size changes or losing either hand cancel the sequence.
Require the stable interval again afterward. These are conservative starting
values, not hardware-calibrated guarantees. Keep both hands steady and apart.

This is a deliberate usability gesture, **not authentication** or biometric
identity. Continuous high-confidence misclassification or undetected replacement
cannot be ruled out by two label/position histories. Ambiguity refuses gesture
rearm; keyboard A remains available once existing safety checks pass. No persistent
identity tracker is added. Better multi-hand identity association remains separate
future work. No webcam accuracy, FPS or physical input behavior is claimed here.

## CLI and feedback

- `--control-gesture-rearm`: opt-in; requires `--controls --gestures --pinch
  --gesture-states` and `--control-hand right`. Left desktop control is rejected
  with this feature, avoiding conflicting hand roles.
- `--control-rearm-hold-ms 800`: integer **500–3000 ms**.
- `--control-rearm-stable-ms 300`: integer **150–2000 ms** for continuous two-hand
  confidence/association before a fresh Left OPEN.
- `--control-rearm-debug`: optional sampled diagnostics, at most once per 2 seconds.
  Rearm timing/debug options require `--control-gesture-rearm`.

One extra compact white-on-black status row appears when relevant: blocked/manual
arm required, stabilize both hands, OPEN to start, hold progress, release to confirm,
or REARMED. REARMED feedback expires after one second of observations. Gesture
labels remain separate. Defaults, existing commands, Q/H, A/D and the configured
global shortcut are preserved.

## Exact PowerShell commands

Run from `C:\Users\Darsh\VisionControl`. All commands start DISARMED. These examples
use the existing Ctrl+Shift+F10 alternative; Ctrl+Alt+Esc remains the default when
that option is omitted. Successful registration does not guarantee remote delivery.

```powershell
# A. Simulation: complete recognition, swipes and virtual click/drag/tab actions.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-mouse --control-tabs --control-gesture-rearm --control-rearm-hold-ms 800 --control-rearm-stable-ms 300 --control-rearm-debug --control-emergency-hotkey ctrl+shift+f10

# B. Live cursor ONLY: verify global stop outside preview focus before arming.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-gesture-rearm --control-rearm-hold-ms 800 --control-emergency-hotkey ctrl+shift+f10

# C. Live click/drag: only after simulation and cursor-only safety checks pass.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-mouse --control-gesture-rearm --control-rearm-hold-ms 800 --control-emergency-hotkey ctrl+shift+f10

# Optional matched simulation benchmark; use a fresh report filename each run.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --benchmark --warmup 3 --duration 30 --report hand_tracking/benchmarks/rearm_simulation.json

.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
```

## Hardware acceptance checklist (owner testing)

1. In simulation, verify startup cannot gesture-arm. Press A. Remove Right and
   confirm DISARMED. Restore both, stabilize with Left open, hold Left pinch for
   0.8 s and release. Expect REARMED with no action on release. Right then resumes
   normal pointing, click/drag and optional swipes.
2. Reject short Left pinch, already-pinched entry, Right pinch alone, loss of
   either hand during hold, rapid label changes, crossing, overlap and return with
   Right already pinched. Require fresh OPEN after each canceled attempt.
3. Press D during an attempt: the Left sequence must stay blocked even after
   more hand loss/reacquisition. Return with healthy Right and press A explicitly.
   Repeat for Ctrl+Shift+F10 in live mode, including another application's focus
   and the actual remote-desktop connection, before enabling mouse actions.
4. Test live cursor only, then a disposable click/drag surface. Routine Right loss
   during drag must release the button. Rearming must never click, replay a tab
   event, jump on confirmation, or transfer control to Left. Verify Right opening
   then a fresh pinch works normally after recovery.
5. Confirm intentional/emergency stops require keyboard recovery; faulted monitor,
   backend or failed release requires resolved cause/restart. Never bypass a fault
   to test rearming. Verify Q, D and shutdown release owned inputs.
6. Repeat mixed loss/recovery cycles for 10–15 minutes. Record false rearm attempts,
   interruptions, FPS, responsiveness and stuck inputs. No raw images are saved.

## Automated and isolated performance validation

Baseline: **473 tests** at clean commit `28383bc`. Final: **531 passing tests**:
camera 16, gestures 154, hand_tracking 161, controls 200. The 58 added tests cover
sequence/timing boundaries, real pinch/manager integration, identity refusals,
routine/hard stops, held-button release, stale events, arming races, both mappings,
fake live backend, CLI, UI, Q/H, profiling and thousands of synthetic observations.
Existing tests were retained. No actual Windows input, hotkey registration or
camera capture was performed. Syntax/dependency/whitespace checks passed.

A follow-up review caught a combined-error edge case: a side mismatch could
downgrade a simultaneous critical manager error into routine recovery. Critical
time/geometry/channel reasons now take precedence, with a regression covering
all five critical reason codes and explicit manual recovery afterward.

The validator reuses prepared features and pinch/state outputs. Its state is
constant-size; no trajectory/event queue, inference, full feature extraction,
dependency or extra thread is added. `gesture_rearm` JSON timing is nested inside
`controller_processing`: disarmed validation/request cost, zero on skipped frames.
It is not camera-to-input latency. Compare matched enabled/disabled simulation
runs, exercising the disarmed rearm path; armed-only runs do not measure it.

One isolated synthetic run used 700 warm-up and 4,200 measured observations
(300 full completed sequences): validator mean **0.0222 ms**, median **0.0209 ms**,
P95 **0.0258 ms**, P99 **0.0545 ms**. Inputs were prepared outside measurement;
this excludes controller locking, arming/backend queries, capture, MediaPipe,
rendering and real OS input. It establishes no webcam FPS or physical accuracy.

Suggested commit after hardware testing:
`feat(controls): support safe left-hand pinch rearming`.
