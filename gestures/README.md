# Phase 3.4: Gesture states and events

This package provides the Phase 3.1 landmark geometry foundation and Phase 3.2
deterministic static rules: **OPEN_PALM, FIST, POINTING, UNKNOWN**. Feature
extraction stays separate from classification. The existing hand-tracking
preview can show per-hand gesture labels with `--gestures`; recognition is
opt-in. The owner has verified static recognition at approximately 36 FPS after
POINTING calibration; occasional backward-rotation POINTING/FIST ambiguity is
unchanged. The static classifier imports no camera, GUI, MediaPipe or desktop-control
code and retains no motion history. Phase 3.3 adds a separate pinch lifecycle;
Phase 3.4 adds optional state management and event arbitration above both raw
recognizers. No additional model, threads or gesture-triggered actions are added.

The package uses only Python's standard library (Python 3.11+; the existing
environment is Python 3.13.7). No requirements changes or installations are needed.

## Modules

| File | Responsibility |
| --- | --- |
| `models.py` | Official landmark indices; immutable validated landmarks, predictions, hands, frame observations and image dimensions |
| `landmarks.py` | Snapshot adapter for raw/EMA Tasks results; explicit image-coordinate conversion |
| `geometry.py` | Stateless distances, vectors, unit directions, dot products, angles, palm scale and distance ratios |
| `features.py` | Named per-finger/per-hand features and the lightweight `FrameFeatures` consumer contract |
| `static_gestures.py` | Typed gesture/result/threshold records and stateless conservative rules |
| `pinch.py` | Cached proximity measurement, typed pinch results and conservative per-side hysteresis/recovery |
| `association.py` | Shared existing unique/confident side and overlapping-hand gates; no persistent IDs |
| `events.py` | Immutable event, metadata and current-state snapshots; reuses static Gesture identifiers plus PINCH |
| `arbitration.py` | Small input precedence policy; preserves raw observations |
| `state_machine.py` | Per-hand timed confirmation, per-gesture cooldowns, pinch-event admission and cancellation |
| `__init__.py` | Public observation/feature/adapter exports |
| `tests/` | Synthetic fixtures and hardware-independent model, adapter, geometry and feature tests |

Existing tracking helpers are display-oriented and import OpenCV/NumPy. The new
models add validation, metadata and immutable snapshots without importing that
rendering stack. The adapter also accepts the existing EMA `DisplayLandmark`
objects structurally; neither the tracker nor its smoothing code is refactored.

## Phase 3.4: stabilized gesture events

The optional manager converts existing recognition results into a **single resolved
intent stream per hand**, while preserving raw static classifications and all
Phase 3.3 pinch statuses. It does not rerun inference, extract geometry again,
reclassify poses, change thresholds or call OS input APIs. The engine is standard
library Python and is independent of OpenCV, MediaPipe and Windows.

### Launch and diagnostics on Windows

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
# Original tracking; no recognition or state engine
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker

# Raw static + pinch channels, without generalized state management
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch

# Static states only
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-states

# Pinch events only; open fingers first to arm
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch --no-gestures --gesture-states

# Both recognition channels, with resolved states and events
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states

# Explicit event diagnostics; numeric pinch diagnostics are independently optional
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --gesture-event-debug --pinch-debug

# Tune time intervals without editing source; 0 update interval disables UPDATED
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --gesture-activation-ms 100 --gesture-transition-ms 60 --gesture-cooldown-ms 150 --gesture-update-ms 0
```

`--gesture-states` defaults off and **requires `--gestures` and/or `--pinch`**;
it never silently enables recognition. `--gesture-event-debug` requires states.
Existing combinations including `--no-gestures --pinch`, Q/H, MSMF 1080p capture,
full inference, EMA alpha 0.75 and native Win32 polling remain available.

The original wrist label remains raw, e.g. `Left - POINTING | Pinch: HELD`.
A compact white-on-black row shows state, candidate (if any), confirmed intent
and last event. Last events are historical display records, not new emissions;
they are cleared when association becomes unsafe. A brief transition can be hard
to see at camera speed; use the optional event log to inspect exact timestamps.
Logging shows side, gesture, event type, monotonic elapsed ms and reason, e.g.
`Left | PINCH | GESTURE_CANCELED | ... | tracking_lost (former association)`.
No per-frame state logs, images or video are recorded. Event logging is off by
default; moving pinches can produce bounded useful UPDATED diagnostics when on.

### Time model, transitions and defaults

Every operation uses the existing frame timestamp in monotonic elapsed integer
milliseconds. No frame-count assumptions or wall-clock scheduling are introduced.

| Setting / CLI | Default | Policy |
| --- | ---: | --- |
| `--gesture-activation-ms` | 100 | Require one unchanged supported static candidate for a short stable interval |
| `--gesture-transition-ms` | 60 | Require a different supported static pose to persist before ending the old pose |
| `--gesture-cooldown-ms` | 150 | Block reactivation of the same static gesture for this hand after END/CANCEL |
| `--gesture-update-ms` | 250 | Minimum interval between useful pinch distance UPDATED events; 0 disables them |

All four intervals must be integers in **[0, 5000] ms**. Zero activation/transition/
cooldown means immediate/no delay respectively. Defaults are initial tuning
choices: 100 ms rejects brief classifications, 60 ms tolerates short recognized
pose changes, and 150 ms limits immediate repeat activations without imposing a
global lockout. They still add deliberate static interaction latency; tune with
your webcam. There is **no added activation/release delay or cooldown for PINCH**.

| Situation | State / event behavior |
| --- | --- |
| No confirmed gesture | IDLE; UNKNOWN never qualifies |
| Valid supported pose appears | CANDIDATE; changing it restarts its clock |
| Candidate stable for activation interval | ACTIVE; emit one GESTURE_STARTED at the confirming observation's timestamp |
| Matching ACTIVE observations | Remain ACTIVE; no repeated STARTED or static UPDATED events |
| Brief different supported pose | Keep old ACTIVE until transition interval; returning to it clears the pending replacement |
| Stable different supported pose | GESTURE_ENDED for old pose, then confirm the new candidate using elapsed time from its first changed frame |
| UNKNOWN / conflicting rules / invalid input | Immediately GESTURE_CANCELED for an active pose; discard an unconfirmed candidate without an event |
| Same static gesture returns during its cooldown | COOLDOWN; no candidate time accrues until its timer expires |
| Pinch STARTED with observed prior OPEN/RELEASED | Immediately ACTIVE PINCH and one GESTURE_STARTED |
| Pinch HELD | Maintain already-active PINCH; never create a missing STARTED |
| Pinch RELEASED | One GESTURE_ENDED for active PINCH; static candidates may form again |
| Pinch UNAVAILABLE / missing release transition | Cancel active intent; no intentional release is invented |

Cooldown is a **per-static-gesture, per-hand timer**, not a global blocking state.
The displayed state is COOLDOWN only when the currently selected static gesture
is blocked; other static gestures can form candidates, and PINCH remains immediate.
UNKNOWN displays IDLE even while a past gesture's cooldown timer remains. Terminal
static events carry COOLDOWN as their post-termination phase when configured;
the same frame may display another candidate/IDLE after arbitration.

Example with defaults: POINTING active, FIST first seen at t=130 ms, still valid
at t=190: end POINTING at 190 (60 ms transition). Confirm FIST at the first valid
observation at/after t=230 (100 ms since it first appeared). With sparse frames,
events occur on the next confirming observation, never retroactively on a timer.
Exact activation/transition/cooldown deadlines are inclusive. A gap **>250 ms**
is tracking loss rather than evidence that an unseen pose remained stable.

### Typed events, arbitration and pinch recovery

`GestureEvent` is frozen and contains a gesture identifier, `EventType`, timestamp,
`HandSide`, relevant state and frozen `EventMetadata` (reason, optional normalized
pinch distance and whether the association is current). Static identifiers reuse
the existing `Gesture` enum; PINCH is an event-only typed literal, **not** a new
static class. UNKNOWN cannot be constructed as an actionable event identifier.

- **GESTURE_STARTED:** emitted once on confirmation/admitted pinch STARTED.
- **GESTURE_UPDATED:** only for active pinch distance changing by at least 0.02
  palm units since the last emitted distance, and after the update interval.
  This is metadata, never another activation. Unchanged holds produce no updates.
- **GESTURE_ENDED:** stable known static replacement or a deliberate pinch RELEASED.
- **GESTURE_CANCELED:** uncertainty, invalid input, lost association, pinch
  precedence or reset/shutdown. Consumers must clear prior intent, not infer release.

PINCH has precedence over all static classes for the **resolved intent channel**.
Its STARTED cancels any active static intent before starting PINCH. HELD suppresses
static starts even when an earlier STARTED was not admitted. UNKNOWN does not
override an active valid pinch. When pinch is enabled but UNAVAILABLE, static
intents are also suppressed/canceled; uncertain high-priority input does not fall
through to a possibly contradictory static action intent. Raw results are untouched.

The Phase 3.3 detector retains its existing distance hysteresis and rearming.
The manager observes its OPEN/RELEASED before admitting a fresh STARTED. This
adds no time delay to normal valid transitions, but an orphan STARTED or HELD
after unsafe recovery cannot fabricate activation. Reopen to rearm both layers.
Duplicate STARTED does not restart an active pinch. A missed RELEASED followed
by OPEN cancels instead of claiming deliberate completion.

Events are returned in `StateFrame.events`; current snapshots follow detection
slots solely for rendering. Loss cancellations precede current-hand events;
within each group, side order is fixed. Identical ordered observations and
timestamps produce identical outputs. No global bus, callbacks, unbounded event
history, cooldown shared across hands, probability score or action dispatch exists.
Future desktop controls can consume these immutable records independently;
future swipe recognition would extend the identifier/input adapter and precedence
policy rather than coupling this engine to OS APIs. No swipe logic is implemented.

### Association, loss and invalid time

Only unique confident single-category Left/Right predictions (score >=0.8) receive
state; these are **predicted sides, not persistent identities**. Detection order
does not transfer history. Shared Phase 3.3 overlap/side helpers retain the same
gates and do not change pinch lifecycle rules. The manager checks cached landmark
geometry/continuity, not another MediaPipe inference or feature extraction.

- Missing hand: immediately remove that history and cancel its active intent.
  The other reliable hand continues independently. Empty frames retain no states.
- Uncertain/unknown/duplicate labels or overlapping boxes/close wrists: cancel
  both histories conservatively. No activation/update is emitted for an unsafe hand.
- Invalid geometry/channel data: cancel the affected history. Unknown identity
  can invalidate both. Classifications/pinch results must match the current
  observation's handedness metadata, slot count and timestamp.
- Wrist jump >0.10 image-width common-axis units: cancel that side and skip
  the discontinuous observation. Capture dimension changes or >250 ms frame
  gaps cancel all and skip activation for that observation.
- Reacquired static poses begin fresh candidates; old timers/events never activate
  them. Reacquired closed pinches require an observed separation first.
- Missing/invalid/duplicate/backward timestamps cancel at the **last accepted
  timestamp** (0 before any valid frame). No wall-clock timestamp is substituted;
  invalid input does not lower the timestamp watermark. New time must exceed it.
- Explicit reset/shutdown cancels remaining active intents at the last accepted
  timestamp. These are cleanup events, not an intentional release.

Loss/ambiguity cancellations reference the **former reliable side** and carry
`association_current=False`; they do not assert that this hand is still visible.
The manager retains at most two histories, three static cooldown timers per side
and one latest event per side. Confident side swaps that escape the simple gates
remain a limitation. Overlap may interrupt real gestures; conservative cancellation
is preferred to speculative matching. Underlying backward-rotation static ambiguity
and projected pinch proximity vs physical contact are unchanged.

### Manual acceptance and benchmarking

1. Use static-only states with event diagnostics. Briefly flash POINTING (<100 ms),
   then hold it: expect CANDIDATE then one STARTED; prolonged holding must not
   repeat it. Repeat OPEN_PALM and FIST, including variable movement/lighting.
2. Change between known poses: expect END after transition stability and a new
   START after confirmation. Show UNKNOWN/unsupported geometry: expect immediate
   CANCEL, never UNKNOWN START. Return rapidly to check cooldown/reconfirmation.
3. With pinch states, open first, approach, hold and separate: one PINCH START,
   optional bounded distance UPDATE, one END. Holding never repeats START.
4. Enable both channels. Raw POINTING/FIST/etc. must remain visible while PINCH
   takes precedence; static CANCEL precedes PINCH START. Release and form a
   static candidate again; no contradictory active intents should coexist per hand.
5. Repeat with both hands independently, change detection order, lose one/both,
   cross/overlap and reacquire closed. Loss must CANCEL rather than END; reopen
   before a new pinch starts. Static reacquisition requires fresh confirmation.
6. Verify Q/H, labels/colors, responsiveness and FPS with diagnostics disabled.
   Test both the original flags without states and the new opt-in combinations.

Run these matched preview benchmarks **sequentially** with the same hand count,
movement, lighting and capture settings. Existing reports exclude warm-up and
refuse overwrite; this directory is already ignored:

```powershell
$stateRun = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\raw_${stateRun}.json"
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\states_${stateRun}.json"
```

`state_management` profiles validation, continuity, transitions and event creation,
including zero-hand frames. It appears in existing overall/per-hand-count timings.
Overlay work remains in drawing; optional logs are included in loop FPS but outside
the state-engine timer. JSON `gesture_states` records settings, measured state/event
counts and separate shutdown events. State counters count observed hands per frame;
event counters count emissions by type/identifier. Counters exclude warm-up, while
state continuity runs during it. Diagnostics log live events including warm-up;
shutdown cancellations are separately reported and never mixed into measured counts.
Reports are summaries, not an event journal or proof of physical hand identity.

### Validation and measured synthetic cost

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

All **214 tests pass**: 105 gesture, 93 tracking and 16 camera tests. All 174
previous tests remain passing without altered expectations; 40 new tests cover
confirmation/rejection, known changes/UNKNOWN, cooldown boundaries, variable FPS,
immutable deterministic events, arbitration, simultaneous pinches, rearming/loss,
uncertainty, order changes, invalid time/geometry/channel alignment, reset, CLI,
overlays, native polling/Q/H, shared extraction and benchmark/report behavior.
The 32 engine tests also pass with `python -S` without third-party packages.

An interleaved synthetic two-hand comparison used the existing venv, five repeated
approach/release poses, 100 warm-up + 1000 measured observations per configuration,
alternating configuration order and disabled profile collection. All values are
ms per two-hand observation; no camera, inference, smoothing, GUI or logs:

| Work | Mean | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Raw static + pinch recognition bridge | 1.268 | 1.065 | 2.372 | 3.834 |
| Same bridge with state management | 1.351 | 1.111 | 2.471 | 4.283 |
| State manager portion | 0.044 | 0.036 | 0.085 | 0.174 |

Host scheduling affects these samples; they do not establish camera FPS or physical
accuracy. Approximately 35+ FPS against the owner's ~36 FPS static baseline is a
target for local testing, not a verified result. Default static confirmation adds
intentional time latency even when processing overhead is small. No new dependencies,
models, threads, frame copies or OS controls are introduced. Stop for owner webcam
acceptance before the next milestone. Suggested commit after acceptance:
`feat(gestures): add gesture state management and event arbitration`.

## Phase 3.3: real-time pinch proximity

Pinch is a **separate opt-in channel**, not a static PINCH class. Static
OPEN_PALM/FIST/POINTING/UNKNOWN rules and thresholds are unchanged. For example,
`Left - UNKNOWN | Pinch: HELD` is a valid combination. This raw channel itself adds
no generalized state/arbitration; opt-in Phase 3.4 handles those above recognition.
No desktop controls, swipe detection or actions are implemented. Physical pinch
accuracy and current FPS still require owner testing.

### Geometry and starting thresholds

Use **THUMB_TIP (4)** and **INDEX_FINGER_TIP (8)** from the current raw/EMA
observation. Phase 3.1 already computes their `distance_2d` and `thumb_index_ratio`:

```text
common-axis point = (x, y * image_height / image_width)
palm scale = (distance(wrist, middle MCP) + distance(index MCP, pinky MCP)) / 2
pinch distance = distance(thumb tip, index tip) / palm scale
```

Both numerator and denominator use the same aspect-correct 2D space. There are
no pixel-distance thresholds. Uniform scale/in-plane rotation do not change the
ratio; out-of-plane rotation/foreshortening can change it. Non-finite or missing
features, absent image dimensions, inconsistent cached ratios and zero/negligible
palm scale give an invalid measurement, never an assumed OPEN state.

Defaults are **activation 0.25**, **release 0.40 palm units**. These use a small
fraction of palm size for activation and a 0.15-unit hysteresis band to reduce
boundary chatter. They are conservative initial heuristics, **not physically
calibrated thresholds or proof of contact**. Valid CLI/configuration values must
satisfy `0 < activation < release <= 2`; the upper bound excludes thresholds
spanning several palm sizes, which would no longer describe near-fingertip proximity.
Projected 2D overlap can appear close even when fingers are separated in depth.

### Narrow pinch lifecycle and recovery

| Previous state | Current observation | Result |
| --- | --- | --- |
| Startup / reset / reacquisition | Distance above release | OPEN, armed |
| Startup / reset / reacquisition | Distance at/below release | UNAVAILABLE, `open_to_rearm` |
| OPEN / RELEASED | Distance below activation | STARTED, once |
| OPEN / RELEASED | Distance at/above activation | OPEN |
| STARTED / HELD | Distance at/below release | HELD |
| STARTED / HELD | Distance above release | RELEASED, once; then OPEN on the next separated frame |
| Any | Invalid geometry or unreliable identity/time | UNAVAILABLE, history invalidated |
| Any | No hand observation | No result/overlay for that hand; history removed |

STARTED and RELEASED are one-frame observations, not latched labels or actions.
At exact thresholds, the existing active/inactive state is retained. There is no
debouncing, cooldown or generalized gesture history. A hand already closed when
the application starts must **separate beyond release once before it can start**.
After loss/ambiguity, an already-closed returning hand likewise remains
UNAVAILABLE until observed open. Tracking loss never fabricates intentional
RELEASED or stale STARTED events.

State association uses only unique Left/Right predictions with one category and
score **at least 0.8** in consecutive frames. Detection order is never an identity.
Unknown/uncertain/duplicate/conflicting labels invalidate both histories. Missing
hands are removed immediately; invalid geometry invalidates the affected history.
A malformed slot with unknown identity invalidates both rather than assigning it.
Close wrists (<0.10 in image-width common-axis units), overlapping hand landmark
bounding boxes, or conflicting image sizes also invalidate both. A wrist jump
>0.10 invalidates that side rather than guessing a match. These are conservative
continuity gates, not pixel pinch thresholds or persistent tracking algorithms.
Histories reset on a timestamp gap >250 ms or a capture dimension change. Invalid
timestamps raise ValueError after clearing state; duplicate/backward timestamps
produce UNAVAILABLE and clear history until time passes the last accepted timestamp.

Left/Right are predictions, **not guaranteed persistent identities**. Crossing,
occlusion and overlapping boxes may interrupt a real pinch. A confident label
swap or missed identity change that bypasses these simple gates is still possible.
No speculative matching is attempted. This lifecycle is preparation for later
controls; it does not dispatch any input actions.

### Exact PowerShell commands

Run from `C:\Users\Darsh\VisionControl` using the existing environment/model:

```powershell
# Normal hand tracking; both recognition channels off
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker

# Pinch alone (also works with explicit --no-gestures)
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch

# Numeric on-screen diagnostics and adjustable starter thresholds
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --pinch --pinch-debug --pinch-activation 0.25 --pinch-release 0.40

# Independent static gesture labels and pinch together
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch

# Raw comparison, with all other settings unchanged
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --pinch-debug --no-smoothing
```

`--pinch` defaults off and does not implicitly enable `--gestures`. `--pinch-debug`
requires `--pinch`; it adds one compact row near each wrist with current `d`,
activation/release bounds, geometry `valid=yes/no` and any reset/rearm reason.
Geometry can be valid while state is UNAVAILABLE due to identity or rearming.
The main wrist label always shows pinch status when enabled. Thumb/index tips and
their connecting line use **gray OPEN, yellow STARTED, green HELD, orange RELEASED,
purple UNAVAILABLE**. Skeleton side colors and static labels remain unchanged.
Brief transitions can be hard to see at normal FPS; they are deliberately not held.
Diagnostics produce no per-frame console logs and are off by default. Q quits;
H toggles existing help. MSMF, full inference, EMA alpha 0.75 and native polling
are preserved. Raw comparison markers do not change recognition input.

### Manual calibration and acceptance checklist

1. Use `--pinch-debug`, show one hand and **open fingers first**. Hold separated,
   approaching, touching, held and releasing poses for several seconds each.
   Watch `d`, validity, state and `open_to_rearm`. Repeat with each hand.
2. Note the largest stable ratio during your intended pinch and the smallest
   stable ratio when clearly released. If those ranges overlap, improve lighting
   or pose first. Set activation slightly above the intended-pinch range and
   release clearly above activation but below the separated range. If overlap
   persists, no single threshold pair can reliably separate those views.
3. Hover near both thresholds: holding must remain HELD without repeated STARTED;
   deliberate separation gives RELEASED once, then OPEN. One-frame transitions
   may flash briefly. A timed report's `pinch.status_counts` can help check the
   total transitions in a controlled sequence; it is not a per-hand event log.
4. Repeat at different camera distances, in-plane rotations and moderate hand
   tilts; verify that projected overlap without physical contact remains a known
   limitation. Backward-rotation static gesture ambiguity is outside this phase.
5. Pinch both hands independently and together, change detection order, cross
   them, and leave/reenter the frame. Overlap/loss must clear active state without
   a deliberate RELEASED event; closed reacquisition must require opening first.
6. Enable `--gestures --pinch`, repeat open palm/fist/pointing/unsupported poses,
   check skeletons, Q/H, responsiveness and FPS. Use the same hand count, motion,
   lighting and capture settings for performance comparisons; turn debug off.

For a matched preview comparison (run **sequentially**, close each run before
the next), reports exclude 3 seconds of warm-up and refuse existing paths:

```powershell
$pinchRun = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\static_${pinchRun}.json"
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\pinch_${pinchRun}.json"
```

Reports use the already ignored local benchmarks directory; no camera images or
model assets are added. Compare application FPS, existing end-to-end/processing
timings, rendering and `pinch_processing` mean/p95/p99. Capture/driver frame age
is unknown. Approximately 35+ FPS is a target, not a measured result here.

### Tests and synthetic overhead

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

The **Phase 3.3 baseline** was 174 passing tests: 73 gesture, 85 tracking and 16 camera tests.
All 148 previous tests remain unchanged and passing; 26 new tests cover geometry,
articulated approach/hold/release, hysteresis/equality, rearming, loss, time and
identity checks, simultaneous hands/order changes, EMA input, shared extraction,
unchanged static results/UNKNOWN, rendering, CLI and headless/warm-up/native GUI.

Recognition shares the current smoothed snapshot and cached Phase 3.1 features.
With both channels on, each detected hand is adapted/extracted once. Static
feature timing remains `gesture_features`; pinch-only uses `pinch_features`.
`pinch_processing` separately includes measurement validation/continuity/state;
pinch overlays are included in existing drawing timing. Both new stages appear
in per-hand-count profiles. JSON records thresholds, mode, input and status counts
for measured frames only; no inference, threads, frame copies or dependencies added.

An interleaved synthetic comparison used two articulated hands, five repeating
approach/release poses, 100 warm-up and 1000 measured samples per configuration,
alternating configuration order, existing venv and disabled Profile collection.
It excluded camera, inference, smoothing and rendering. All values below are ms
per two-hand observation; scheduling noise affects tail values:

| Stage | Mean | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Static bridge (adaptation + cached features + static rules) | 1.479 | 1.042 | 3.906 | 5.692 |
| Static bridge + shared-feature pinch | 1.555 | 1.112 | 4.186 | 6.060 |
| Pinch portion within combined run | 0.105 | 0.072 | 0.279 | 0.405 |

These host microbenchmarks establish neither real camera FPS nor physical
accuracy. The owner's previous approximately 36 FPS static baseline is the
comparison target for the next webcam run. New pinch defaults remain uncalibrated.
Suggested commit after hardware acceptance:
`feat(gestures): add real-time pinch detection with hysteresis`.

The remaining sections document the existing stateless classifier and earlier
milestone measurements; Phase 3.3 does not retune those rules.

## Run static recognition on Windows

From `C:\Users\Darsh\VisionControl` in PowerShell, use the existing environment/model:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --no-gestures
```

`--gestures` enables recognition; `--no-gestures` disables it (the default).
All existing arguments remain available. With recognition enabled, capture
remains 1080p60/MSMF, inference defaults to full, EMA defaults to alpha 0.75,
and native Win32 polling, skeleton colors, Left/Right and Q/H remain active.
Labels use ASCII `Left - OPEN_PALM` / `Right - POINTING` on the existing black
wrist-label background so OpenCV's font can render every character.

## Conservative recognition rules

### Targeted POINTING calibration and diagnostics

The owner physically tested the original Phase 3.2 implementation: OPEN_PALM,
FIST, UNKNOWN, two-hand independence, recovery and performance passed; POINTING
was intermittent. Recognition ran at approximately 36 FPS versus the earlier
38.77 FPS tracking baseline. The bounded calibration below was initially validated
synthetically; the owner subsequently confirmed the static gestures work well
after calibration. Occasional backward-rotation POINTING/FIST ambiguity remains
outside Phase 3.3. New pinch accuracy/performance still need webcam validation.

Inspection showed POINTING reused the strict FIST curl test. Articulated
synthetic relaxed curls had PIP 90–100°, DIP 110–115° and straightness 0.47–0.56,
all passing the strict curl gates, but tip-to-wrist/palm ratios 1.40–1.58 exceeded
1.25 and caused UNKNOWN. A slightly bent synthetic index with PIP 150–152°
also missed the original 155° extension gate. These demonstrate concrete failure
paths, **not proof of which gate failed on the owner's real hand**. Debug samples
are needed to establish the actual camera failure.

The calibration changes only these POINTING gates:

- Index PIP minimum: **150°** instead of 155°. Index DIP ≥145°, straightness
  ≥0.88 and tip/wrist ≥1.15 remain required; a generally bent index does not qualify.
- Middle/ring/pinky tip/wrist maximum: **1.65** instead of 1.25. Their PIP ≤110°,
  DIP ≤160° and straightness ≤0.75 remain required. This allows tips further from
  the wrist while preserving clear geometric evidence of curling.
- Each of those fingers must also lie at least **0.25 palm-scale units closer
  to the wrist than the index tip**. This additional separation guard rejects a
  short/insufficiently protruding index and limits partially open false positives.

OPEN_PALM and the strict FIST curl thresholds below are unchanged. Peace signs
and three-finger poses still fail the curl requirements. Broader partial curls
and ambiguous/invalid features remain UNKNOWN. There is also one narrow FIST
exclusion required by the unsupported-pose checklist: if only the thumb is
clearly extended (its MCP/IP angles and straightness meet the strict extension
limits, with tip/wrist ≥1.35), the result is UNKNOWN instead of FIST. The original
FIST rule ignored the thumb and could accept this thumbs-up-like geometry.
Wrapped/relaxed-thumb fists retain their original rule; this exclusion neither
adds a thumbs-up class nor restricts natural thumb posture during POINTING.

Run normal recognition or enable sampled numeric diagnostics:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug
```

`--gesture-debug` requires `--gestures`, is disabled by default, and samples at
most once every **two seconds** using the existing frame timestamps. Every frame
is still classified immediately. No debouncing, label hold or cooldown is added.
When inactive, no log sampler or diagnostic-check records are constructed.
Sampled `GestureResult.pointing_checks` use the same comparisons as classification;
console output shows each finger's angles, straightness, normalized tip/wrist,
index separation, PASS/FAIL bounds, classification/reason and POINTING blockers.
Missing/non-finite values show INVALID; invalid input/palm scale is identified.
Frame slot numbers are local positions, not persistent hand identities. Logs
contain numeric features and labels, **not camera images or raw x/y/z coordinates**.

To save a readable local log (the directory is already ignored by Git):

```powershell
New-Item -ItemType Directory -Force -Path .\hand_tracking\benchmarks | Out-Null
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug 2>&1 | Tee-Object -FilePath "hand_tracking\benchmarks\pointing-debug_${runStamp}.txt"
```

Hold one hand in natural pointing for 4–6 seconds, then slightly bend the index
and relax the other fingers. Repeat with the other hand, different distances and
in-plane rotations. Note which named bounds fail during UNKNOWN. Then test peace
signs, three fingers, thumbs-up, partially open hands, open palms and ordinary
fists. Test both hands simultaneously, change their order, and leave/reenter the
frame. Share several failing and passing numeric samples with a short description
of the intended pose before further tuning. No images are needed.

Use debug **off** for matched FPS comparisons: optional console logging can
affect responsiveness. Existing profiling includes calibration work; JSON records
the additional thresholds and whether debugging was enabled. A sequential
cached-feature microbenchmark (100 warm-up/2000 measured two-hand iterations,
no camera, feature extraction or GUI) measured rule means/p95 of 0.021/0.035 ms
before and 0.053/0.107 ms after calibration with debug off. This is an approximately
0.032 ms mean host-rule increase, not a webcam FPS measurement or accuracy gain.
The target remains the owner's approximate 36 FPS, pending local re-testing.

The classifier consumes `HandFeatures`; geometry is computed once using the
Phase 3.1 utilities with the **actual capture aspect ratio**. Every required long
finger must have valid measurements. The four long fingers are index, middle,
ring and pinky. A relaxed/tucked thumb is allowed; four clearly extended long
fingers count as most fingers extended. The table is the original **strict**
extended/curl policy for OPEN_PALM and FIST; POINTING uses the bounded exceptions
above, and FIST excludes clear thumb-only extension as described there.

| Long-finger condition | Clearly extended | Clearly curled |
| --- | ---: | ---: |
| PIP interior angle | at least 155° | at most 110° |
| DIP interior angle | at least 145° | at most 160° |
| Base-to-tip chord / chain length | at least 0.88 | at most 0.75 |
| Tip-to-wrist distance / palm scale | at least 1.15 | at most 1.25 |

All four measurements must meet the relevant column. These initial engineering
thresholds allow modest bending of extended fingers, require multiple signs of
curling and leave a gap for partial poses. They are **not learned or calibrated
from real hands**. Articulated synthetic fixtures test geometry and invariance;
webcam results must determine whether future tuning is appropriate. They are
named in the frozen `StaticThresholds` record for explicit Python configuration;
the live preview uses `DEFAULT_THRESHOLDS`, also recorded in JSON. No extra CLI
threshold knobs are introduced in this milestone.

- `OPEN_PALM`: all four long fingers clearly extended; thumb may be relaxed.
- `FIST`: all four long fingers strictly curled, without clear thumb-only extension.
- `POINTING`: index clearly extended, the other three geometrically curled with
  the POINTING-specific wrist-distance tolerance and index-separation guard.
- `UNKNOWN`: no rule matches, multiple rules match, or required features are
  missing, non-finite, out of range, duplicated or degenerate. A valid but
  unsupported finger combination also stays UNKNOWN. Invalid thumb-only
  features do not invalidate otherwise sufficient long-finger geometry.

There is no rule priority that forces a conflicting pose into a class.
`GestureResult` contains the enum, frame timestamp, available handedness
predictions, `matched_rules` and a diagnostic `reason`. `unique_rule_match` is a
boolean rule indicator, **not a confidence probability or an accuracy claim**.
An empty frame produces an empty result tuple, not a phantom UNKNOWN hand.

```python
from gestures import ImageSize, classify_frame, extract_frame_features, from_mediapipe

# tasks_result and timestamp_ms come from the existing tracker/API.
frame = from_mediapipe(tasks_result, timestamp_ms, ImageSize(1920, 1080))
results = classify_frame(extract_frame_features(frame))
for result in results:
    print(result.gesture, result.timestamp_ms, result.matched_rules, result.reason)
```

The live bridge (`hand_tracking/gesture_preview.py`) uses the output of the
existing smoother; `--no-smoothing` makes recognition use raw coordinates.
Raw comparison crosses do not change the classifier input. Adaptation preserves
current-result slots, even if handedness predictions duplicate or detection order
changes. A malformed hand becomes UNKNOWN without shifting the other hand's
classification. If geometry cannot be adapted, its result has no handedness
metadata; the existing renderer still uses the original frame-local label when
that hand's x/y coordinates are drawable. No previous classifications are held.
Labels disappear immediately when observations disappear. Near thresholds labels
may flicker; optional Phase 3.4 debounces the resolved intent above these raw labels. Pinches and
other later gesture algorithms are not implemented in Phase 3.2.

## Manual webcam validation and performance

Run with `--gestures` and test both hands separately, then simultaneously:

1. Open palm, closed fist and pointing; vary natural thumb posture.
2. Unsupported configurations (for example two extended fingers) should read UNKNOWN.
3. Slowly curl/extend fingers through intermediate poses; inspect UNKNOWN and flicker.
4. Rotate in the image plane, then tilt modestly toward/away from the camera.
5. Use different gestures on each hand, then the same gesture on both. Cross hands,
   overlap them, and leave/reenter the frame; check current hand/label association.
6. Check Q, H, window responsiveness and `--show-raw-landmarks`; inspect EMA lag
   and compare `--no-smoothing` separately if needed.
7. Compare FPS, stage means/p95 and process CPU with recognition off/on under
   identical lighting, framing, hand distance/movement, capture and inference.

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
foreach ($mode in @('no-gestures', 'gestures')) {
    & .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker "--$mode" --benchmark --backend msmf --width 1920 --height 1080 --fps 60 --inference-resolution full --warmup 3 --duration 30 --report "hand_tracking\benchmarks\${runStamp}_${mode}.json"
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed or interrupted: $mode" }
}
```

Use only reports with `status=completed`. Repeat at least three times, reverse
mode order on a repeat, and run separate zero-, one- and two-hand comparisons.
`--headless` can be added to both runs to remove drawing/GUI; those results are
headless throughput, not preview FPS. With `--no-gestures`, adaptation, features,
rules and gesture timing stages are skipped entirely.

`gesture_features` includes adapter/snapshot plus feature extraction;
`gesture_classification` measures rule evaluation/result creation for the entire
frame; `gesture_total` contains both and must not be added to its sub-stages.
All retain mean, p50/p95/p99/max, exclude benchmark warm-up, and appear in the
per-detected-hand-count profiles. JSON includes the enabled flag, configured
raw/EMA input, thresholds and measured per-classification counts. Counts are
predictions, not accuracy or ground truth; zero hands adds no classification.

A synthetic check with two fabricated hands (100 warm-up / 1000 measured
iterations, no camera, inference or GUI) measured means/p95s of **1.006/1.338 ms**
for adaptation/features, **0.024/0.032 ms** for rules and **1.030/1.366 ms** total.
A separate preview-only check (20 warm-up / 300 samples, sequential batches)
measured **0.769/0.972 ms** without gesture labels and **0.822/1.097 ms** with them.
These are host microbenchmarks, not physical camera FPS or recognition accuracy.
The extra work is measurable, so recognition remains opt-in while local hardware
validation is pending. The 35–40 FPS target has not been verified.

## Observations and indices

`Landmark(x, y, z, visibility=None, presence=None)` contains finite real numbers.
Strings, booleans, missing required coordinates, NaN and infinity are rejected.
Coordinates are not constrained to [0, 1]; finite out-of-frame values are retained.
Optional visibility/presence values are preserved as supplied, not assumed to be
calibrated probabilities. A handedness score, when present, must be finite in
[0, 1]. No detection/tracking confidence is invented from a handedness score.

All observation dataclasses are frozen. Hand/frame collections are copied to
tuples, so later changes to input lists or MediaPipe objects cannot change them.
`HandObservation` requires exactly 21 `Landmark` objects. `FrameObservation`
contains zero to two hands, a nonnegative integer `timestamp_ms`, and optional
`ImageSize(width, height)` with positive integer dimensions. The caller supplies
timestamps from one consistent clock; the package does not impose sequence-wide
ordering or retain past observations.

`LandmarkIndex` follows MediaPipe's indexing:

| Indices | Enum names |
| --- | --- |
| 0 | `WRIST` |
| 1–4 | `THUMB_CMC`, `THUMB_MCP`, `THUMB_IP`, `THUMB_TIP` |
| 5–8 | `INDEX_FINGER_MCP`, `INDEX_FINGER_PIP`, `INDEX_FINGER_DIP`, `INDEX_FINGER_TIP` |
| 9–12 | `MIDDLE_FINGER_MCP`, `MIDDLE_FINGER_PIP`, `MIDDLE_FINGER_DIP`, `MIDDLE_FINGER_TIP` |
| 13–16 | `RING_FINGER_MCP`, `RING_FINGER_PIP`, `RING_FINGER_DIP`, `RING_FINGER_TIP` |
| 17–20 | `PINKY_MCP`, `PINKY_PIP`, `PINKY_DIP`, `PINKY_TIP` |

Use `hand[LandmarkIndex.INDEX_FINGER_TIP]`. Negative indices and indices outside
0–20 are rejected rather than using Python's negative-index convention.

## Coordinates and units

MediaPipe normalizes x by image width and y by height. Image x increases right,
y down. Its normalized z estimates wrist-relative depth; smaller values are
closer to the camera, with roughly x's scale. These are not metric world landmarks.
See [Google's Hand Landmarker result documentation](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python).

VisionControl passes unmirrored camera images to the Tasks API. The adapter
preserves coordinates and handedness exactly; it neither reflects x nor swaps
Left/Right. `HandednessPrediction.side` exposes recognized category names, with
other/missing names mapped to `HandSide.UNKNOWN`. Low scores remain low scores;
no confidence decision is made. Handedness is a prediction, never a track ID.
Mirroring a future preview requires an explicit display transformation while
keeping geometry and label conventions consistent.

For geometry, two explicit coordinate choices are supported:

- With `image_size=None`, calculations use the supplied normalized x/y (and
  optionally z) directly. On a nonsquare image, an x unit and a y unit represent
  different image lengths. This mode is useful for abstract/square-plane inputs;
  it is not an aspect-correct camera distance.
- **For camera observations, supply `ImageSize`**. Geometry uses
  `(x, y * height / width[, z])`, placing x/y on common image-width units.
  Results are independent of image resolution at a fixed aspect ratio. The
  optional z axis remains an approximate model depth, not calibrated 3D geometry.
  `extract_frame_features` uses the frame's image size for all its hands.

`to_image_coordinates(point, size)` returns continuous `(x*width, y*height)`
without rounding or clipping. For example, (0.25, 0.75) at 1920×1080 becomes
(480, 810); (1, 1) becomes (1920, 1080), at the image's outer boundary.
Use `clip=True` explicitly to clamp to valid pixel-center bounds
`[0, width-1]` / `[0, height-1]`, then round if drawing requires integer indices.
Do not use clipped coordinates for geometry. The existing tracker renderer's
separate rounded `(width-1)` display mapping remains unchanged.

## Geometry and degeneracy

Public functions accept validated `Landmark`/`HandObservation` objects:

- `distance_2d`, `distance_3d`: Euclidean distances in the selected coordinate
  space. `landmark_distance` selects two indices from a hand and supports
  `dimensions=2` (default) or `3`.
- `vector_between(start, end)`: end minus start, in two or three dimensions.
- `magnitude`, `normalize`, `dot`: two/three-component vector operations.
  Unit normalization rejects zero vectors. Dot products require equal dimensions.
- `angle_degrees(a, vertex, c)`: interior angle at the middle point, in [0, 180]
  degrees. Either zero-length edge returns `None`. Floating-point cosine is
  bounded before `acos`; input coordinates are never silently clipped.
- `palm_scale`: mean of wrist-to-middle-MCP distance and index-MCP-to-pinky-MCP
  distance, using the same coordinate space as the numerator.
- `normalized_distance`: selected landmark distance divided by that palm scale.
  A zero scale raises `ValueError`. There are no pixel thresholds or gesture rules.

Non-finite/malformed coordinates and vector components raise `ValueError`.
Calculations that exceed finite floating-point range also fail explicitly.
No arbitrary epsilon is used to classify a small hand as a gesture or invent
measurements when a vector has no direction.

## Named features and the consumer contract

`extract_features(hand, image_size=...)` calculates the following once and returns
a frozen `HandFeatures`, retaining the original immutable observation and units:

| Feature | Meaning |
| --- | --- |
| `palm_scale` | Raw mean palm length/width described above |
| `thumb_index_distance` | Raw thumb-tip to index-tip distance |
| `thumb_index_ratio` | That distance / palm scale |
| `fingers` | Tuple of named `FingerFeatures`, one for each `Finger` |
| `finger(Finger.INDEX)` | Named lookup without assuming a tuple position |
| `tip_to_wrist_ratio` | Fingertip-to-wrist distance / palm scale |
| `joint_angle_degrees` | PIP interior angle for fingers; MCP for thumb |
| `distal_angle_degrees` | DIP interior angle for fingers; IP for thumb |
| `straightness_ratio` | Base-to-tip chord / three-segment chain length |

Finger chains start at MCP, then PIP/DIP/TIP; the thumb uses CMC/MCP/IP/TIP.
Straightness is a continuous geometric ratio in [0, 1], **not** an extended/folded
decision. Its upper bound is capped only to suppress floating-point overshoot.
Undefined feature angles/ratios use `None`: zero palm scale leaves normalized
distances unavailable; a zero chain length leaves straightness unavailable.
Raw palm scale/distance remain available, including zero. Undefined values must
not later be treated as recognized gestures or silently replaced by zeros.

`extract_frame_features(frame)` returns `FrameFeatures(observation, hands)`.
Future classifiers can consume this record's timestamp, raw/smoothed coordinates,
metadata and cached geometry. This supports later static comparisons and later
temporal consumers retaining consecutive records for movement/transitions. Empty
frames explicitly represent no observations. Phase 3.2 static rules now consume
this contract; it implements no matching or temporal events itself. Phase 3.4's
opt-in consumer now manages state above these same immutable observations.
Future temporal code must solve hand association explicitly; tuple order and
Left/Right predictions are insufficient for persistent identity.

## Synthetic example

Run this Python code from the repository root. The coordinates form mathematical
line segments for illustrating measurements, not an anatomically verified pose:

```python
from gestures import HandObservation, ImageSize, Landmark, LandmarkIndex, extract_features
from gestures.geometry import normalized_distance

I = LandmarkIndex
points = [Landmark(.5, .8, 0) for _ in I]
points[I.MIDDLE_FINGER_MCP] = Landmark(.5, .5, 0)
points[I.INDEX_FINGER_MCP] = Landmark(.4, .5, 0)
points[I.PINKY_MCP] = Landmark(.6, .5, 0)
points[I.INDEX_FINGER_PIP] = Landmark(.4, .4, 0)
points[I.INDEX_FINGER_DIP] = Landmark(.4, .3, 0)
points[I.INDEX_FINGER_TIP] = Landmark(.4, .2, 0)
points[I.THUMB_TIP] = Landmark(.3, .6, 0)

hand = HandObservation(points)
size = ImageSize(1920, 1080)
features = extract_features(hand, image_size=size)
print(features.palm_scale, features.thumb_index_ratio)
print(normalized_distance(hand, I.THUMB_TIP, I.INDEX_FINGER_TIP, image_size=size))
```

## Adapting MediaPipe Tasks output

For direct use of the foundation (the live bridge performs this work only when
`--gestures` is enabled):

```python
from gestures import ImageSize, extract_frame_features, from_mediapipe

# result: existing HandLandmarkerResult, or the result of LandmarkSmoother.apply
# timestamp_ms: the existing monotonic per-frame timestamp
observation = from_mediapipe(result, timestamp_ms, ImageSize(1920, 1080))
features = extract_frame_features(observation)
for hand in features.hands:
    print(hand.observation.handedness, hand.palm_scale, hand.thumb_index_ratio)
```

The adapter imports no MediaPipe, camera or GUI module. It accepts result objects
with Tasks-compatible attributes, copies all 21 normalized landmarks in order,
and pairs each hand with its categories **within that result**. Valid category
names/scores are retained, including multiple candidates, uncertain labels and
duplicate Left/Right predictions. Hands are never sorted, merged, reassociated
between frames or discarded for uncertain handedness. Missing category rows
produce empty tuples; malformed optional categories are ignored. Extra unpaired
metadata is unused. Malformed geometry or more than two hands raises `ValueError`
instead of silently skipping/truncating observations. A missing result is not an
empty frame; provide a result with `hand_landmarks=[]` for zero detections.

Raw and existing EMA coordinates use the same adapter. It performs no additional
smoothing and does not alter either input. Metadata that the source does not
provide remains absent; world landmarks are not imported into normalized points.

## Limits and validation

Distance ratios and joint angles are invariant to translation and positive
uniform scaling within the same coordinate space. Raw lengths scale with the
input. These scalar 2D measurements are invariant to in-plane rotations in a
common-axis space, but x/y vectors, screen coordinates and future directional
features are not. An in-plane rotation in raw nonsquare normalized coordinates
does not represent the same physical rotation. Tilting a hand in depth causes
foreshortening/occlusion; 2D ratios and angles can change. Estimated z is not
metric calibration or a cure for perspective. A collapsed palm/chain, off-screen
points, model jitter, handedness errors and EMA lag remain caller considerations.

No gesture accuracy, new hardware FPS or true camera-to-display latency has been
measured for this foundation. The owner's verified Phase 2.5 two-hand result was
38.77 FPS before live gesture integration. Disabling recognition skips all new
classification work; enabled recognition's physical accuracy/performance still
requires local evaluation. Geometry can satisfy these broad rules for unsupported
poses, especially under occlusion or strong perspective. There is no guarantee
that every unsupported physical pose will return UNKNOWN.

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s camera -v
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

The 36 Phase 3.1 tests cover indexing/validation/immutability, adapter cardinality and
metadata pairing, input snapshots, distances/vectors/angles/degeneracy, aspect and
image conversion, expected feature measurements, translation/scaling, planar
rotation, projection limits and independent hands/loss. Phase 3.2 adds rule and
live-bridge tests for articulated poses, natural thumb variations, both sides,
scale/rotation, moderate synthetic foreshortening, ambiguous/invalid/conflicting
features, detection order, EMA input, rendering, Q/H/native polling, warm-up and
JSON timing/count behavior. All earlier camera/tracking tests are also run.
Compatibility smoke checks additionally use the installed Tasks enum,
real Tasks result containers and the existing EMA output without a camera.
The original Phase 3.2 baseline was 134 tests. Calibration adds 14 regressions for
relaxed curls, slight index bends, side/scale/rotation, peace/three-finger/thumbs-up
exclusions, separation safeguards, malformed features, shared diagnostic decisions,
rate limiting, opt-in behavior and independent live two-hand outputs.
The **Phase 3.2 baseline** was 148 passing tests: 56 gesture, 76 tracking and 16 camera tests.
An additional smoke test loaded the real installed model, processed blank 1080p
synthetic frames with `--gestures` in a native Win32 preview, recorded gesture
timings with no phantom classifications, and released the simulated capture/window.
This was an integration check without a physical webcam. Synthetic label layout
was also rendered and visually inspected; physical accuracy remains unverified.

Suggested commit after review:

```text
feat(gestures): recognize static hand poses with unknown fallback
```

Phase 3.2 stops here. No automatic commit or push is performed.
