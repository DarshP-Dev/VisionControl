# Phase 3.5: directional swipe recognition

The optional Phase 3.7 [palm cursor profile](../controls/PROFILES.md) selects
POINTING eligibility through the existing recognizer; trajectories still use
the palm center. Legacy eligibility remains OPEN_PALM. Raw static classes and
all motion thresholds are unchanged; UNKNOWN remains ineligible.

The Phase 3.7 reliability audit leaves legacy thresholds, eligibility, cooldown and pose-change/stationary
reset policy unchanged. Variable-timing tests and 200 complete synthetic swipe
cycles verify one action per swipe, bounded histories and no opposite action on
return before a neutral-pose reset. See [Phase 3.7 acceptance](../PHASE_3_7.md) for
two-hand, loss/recovery and manual extended-use checks. Hardware acceptance is pending.

Supported motions are **SWIPE_LEFT** (decreasing image x) and **SWIPE_RIGHT**
(increasing image x) in the existing **unmirrored** preview. The direction is
defined by the camera image, independently of which anatomical hand performs it.
This recognizes motion and emits in-process events; it performs no desktop actions.
All defaults are uncalibrated starting values pending the owner's webcam testing.

## Windows launch commands

Run from `C:\Users\Darsh\VisionControl` using the existing venv/model:

```powershell
# Normal tracking; no new recognition/state work
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker

# Existing static + pinch + state pipeline, without swipes
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states

# Swipes, using the existing static eligibility, pinch safety and event channels
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes

# Optional numeric diagnostics and short trajectory trail; optional lifecycle logs
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --swipe-debug --gesture-event-debug

# Example threshold tuning (defaults shown)
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --swipe-distance 1.5 --swipe-velocity 3 --swipe-dominance 3 --swipe-consistency 0.85 --swipe-min-ms 120 --swipe-max-ms 600 --swipe-cooldown-ms 800 --swipe-reset-ms 250 --swipe-feedback-ms 350
```

`--swipes` is opt-in and **requires `--gestures --pinch --gesture-states`**.
The dependencies are explicit, never silently enabled. `--swipe-debug` requires
swipes. Earlier CLI combinations remain valid without swipes. Q/H, MSMF, 1080p
capture, full inference, two hands, EMA 0.75 and Win32 polling are preserved.

Swipe-enabled operation is already combined with static/pinch recognition:
there is no separate model or parallel recognition/event pipeline. Raw static
and pinch labels remain visible. A separate Motion row shows direction/candidate,
cooldown/reset status and briefly accepted or suppressed SWIPE feedback.
The optional debug rows show dx/dy, average/recent velocity, duration, direction
consistency, horizontal dominance, bounds, cooldown and rejection reason. Missing
trajectory measurements display `--`, never fabricated zeros. Yellow trails are
debug-only and are cleared on completion/reset/loss. With two hands, annotations
use separate screen columns; those screen positions are not tracking identities.
During short confirmation feedback, `last dx` and the accompanying metrics refer
to the completed motion, not new movement during cooldown.
The existing optional event log includes numeric motion metrics on swipe lifecycle
events; there is no per-frame console logging from swipe diagnostics.

## Anchor and coordinate normalization

The anchor is the **mean of wrist and four finger MCP landmarks: 0, 5, 9, 13, 17**.
It excludes fingertips so finger extension/curl alone does not translate the
anchor. Use the current EMA-smoothed snapshot (or raw if `--no-smoothing`).

```text
anchor = mean((x, y * capture_height / capture_width) for the five palm landmarks)
baseline scale = cached mean(wrist-to-middle MCP length, index MCP-to-pinky MCP width)
dx = (current_anchor.x - initial_anchor.x) / baseline_scale
dy = (current_anchor.y - initial_anchor.y) / baseline_scale
average horizontal velocity = dx / elapsed_seconds
```

Both position axes use image-width units; y increases downward. This reuses the
existing aspect-correct palm scale without another feature extraction. Positions
are **not divided by a changing per-frame hand scale**, which would create motion
artifacts. Instead, reject trajectories whose scale differs by more than 25%
from their first sample. Uniform image/hand scaling preserves displacement in
palm units. No pixel thresholds or metric-world velocity claims are made.
Out-of-plane rotation/depth movement can still change the projected anchor/scale.

`motion.py` provides typed samples and `MotionMetrics`: normalized dx/dy, total
2D path length, elapsed ms, average/recent horizontal velocity, consistency,
dominance and scale change. Missing/non-finite/zero/negligible-scale geometry
cannot confirm. Repeated/backward/missing timestamps and >250 ms tracking gaps
discard history under the existing state engine's conservative recovery policy.

## Conditions and defaults

All conditions must hold on the confirming observation:

| CLI | Default | Meaning / accepted range |
| --- | ---: | --- |
| `--swipe-distance` | 1.5 | Minimum absolute net dx, in palm units; [0.25, 10] |
| `--swipe-velocity` | 3.0 | Minimum average **and recent** horizontal speed, palms/s; [0.1, 50] |
| `--swipe-dominance` | 3.0 | abs(net dx) / total absolute vertical travel; [1, 10] |
| `--swipe-consistency` | 0.85 | abs(net dx) / total absolute horizontal travel; [0.5, 1] |
| `--swipe-min-ms` | 120 | Minimum duration; integer [30, 1000] ms |
| `--swipe-max-ms` | 600 | Maximum duration, strictly greater than minimum; integer [60, 2000] ms |
| `--swipe-cooldown-ms` | 800 | Shared left/right swipe block for this hand; integer [0, 5000] ms |
| `--swipe-reset-ms` | 250 | Eligible stationary hold before arming; integer [0, 1500] ms |
| `--swipe-feedback-ms` | 350 | Short accepted/suppressed name feedback; integer [0, 1000] ms |
| `--swipe-max-scale-change` | 0.25 | Allowed fractional baseline-scale change; [0.05, 0.5] |
| `--swipe-pose` | `open-palm` | `open-palm` or explicit `open-palm-or-fist` |

The starting distance/velocity reject small or slow repositioning; the duration
window rejects very brief bursts and long movements. Dominance requires a clear
horizontal component and includes **all vertical travel**, so an up/down zigzag
cannot disappear through net cancellation. A 0.01-palm vertical denominator floor
keeps the metric finite for flat paths. Consistency permits small deviations while
penalizing reversals; the entire candidate is retained rather than selecting a
convenient suffix after zigzags. Recent velocity uses approximately the final
80 ms of available samples and must agree with the net direction. A short jump
followed by holding still cannot qualify merely by waiting out minimum duration.
Sparse frames cannot reveal unobserved between-frame motion; no interpolation or
future trajectory prediction is performed.

The initial stationary gate requires total path <=0.15 palms and average path
speed <=0.5 palms/s over the reset interval. An armed candidate begins once net
x/y reaches 0.15 palms or path reaches 0.25 palms. Quiet leading steps <=0.01
palms are trimmed; idle evidence otherwise uses approximately a 100 ms window.
These small starting/reset gates are conservative heuristics, not calibration.

Each per-hand trajectory/rest deque has **at most 64 samples**. Candidate time
is bounded by max duration; expired/capacity-limited/scale-invalid candidates
are discarded and require a pose reset. Rest evidence uses only the latest reset
window plus a bracketing sample. At unusually high sampling rates or long custom
windows, capacity can prevent arming/confirmation; it never permits unlimited
history or silently discards early reversals to accept a fast tail.

## Eligibility, reset and arbitration

Default eligibility requires a unique **OPEN_PALM** static rule match and a valid
pinch **OPEN/RELEASED** observation. POINTING, UNKNOWN, conflicting static rules,
pinch STARTED/HELD/UNAVAILABLE and an already-active pinch block motion evidence.
`open-palm-or-fist` explicitly allows FIST too; it still cannot override pinch
safety. Some physical fists may look pinched in 2D and therefore remain blocked.
Static thresholds and pinch hysteresis/rearming are unchanged.

After a confirmation, **keeping the same eligible pose never rearms**, even after
cooldown. To repeat: change to an ineligible pose (default: close to a fist),
reposition while ineligible, reopen, allow cooldown to finish, then hold still
for the reset interval before deliberately moving again. If both open palm and
fist are eligible, use another ineligible pose or leave/reenter the frame. Zero
cooldown still requires neutral-pose reset and stationary arming. This favors
avoiding unintended return swipes over continuous back-and-forth interaction.

Trajectory evidence lives in the **existing per-hand Phase 3.4 history**. That
manager owns association, cooldown timers, event admission and cancellation;
`SwipeHistory` only collects evidence and remembers whether a motion was consumed.
It reuses `GestureState` for IDLE/CANDIDATE/ACTIVE-confirmation/COOLDOWN display;
there is no second event enum, event bus or persistent identity tracker.

Priority is **PINCH > confirmed SWIPE > static intent**. Swipe evaluation occurs
before a new static activation, so the confirmation frame cannot accidentally
START both static and swipe actions. An already-active static intent is CANCELED
first with `swipe_precedence`. Each admitted swipe then emits exactly:

1. One **GESTURE_STARTED** with SWIPE_LEFT/RIGHT (the confirmation to consume).
2. One **GESTURE_ENDED** at the same timestamp, closing this completed motion.

These form one atomic completed-motion lifecycle, **not two activations**. No
sustained swipe ACTIVE state or repeated updates exist. Event metadata carries
direction and immutable `MotionMetrics`, along with the existing reliable-side
association and timestamp. Future action mapping should consume STARTED once;
no OS actions or action-mapping code are implemented here.

Both swipe directions enter the configured cooldown for this hand; other static
gestures and the other hand retain their existing independent state behavior.
Raw static/pinch results are never overwritten. The Motion name expires after
feedback duration (zero disables extra persistence). The existing `Last: ...`
event row remains a historical event display, never a new current confirmation.

Two confident, uniquely associated hands have independent histories; detection
order is irrelevant. Same-direction simultaneous swipes are permitted per hand.
If one confirms while the other has an opposite candidate, **suppress both
current motions**, consume their histories and apply cooldown/reset. Diagnostics
retain raw confirmation/metrics with `admitted=False` and
`opposite_two_hand_motion`. A later opposite confirmation within
`min(200 ms, swipe cooldown)` of a recent completion is suppressed as well;
the already-completed earlier event is not retroactively undone. Same-direction
motions remain independent. This is a conservative conflict guard, not desktop
action mapping or a global hand identity model.

Loss removes the affected history immediately; another reliable hand can continue.
Ambiguous/duplicate handedness, overlap/close wrists, frame-size changes and long
gaps use the existing cancellation/reset gates. The existing wrist-jump gate also
remains, so very fast/large between-frame translations can be rejected as unsafe
association. Reacquisition must build fresh stationary/trajectory evidence; no
incomplete swipe completes on loss. Confident side swaps that escape these gates
remain a limitation. Completed swipe pulses do not replay or cancel again on shutdown.

## Reproducible webcam calibration and acceptance

1. Start diagnostics; use one hand at normal distance, open and hold still until
   `ready`. Move deliberately right/left. Observe dx, both velocities, elapsed
   time, consistency/dominance and confirmation. Repeat with each hand.
2. Test stationary fingers changing pose, slow horizontal repositioning, short
   nudges, vertical/diagonal motion and zigzags. None should produce swipe STARTED.
   Note the displayed rejection rather than weakening all thresholds together.
3. If valid motions are consistently too small/slow, lower distance/velocity in
   small steps and repeat negative tests. Adjust dominance/consistency only when
   measured natural paths justify it. Longer max duration may admit repositioning;
   shorter min duration may admit bursts. Keep matching capture/EMA settings.
4. After a successful swipe, return with OPEN_PALM: no second swipe should occur.
   Then close/change pose, reposition, reopen, hold still after cooldown, and
   intentionally swipe again. Check feedback expiry and reset messages.
5. Test several distances/frame sizes and moderate hand rotations. Moving toward
   the camera or rotating strongly may cause `scale_changed_change_pose`; do not
   assume projected translation accurately describes 3D hand motion.
6. Enable event logs to verify one STARTED/ENDED pair. Check raw OPEN_PALM/FIST/
   POINTING/UNKNOWN and pinch lifecycle still work; pinching must block swipes.
7. Test both hands independently, detection-order changes, one disappearing,
   crossing/overlap and reacquisition. Try simultaneous opposite motions to check
   suppression, plus same-direction motions to check independent associations.
8. Verify Q/H, tracking quality and responsiveness. Compare FPS with all diagnostics
   disabled; approximately 35+ FPS is a target, not a verified hardware result.

## Tests and sequential performance commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check

# Run sequentially under matching lighting, hand count, motion and camera settings
$swipeRun = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\states_${swipeRun}.json"
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\swipes_${swipeRun}.json"
```

Reports refuse overwrite and use the existing ignored benchmarks directory.
JSON `swipes` records thresholds and admitted confirmation counts, counting a
swipe **once**, not once per lifecycle event. Existing event counts include both
STARTED and ENDED. Counts/timing exclude warm-up; history runs throughout it.
`swipe_processing` measures trajectory evaluation and conflict checks, **nested
within `state_management`**; do not sum them. Lifecycle event creation stays in
state-management timing. Drawing/trails are included in landmark rendering and
optional event logs in full-loop FPS. No extra inference, feature extraction,
image copies, threads, models or dependencies are introduced.

All **253 tests pass**: 135 gesture, 102 tracking and 16 camera tests. The 214-test
baseline remains unchanged and passing; 39 added tests cover geometry, anchors,
scales/aspects, motion acceptance/rejection, recent speed, duration, bounded
buffers, cooldown/reset, eligibility, events, two hands/conflicts, recovery,
CLI, EMA input, rendering/clearing/layout, Q/H/native polling and benchmark JSON.
The 30 swipe core tests also run with `python -S` without third-party packages.

An interleaved synthetic test used two hands, a repeating 40-observation cycle
(rest/open, movement/open, fist return, rest/open), 100 warm-up + 1000 measured
samples per configuration, 50 ms input timestamps, alternating order and disabled
Profile collection. No camera, inference, smoothing, rendering or logs were included:

| Work (ms per two-hand observation) | Mean | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Recognition bridge + existing states | 4.293 | 4.114 | 5.346 | 6.046 |
| Same pipeline + swipes | 4.547 | 4.371 | 5.773 | 6.386 |
| Nested swipe processing | 0.182 | 0.183 | 0.315 | 0.523 |

Host load/scheduling affect results; comparisons to earlier milestone timings
from separate runs are not meaningful. These synthetic observations do not
establish physical accuracy, world-space motion or application FPS. Webcam
acceptance is pending. Recommended commit after acceptance:
`feat(gestures): add directional swipe recognition`.
