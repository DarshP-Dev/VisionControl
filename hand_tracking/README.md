# Hand tracking with optional gesture recognition, states and events

Detect and draw **up to two hands**, each with 21 landmarks and a skeleton, using the
MediaPipe Tasks Hand Landmarker API in synchronous **VIDEO** mode on the CPU.
Optional static recognition labels open palm, fist, pointing and unknown poses.
Optional pinch recognition measures normalized thumb/index proximity with a
separate OPEN/STARTED/HELD/RELEASED/UNAVAILABLE lifecycle; it adds no static class.
Phase 3.4 optionally stabilizes static results and resolves pinch precedence into
typed events; raw recognition remains visible and unchanged.
Phase 3.5 optionally recognizes palm-trajectory SWIPE_LEFT/SWIPE_RIGHT through
the same event manager, with pose eligibility, motion metrics and reset safeguards.
Phase 3.6 adds a separate opt-in desktop mapper: simulation by default, explicit
arming, relative cursor, pinch click/drag and independently enabled browser tabs.
See [controls/README.md](../controls/README.md) for commands, global
**Ctrl+Alt+Esc** stop, safety gates and staged local testing. Tracking/recognition
commands alone still send no desktop input. Voice and motor controls are absent.
For reversed-feeling horizontal pointer movement, add `--control-invert-x` to a
controls command. This opt-in calibration changes only the cursor's horizontal
delta; vertical movement, the unmirrored preview and recognition remain unchanged.
The existing Phase 1 camera applications are unchanged.
Inference size is configurable independently of capture; detailed benchmarking
and host timing reports are available. See [PERFORMANCE.md](PERFORMANCE.md) for
the measured synthetic baseline, limitations and full comparison procedure.
Lightweight landmark EMA smoothing is enabled conservatively by default, with
raw comparison and explicit reset behavior described below.
Phase 2.5 uses native Win32 GUI polling when supported, retaining an explicit
`waitKey(1)` baseline and a timed headless comparison. Full inference, MSMF,
two-hand model options, drawing, confidence thresholds and EMA alpha 0.75 are
unchanged. The owner's Phase 2.5 comparison measured 28.98 FPS with the old GUI
path and 38.77 FPS with native polling. The owner verified static gestures after
POINTING calibration at approximately 36 FPS. New Phase 3.3 pinch accuracy/FPS
still await local hardware testing; backward-rotation static ambiguity is unchanged.

## Run on Windows

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker
```

To enable per-hand static gesture labels in this same preview:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --no-gestures
```

Recognition is **off by default**. `--gestures` uses the selected
raw/EMA coordinates with actual capture aspect correction, without modifying
MediaPipe results. Each wrist label includes `OPEN_PALM`, `FIST`, `POINTING` or
`UNKNOWN`. No observation means no gesture label; nothing persists after loss.
Q/H, colors, handedness, full inference and all previous arguments remain active.
`--show-raw-landmarks` adds comparison markers without changing recognition input.
The rules are immediate per-frame heuristics and may flicker; they do not produce
calibrated confidence percentages. See [gesture rules, thresholds and manual
testing](../gestures/README.md) for limitations and repeatable off/on benchmarks.
`gesture_features`, `gesture_classification` and `gesture_total` profile the new
work separately, including in headless runs and per-hand-count reports.

## Phase 3.5 directional swipes

```powershell
# Swipes need existing static eligibility, pinch safety, and event state channels
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes

# Optional motion diagnostics/trail and existing event log
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --swipe-debug --gesture-event-debug
```

`--swipes` defaults off and requires all three shown recognition/state flags.
`--swipe-debug` requires swipes. Normal tracking and earlier CLI combinations are
unchanged. Directions refer to the **unmirrored image**, not anatomical hand side.
No new model, inference, dependencies, threads, desktop actions or frame copies.

The anchor averages wrist + four MCP landmarks and uses the existing cached palm
scale in aspect-correct 2D coordinates. Defaults require 1.5 palms horizontal
displacement, 3 palms/s average/recent speed, horizontal dominance 3, consistency
0.85, duration 120–600 ms and <=25% scale change. OPEN_PALM is eligible by default;
POINTING/UNKNOWN and active/unavailable PINCH block swipes. Static thresholds and
pinch hysteresis remain unchanged. The optional `--swipe-pose open-palm-or-fist`
widens eligibility while retaining the pinch gate.

PINCH > confirmed SWIPE > static intent. Each swipe emits one STARTED/ENDED pair
at confirmation through the Phase 3.4 manager; a future consumer uses STARTED once.
An active static intent is canceled first. A swipe uses both directional cooldown
timers for that hand (800 ms); no repeat can occur until an ineligible pose is
observed, followed by an eligible stationary hold (250 ms) after cooldown. Return
while still OPEN_PALM remains blocked. Feedback expires after 350 ms. Opposing
two-hand candidates are suppressed, with raw diagnostics retained. Missing/unsafe
associations discard trajectories. Stable Left/Right predictions are not guaranteed
persistent identities; projection/rotation and continuity gates remain limitations.

Motion results have a separate row; `--swipe-debug` adds dx/dy, speed, duration,
consistency/dominance, requirements/reason, cooldown and a cleared-on-reset trail.
Two-hand annotations use separate screen columns. JSON records admitted swipe
counts/settings; `swipe_processing` is nested inside `state_management`, while
preview drawing and existing loop/FPS timings include their respective new work.
Synthetic nested swipe mean/p95 were 0.182/0.315 ms per two-hand observation;
physical accuracy and the ~35+ FPS target still require owner webcam validation.
See [SWIPES.md](../gestures/SWIPES.md) for all CLI ranges, exact test/benchmark
commands, reset policy, event structure and manual acceptance checklist.

## Phase 3.4 gesture states and events

```powershell
# Static confirmation and events
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-states

# Independent pinch lifecycle events only (open fingers first)
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch --no-gestures --gesture-states

# Raw static + pinch overlays, plus resolved intent/state and latest event
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states

# Explicit event diagnostics; no images or video recorded
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --gesture-event-debug
```

States are **off by default** and require at least one enabled recognition channel;
`--gesture-event-debug` requires states. All original flag combinations still work.
No OS actions, cursor, clicks, keys, voice or new models are implemented.

Defaults: `--gesture-activation-ms 100`, `--gesture-transition-ms 60`,
`--gesture-cooldown-ms 150`, `--gesture-update-ms 250`. Each accepts integer
0–5000 ms. Zero activation/transition/cooldown removes that delay; zero update
disables UPDATED events. Confirmation uses the existing monotonic frame timestamp,
not frame counts. Static candidates require stable recognition; a known replacement
ends the old pose after transition stability and confirms from its first appearance.
UNKNOWN/conflicts immediately CANCEL, never become actionable. Same-gesture
cooldown is per hand and gesture; other gestures can become candidates meanwhile.

PINCH takes precedence in a separate resolved intent stream, canceling an active
static intent before starting. Its already-confirmed STARTED/RELEASED have no
additional delay/cooldown. HELD never creates a missing START; UNAVAILABLE cancels
and suppresses static fallback. The manager must observe OPEN/RELEASED before
admitting a fresh STARTED, including after loss. Original pinch hysteresis/rearming
and all raw static thresholds are unchanged. Existing side/overlap helper code is
shared by both consumers without changing those Phase 3.3 gates.

The compact white-on-black row shows IDLE/CANDIDATE/ACTIVE/COOLDOWN, confirmed
intent and latest event; the raw static/pinch label and skeleton colors remain.
Optional logs distinguish STARTED, distance UPDATED, intentional ENDED and CANCELED
with timestamps/reasons. Unchanged active holds do not repeatedly START or log
per-frame updates. Pinch distance UPDATED is limited by time and >=0.02 palm-unit
change. Last-event text is historical, not a new emission. Q/H and native polling
are preserved. Use `--pinch-debug` independently for numeric recognition diagnostics.

Confident unique Left/Right predictions associate consecutive frames; detection
order never transfers state. Missing hands, unsafe overlap, uncertain labels,
invalid geometry/time, dimension changes or >250 ms gaps cancel histories.
Cancellation on loss references the former side, marked `association_current=False`,
and never claims intentional release. Fresh static candidates must reconfirm;
closed pinch reacquisition must reopen. Confident side swaps that escape the
continuity gates remain a limitation. See the [full transition policies, timestamp
handling, exact tuning/benchmark commands and manual checklist](../gestures/README.md#phase-34-stabilized-gesture-events).

`state_management` appears in overall/per-hand-count profiles. JSON records state
settings, measured snapshot/event counts and separate reset/shutdown cancellations.
Counters exclude warm-up, while state continuity runs throughout. Engine timing
excludes optional console logging; full-loop timing includes it. Recognition
features are shared, with no extra inference or feature extraction. Synthetic
two-hand engine mean/p95 were 0.044/0.085 ms, excluding camera/inference/GUI;
physical accuracy, responsiveness and the ~35+ FPS target remain unverified.

## Phase 3.3 pinch channel

```powershell
# Pinch alone; open fingers once before pinching to arm the lifecycle
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch

# Live numeric distance, bounds, geometry validity, state/rearm diagnostics
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch --pinch-debug --pinch-activation 0.25 --pinch-release 0.40

# Static gestures and pinch together, sharing extracted features
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch
```

`--pinch` is independent of `--gestures` / `--no-gestures`. No flag means the
original tracking behavior. `--pinch-debug` requires `--pinch` and adds one small
numeric row near each hand, with no per-frame console logging. The main label
shows pinch state; highlighted thumb/index tips and their line are gray OPEN,
yellow STARTED, green HELD, orange RELEASED or purple UNAVAILABLE. Skeleton
colors, static labels, Q/H, MSMF and native polling remain unchanged.

Pinch distance is aspect-correct 2D tip distance (indices 4 and 8) divided by the
existing mean palm length/width. Defaults start **below 0.25** and release **above
0.40** palm units; CLI values must satisfy `0 < activation < release <= 2`.
These are uncalibrated starter thresholds, not physical contact detection.
Projected overlap, perspective and occlusion remain limitations.

After startup or tracking loss, open beyond release to arm/rearm. Closed
reacquisition is UNAVAILABLE, never a fabricated STARTED/RELEASED. Unique confident
side labels support independent histories without assuming detection order;
uncertain/duplicate labels, overlap, large wrist jumps, invalid geometry or timing
invalidate histories conservatively. Left/Right predictions are not persistent IDs.
STARTED/RELEASED last one observation and can be visually brief. Geometry validity
can be true while identity/rearming makes the pinch state UNAVAILABLE.

The existing smoothed results feed both channels, with one feature extraction per
hand when combined. `pinch_processing` measures the lifecycle separately;
`pinch_features` is adaptation/geometry for pinch-only runs. Combined runs share
`gesture_features`; preview drawing and full-loop profiles include the new work.
Warm-up remains excluded, and JSON contains pinch settings/status counts and
per-hand-count timings. No additional model, inference, threads or dependencies.
See [pinch calibration, sequential benchmark commands, tests and manual checklist](../gestures/README.md#phase-33-real-time-pinch-proximity).

The synthetic combined recognition bridge averaged 1.555 ms vs 1.479 ms for
static-only in an interleaved test; the pinch portion averaged 0.105 ms. This
excludes camera, inference and rendering and does not verify the 35+ FPS target.

## Existing POINTING diagnostics

For the focused POINTING calibration, enable sampled numeric diagnostics:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug
```

Debugging is off by default and requires `--gestures`. It logs POINTING
measurements and PASS/FAIL blockers at most once every two seconds, with no
images or raw landmark coordinates. This is logging cadence only; classifications
remain immediate. See [calibration findings and log collection](../gestures/README.md#targeted-pointing-calibration-and-diagnostics)
for the bounded POINTING-only tolerances and narrow thumbs-up exclusion from FIST.
The owner verified static behavior after POINTING calibration and approximately
36 FPS recognition. New pinch recognition still needs webcam testing.
Disable debugging when comparing performance.

To try a smaller inference image while keeping 1080p capture and a clear preview:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --inference-resolution 960x540
```

Inference defaults to `full` to preserve the established path until local quality
testing. Also supported: `1280x720`, `640x360`, or positive `WIDTHxHEIGHT` bounds.
The image fits within those bounds without cropping, padding, stretching or
upscaling. Actual inference dimensions are logged; they may differ for another
camera aspect ratio. `--width` and `--height` still configure capture only.

For a fresh checkout, complete the dependency and model setup below before
launching. Defaults are
camera index 0, **MSMF**, and a request for 1920 × 1080 at 60 FPS. MSMF remains
the default because the owner's Phase 1 webcam tests measured about 60 FPS with
MSMF versus about 5 FPS with DirectShow. The format request remains MJPG for
consistency with Phase 1, but the actual MSMF transport was inconclusive and is
not assumed to be MJPEG. Configuration acceptance and driver readbacks are logged
using the existing Phase 1 diagnostic helpers.

Override capture settings or the model location:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --camera-index 1 --width 1280 --height 720 --fps 30
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --backend dshow
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --model C:\Models\hand_landmarker.task
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --help
```

Use module invocation (`-m hand_tracking.hand_tracker`) from the repository root
so the tracker can import its package and the existing camera utilities.

## Smoothing and recovery

The new display-only EMA blends normalized x/y/z landmarks after inference:

```text
filtered = alpha * current_raw + (1 - alpha) * previous_filtered
```

| Option | Meaning |
| --- | --- |
| `--smoothing` | Enable smoothing (default) |
| `--no-smoothing` | Display original MediaPipe coordinates; retain no EMA state |
| `--smoothing-alpha 0.75` | Current-measurement weight; finite and greater than 0, at most 1 |
| `--show-raw-landmarks` | Overlay raw normalized points as white crosses; skeleton remains the selected raw/smoothed display |

**Higher alpha is more responsive and applies less smoothing.** Lower alpha
suppresses more jitter but can make slow motion trail. Alpha 1 is equivalent to
raw display. The default 0.75 keeps 75% of the new measurement. No frames are
queued or delayed for smoothing, but the visual lag of an EMA is not zero and
must be assessed locally. There is no extra dead zone, gesture logic or prediction.

The original MediaPipe result object and landmark objects are never mutated.
The loop retains `raw_result` and builds a separate display result only when
coordinates are actually filtered. Handedness/confidences and world landmarks
remain raw. The renderer still maps normalized coordinates to the preview,
independently of inference resolution. Do not treat display EMA output as a
verified measurement or assume it improves model accuracy.

The filter retains separate Left and Right histories only when those labels are
unique and have confidence at least 0.8. It uses the label paired with each
detection in the current result, never list order. The following safety rules
favor current measurements over an uncertain association:

- A missing hand's history is removed immediately. No detected hands means no
  history and no overlay. The first measurement on reappearance is shown raw.
- Unknown, duplicate, missing or low-confidence handedness, or malformed
  coordinates, clear all histories and use current raw results. Detection
  confidence settings are unchanged; the 0.8 threshold gates smoothing only.
- Overlapping normalized landmark bounding boxes, or wrists closer than 0.10
  normalized x/y units, clear history and bypass EMA for that frame. When the
  hands separate, each starts again from its current raw measurement.
- For a confidently labeled hand, movement of **any landmark** by more than
  0.06 normalized x/y Euclidean units between consecutive raw frames bypasses
  EMA and reseeds that hand from raw coordinates. This includes large jumps
  caused by label changes; it is not physical velocity measurement.
- Exactly unchanged raw coordinates snap to raw and avoid residual settling
  lag. Stationary detector jitter still uses EMA; there is no claim to reliably
  classify a hand as stationary.
- A frame timestamp gap over 250 ms, non-increasing timestamps, a capture-shape
  change or application exit resets history. No interpolation fills a gap.

These are conservative **history-discard gates**, not persistent identity
matching. High-confidence handedness can still be wrong or flip between nearby
hands, and occluded hands may temporarily vanish. No reliable physical identity
through arbitrary crossings is claimed. In ambiguous/overlapping frames the
preview intentionally reverts to raw measurements, which can visibly be noisier.

Compare raw and smoothed tracking from the repository root, one run at a time:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --no-smoothing
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --smoothing --smoothing-alpha 0.75
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --smoothing --smoothing-alpha 0.75 --show-raw-landmarks
```

The third command compares raw white crosses with colored smoothed landmarks
in the same frame. H shows the marker legend. Q and all capture/inference options
are preserved. Markers are off by default because they add drawing work.

For a timed comparison with full inference and identical capture settings:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --no-smoothing --inference-resolution full --warmup 3 --duration 30 --report hand_tracking\benchmarks\phase24-raw-01.json
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --smoothing --smoothing-alpha 0.75 --inference-resolution full --warmup 3 --duration 30 --report hand_tracking\benchmarks\phase24-ema-01.json
```

Use fresh filenames for repeats. Keep the same lighting, visible hands, motions,
distance and camera settings. Compare application FPS, processing p95 and the
separate `smoothing` timing stage. Reports store enabled state, alpha and whether
raw markers were drawn. The markers' drawing cost is part of `landmark_drawing`,
not `smoothing`. Disable markers for a fair performance comparison. Warm-up
exclusion, percentile reporting and bounded timing storage remain unchanged.

A synthetic smoothing-only check with two separated hands, 100 warm-up and 3000
measured jittered frames, measured **0.090 ms mean, 0.105 ms p95, 0.324 ms p99**
and 0.789 ms maximum on the implementation environment. This excludes camera,
inference, drawing and GUI and is **not** a hardware FPS or responsiveness result.
The owner's current full-resolution baseline is about **28–29 application FPS**.
Phase 2.4 overhead, jitter reduction and perceived lag need local webcam testing.

Manual stability checks:

1. Compare a stationary open hand in raw and smoothed modes; observe fingertip
   jitter. Then try the raw-marker overlay for a direct comparison.
2. Make small, slow finger movements: confirm real motion remains visible and
   decide whether the default alpha trails unacceptably. Raise alpha or disable
   smoothing if necessary.
3. Move or flick hands rapidly; check that large motion uses current positions
   rather than dragging an old skeleton behind it.
4. Remove one hand, then both. Overlays should vanish immediately. Reintroduce
   each hand at a new location; its first points must not interpolate from the
   old location.
5. Cross/overlap hands, separate them, and switch their screen positions. Expect
   raw behavior while identity is ambiguous, then fresh filtering after separation.
6. Check one and two hands, Q/H, reentry, and FPS/profile reports under the same
   conditions. No physical stability or latency claim is made before this test.

## Controls and local testing

| Key | Action |
| --- | --- |
| Q | Quit |
| H | Show/hide the short help line |

Focus the preview to use keys. Closing the window or pressing Ctrl+C also releases
the webcam and landmarker. The preview fits inside 1100 × 650 pixels while the
capture request remains unchanged. A separate inference image is optionally
downscaled before BGR-to-RGB conversion. The clear preview uses the original BGR
capture, not the smaller inference image. Landmarks are mapped from normalized
coordinates onto the resized preview, without mirroring the feed. Colored points
with dark borders and matching skeleton lines mark each hand. A label near each
wrist displays its handedness prediction. A compact black status panel shows
application FPS, the hand count (0, 1 or 2), captured resolution, and exit instructions.

### Handedness, colors and detection order

The application does not horizontally flip either inference input or preview.
With the pinned current Tasks API and unmirrored camera input, `Left` and `Right`
refer to the subject's anatomical hands, not the left/right side of the screen.
Keep any vendor/driver mirroring disabled as well. Do not apply the legacy
`mp.solutions.hands` mirrored-input label-swapping rule to this Tasks pipeline.
The Tasks label mapping changed in
[Google's handedness update](https://github.com/google-ai-edge/mediapipe/commit/ed0c8d8).
Validate the labels by showing each of your hands individually during local testing.

- **Left:** green skeleton, points and wrist label.
- **Right:** blue skeleton, points and wrist label.
- **Unknown:** gray if the prediction is missing or unrecognized.
- If both detections have the same predicted label, both are retained. The second
  uses purple so the skeletons remain distinguishable. The displayed labels are
  not forcibly reassigned to make one Left and one Right.

Each frame pairs landmark entry `i` with handedness entry `i` from that same
result. Detection order can change between frames; it is never treated as a
persistent ID. Colors follow handedness, not screen position. In ambiguous cases,
labels and colors may change, including during crossing or occlusion; there is
no persistent identity tracker. Ambiguous detections bypass smoothing as described
above. The purple fallback is not a persistent ID.
Frames are drawn from scratch, so missing detections never reuse old skeletons.
Malformed landmark sets are skipped without discarding another valid hand.

For local hardware validation:

1. Close the Phase 1 preview and other webcam apps, then start the tracker.
2. Show one hand with fingers spread. Check that all five fingers and the wrist
   have points and connected lines, aligned with the displayed hand.
3. Show the other hand alone and check both Left/Right labels against your own
   hands. Then show both: confirm two sets of 21 landmarks, different colors and
   labels beside the corresponding wrists.
4. Move both hands slowly, then rapidly, near/far and toward the frame edges.
   Cross and overlap them, separate them again, and observe recovery from loss.
5. Remove either hand, reintroduce it, then remove both. Counts should change
   2 → 1 → 2 → 0 without stale skeletons or crashes. Colors must follow the
   predicted anatomical side when the hands exchange screen positions.
6. Test H, Q, and closing the window; confirm the camera is available afterward.
7. Compare application FPS and stage timing logs for one and two visible hands
   under the same lighting, camera settings and movements.

The owner physically tested Phase 2.1: **35.81 average application FPS**, about
**13.51 ms inference per frame**, and excellent one-hand tracking during movement.
The owner subsequently measured approximately **31 application FPS** with two
hands in Phase 2.2, with 42 landmarks, and about **28–29 FPS** after Phase 2.3
using full inference. The owner's Phase 2.4 measurements were **42.00 FPS** with
no hands, **28.42 FPS** with one hand, **28.76 FPS** with two, and **28.87 FPS**
with two hands and smoothing. Smoothing slightly improved stability without
noticeable lag. Phase 2.5 later reached 38.77 FPS with native Win32 polling in
the owner's hardware comparison; Phase 3.2's recognition accuracy/FPS are unverified.
The camera's ~60 FPS capture rate does not guarantee 60 FPS inference.
Low light, occlusion, framing and motion can affect detection.

## Performance and failure handling

VIDEO calls are synchronous. Every frame receives a timestamp derived from
`time.perf_counter()`, forced strictly upward by at least one millisecond when
timestamps collide. The timestamp is not derived from requested camera FPS.

The application counts completed capture/conversion/inference/preview/event-pump
iterations over roughly two-second windows. FPS initially shows `--`. Logs give
the end-to-end rate and a final average. On exit, profiling reports mean, p50,
p95, p99 and maximum times for camera reads, inference resize, BGR-to-RGB,
MediaPipe image wrapping, inference, smoothing, preview resize, drawing/labels, text, imshow,
GUI events (`pollKey` or `waitKey`), combined GUI time, processing, read-to-completion
time and completed-frame interval. Means/maxima cover all measured samples;
percentiles use the most recent 8192 per stage. Interactive runs include startup;
`--benchmark` excludes warm-up. Setup/cleanup and JSON writing are excluded.

Every completed roughly two-second FPS window is compared with the owner's
35.81 FPS Phase 2.1 reference. Below 75% of that rate (about **26.86 FPS**), a
significant-decrease warning is logged when entering a slow period. Profiling
details are logged once on exit. Benchmark measurement has no periodic logging.
The reference is not a guaranteed target or a sensor measurement. Startup,
redetection and two-hand inference may make a window slower; repeat the test
under comparable conditions before drawing conclusions. Two hands may cost more
than one, and no two-hand FPS target is assumed.

No processing threads or asynchronous capture are introduced. If inference is
slow, this synchronous loop can receive buffered frames and accumulate latency;
this milestone does not attempt buffer management or dropped-frame optimization.
Driver read calls can block; cleanup occurs once they return. Requested modes
and positive driver-reported FPS do not establish actual throughput.
Buffer reuse reduces Python-side allocations; it does not control camera buffers
or establish sensor-to-display latency. See the buffering discussion in PERFORMANCE.md.

Run one full-resolution benchmark (30 measured seconds after 3 seconds of warm-up):

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --inference-resolution full --warmup 3 --duration 30 --report hand_tracking\benchmarks\full-run1.json
```

The normal preview and Q/H controls remain active. Reports include actual capture
and inference dimensions, detected-hand counts, FPS, timing percentiles, requested
settings and driver readbacks. Phase 2.5 also adds per-detected-hand-count timing
groups, effective GUI mode and whole-process CPU observations. Report directories
are created automatically and ignored by Git; existing reports are protected from overwrite. Use a fresh filename
for each run. A run stopped with Q is marked `stopped`; Ctrl+C marks `interrupted`.
Only a benchmark reaching its requested duration is marked `completed`.

### Phase 2.5 comparisons

`--gui-mode auto` (default) uses one `pollKey()` call per processed frame only
when OpenCV reports the native `WIN32` UI backend and exposes that API.
`--gui-mode waitkey` retains the earlier `waitKey(1)` path. `--gui-mode pollkey`
requests native polling explicitly; an unavailable native implementation or a
runtime polling error falls back to `waitKey(1)` with a warning. Other UI backends
use `waitKey(1)`. No spin loop, timer-resolution changes or extra sleeps are added.
Q/H and window close remain active in both preview modes.

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --gui-mode waitkey --warmup 3 --duration 30 --report hand_tracking\benchmarks\waitkey-two-01.json
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --gui-mode auto --warmup 3 --duration 30 --report hand_tracking\benchmarks\auto-two-01.json
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --headless --warmup 3 --duration 30 --report hand_tracking\benchmarks\headless-two-01.json
```

Run these sequentially under the same conditions, first with zero hands, then one,
then two; choose a fresh report name each time. Headless tracking includes capture,
input preparation, the real model, smoothing and profiling; it skips all preview,
landmark drawing and GUI calls. It requires `--benchmark`, exits after the duration,
and can be interrupted with Ctrl+C; Q/H and raw comparison overlays require a
preview. Headless FPS is a diagnostic comparison, never preview/display FPS.
See [PERFORMANCE.md](PERFORMANCE.md#repeatable-phase-25-hardware-validation) for
the complete comparison loop, report columns, CPU interpretation and quality checks.

A missing/empty model produces setup instructions before opening the camera.
Invalid model bundles, dependency errors, failed camera opens and failed reads
produce errors and release acquired resources. MediaPipe may print native
feedback-tensor or projection warnings; the synthetic smoke test still completed.

## Reproduce dependencies

Verified in the existing **Python 3.13.7, Windows x64** virtual environment:

- `mediapipe==1.1.1`
- `numpy==2.5.4` (unchanged)
- `opencv-contrib-python==5.0.0.93` (same OpenCV version as Phase 1)

MediaPipe requires the contrib OpenCV distribution. It replaces `opencv-python`
to avoid installing two packages that both provide `cv2`. Other pinned packages
in the root `requirements.txt` are MediaPipe's resolved dependencies, including
Matplotlib and sounddevice; the tracker does not implement plotting or audio.
The requirements file also pins transitive versions to reproduce this environment.

For another checkout with an existing Phase 1 environment, remove the old OpenCV
provider first, then install the pinned requirements. These steps are already
complete in the current environment:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y opencv-python
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

## Reproduce model setup

The official Google Hand Landmarker float16 **version 1** bundle is stored at
`hand_tracking/models/hand_landmarker.task` (about 7.8 MB). The entire models
directory is ignored by Git. The application uses this local file and never
downloads a model automatically.

Run this once in another checkout, or to verify the existing local copy:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.download_model
```

The setup command downloads from the versioned Google URL below, verifies SHA-256
before saving, and verifies an existing copy without overwriting it. On a checksum
mismatch, inspect/remove the incorrect local file and rerun setup. Network errors
leave the application without a model and produce a clear setup error.

- [Official versioned model bundle](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task)
- SHA-256: `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`
- [Google's Hand Landmarker Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python)
- [Google's model overview](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/index)

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s camera -v
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

The hand-tracking tests cover arguments, timestamps, FPS, RGB conversion,
landmark scaling/topology, 0/1/2-hand rendering, help, VIDEO/CPU/two-hand options,
handedness pairing, order changes, duplicate/missing predictions, disappearing
hands, invalid detections, performance warnings, model checksums, inference sizes,
buffer reuse, percentile calculations, warm-up exclusion, JSON reports, EMA
arithmetic, independent handedness histories, motion bypass, loss/reappearance,
ambiguous identity, reset rules and error/cleanup paths with mocked cameras.
Phase 2.5 adds checks for native polling, guarded fallbacks, Q/H/window close,
headless execution without GUI calls, per-hand-count profiles, CPU calculations,
new CLI constraints and warm-up exclusion.
The original Phase 3.2 baseline was **134 tests**. The targeted POINTING
calibration adds 14 focused geometry/diagnostic regressions; all previous tests
continue to run, including Phase 1 camera tests.
Phase 3.2 completed with 148 passing tests (56 gesture, 76 tracking, 16 camera).
Phase 3.3 completed with 174 passing tests and Phase 3.4 with 214. Phase 3.5 adds
39 swipe regressions: **253 tests pass** (135 gesture, 102 tracking, 16 camera),
including all earlier tests without weakening their expectations.
Phase 3.2 coverage includes static labels, detection order and loss, EMA input,
malformed-hand fallback, native polling/Q/H and gesture profiling/warm-up/counts.
Phase 1 tests cover
the preserved camera tester. A separate smoke check also initialized the actual
downloaded model and processed two blank 1080p RGB images in VIDEO mode, returning
0 hands for both. These checks do not establish real-world detection quality.
Phase 2.5 also loaded the real installed model and completed a timed headless run
with blank 1920×1080 synthetic frames, no GUI calls and a simulated camera that
was released on exit. It returned no hands and produced a JSON-serializable
report; this verifies integration and model loading, not hardware performance.
A second synthetic run exercised the real Win32 preview/event pump with the real
model, selected native polling automatically, completed the timed benchmark and
destroyed its window on exit. Physical keyboard/window responsiveness and live
tracking quality still require the owner's webcam checks.

Suggested commit after local hardware testing:

```text
feat(gestures): recognize static hand poses with unknown fallback
```

The current milestone stops at Phase 3.2. No automatic commit or push is made.
Use local hardware results to decide
the next milestone.
