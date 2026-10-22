# Phase 3.8 — experimental 3–4 hand observation and stable track IDs

Implement up to four simultaneous observations without adding desktop actions,
new recognition rules, models or dependencies. Two hands remains the default.
This phase ends at observation/recognition, UI, diagnostics and measurement.
No Phase 4 work or automatic staging/commit/push is included.

The owner reported the Phase 3.7 palm cursor, clicking and POINTING swipes work
well physically. That existing desktop path is preserved. Four-hand hardware
acceptance and the final useful maximum remain pending owner testing.

## Configuration and compatibility

* `--max-hands 1|2|3|4`, default **2**, sets MediaPipe `num_hands` exactly.
* Maxima 3/4 automatically enable the observation track-ID path.
* `--track-ids` opts into that same path for maxima 1/2, allowing matched
  comparisons and single/two-hand ID experiments.
* `--multi-hand-debug` samples identity diagnostics at most every two seconds.
  It requires a maximum of 3/4 or explicit `--track-ids`; it does not enable
  gestures, input, or a different association policy.
* Default two-hand tracking/overlays and all one/two-hand desktop controls retain
  their original side-based path. Experimental IDs are never control owners.

The local environment contains MediaPipe **1.1.1**. Its installed options API
supports `num_hands`; the existing model was also loaded with `num_hands=4` and
successfully processed one blank synthetic image, returning zero hands. This
verifies local runtime compatibility, not detection of four real hands or FPS.
VIDEO mode, CPU delegate, the existing model and all dependencies are retained.

Capture defaults remain 1920×1080, requested 60 FPS, MSMF/MJPG. Native pollKey,
inference resizing/aspect handling, smoothing flags and alpha 0.75 are unchanged.
The requested maximum is never reduced automatically. An inconsistent detector
result exceeding it raises an error instead of silently truncating observations.
Existing camera-only utilities remain camera-only; hand-tracker previews,
headless diagnostics and the synthetic benchmark accept the new maximum.

## Architecture

The experimental path is synchronous and has one inference per frame:

```text
MediaPipe result (maximum N)
  -> validated per-hand observations (21 landmarks, current label metadata)
  -> bounded global geometric association
  -> EMA keyed by certain track IDs
  -> feature extraction once per smoothed hand
  -> existing static / pinch / gesture-state / swipe engines with track keys
  -> existing preview + aggregated JSON profiling
```

`hand_tracking/multi_hand.py` bridges these components. Raw SDK results are not
mutated, and normalized smoothed geometry is distinct from raw comparison crosses.
The existing two-hand `FrameObservation`/adapter contract remains intact; the new
bridge adapts individual hand observations and feeds cached feature tuples to the
same recognition engines. There is no parallel event bus or input dispatcher.

## Association algorithm and uncertainty

`HandAssociator` uses aspect-correct image-width axes. A descriptor contains:

* Mean of WRIST and MCPs 5/9/13/17, plus wrist position.
* Existing palm scale: mean wrist–middle-MCP length and index–pinky MCP width.
* Four wrist-to-MCP distances normalized by scale; fingertips are excluded.
* Palm-only bounding box, predicted handedness and its score.

Handedness contributes supporting cost only. Duplicate Left/Right labels, an
abrupt label flip or a low-confidence label do not define or transfer ownership.
These are **observation tracks**, not person IDs, anatomical hand authentication
or pairings of hands to people.

For each frame the associator builds gated match costs and enumerates the global
minimum-cost one-to-one assignment, including explicit unmatched/new observations.
It does not greedily consume detections. Candidate displacement is time-aware:
center gate `min(0.16, 0.025 + 1.8 * elapsed_seconds)` in image-width units, wrist
gate 1.3 times that limit. Implausible scale/shape changes are rejected. The scale
log-change limit is `min(0.6, 0.4 + 0.6 * elapsed_seconds)`; normalized shape RMS
must be <=0.40. These are conservative engineering gates, not hardware calibration.

Cost combines distance to the bounded velocity prediction divided by palm scale,
scale and shape change, a small high-confidence label-mismatch penalty (0.03) and
a missing-track penalty (0.12). Prediction uses the previous velocity blended
50/50 with measured velocity and extrapolates at most 100 ms. New-observation
cost is 2.4. Candidate IDs are visited in sorted order for deterministic ties.

The runner-up cost is checked per observation across complete assignments. A
margin under **0.20** marks association uncertain. Close palm centers (less than
0.65 times the smaller palm scale) or substantial palm-box overlap also mark the
affected observations uncertain. This can conservatively reject two close hands
even when a human can distinguish them.

Ambiguous/overlapping observations show **TRACK ? / UNCERTAIN**. Plausibly
implicated old tracks are retired; separated hands get new IDs. Distant unaffected
tracks continue independently. No arbitrary tie is advertised as identity
continuity. Individual malformed/occluded observations retain their frame slot
but do not get an actionable ID.

IDs increase monotonically for the session and are not reused on reset or
retirement. A missing track can remain in the association pool for **500 ms**,
permitting a unique geometric reappearance to keep its ID. A processed-frame gap
over 250 ms, nonmonotonic time or capture-size change invalidates continuity.
At most `2 * max_hands` active/missing descriptors are retained, evicting oldest
missing tracks if necessary. Four observations/eight retained tracks give at
most 3,393 complete assignment leaves, a bounded small search; no growing path
history or retired-ID list is retained.

There is no guarantee that a similar new hand entering near a lost track can be
distinguished from the old hand. An indistinguishable replacement can retain the
same ID. Fast crossings between frames, depth occlusion and plausible but wrong
MediaPipe landmarks can defeat geometry. IDs never establish human identity.

## Smoothing and independent gestures

Track smoothing shares the existing EMA formula, alpha and rapid-motion bypass
with the legacy smoother. It keys history by track ID, never by label or result
position. Only current, certain observations are retained. Missing, uncertain,
new and geometrically reset tracks start raw; no landmarks are held on-screen
while a hand is absent. Keeping an association ID across a dropout does **not**
keep its smoothing history.

The existing `PinchTracker.update` and `GestureStateManager.update` have an
optional `identities=(id, ..., None)` namespace. Positive unique integers select
tracks; None is uncertain and cannot maintain state. Without this argument their
original two-hand duplicate-label, overlap and confidence safeguards remain.

Static rules and thresholds do not change. `GestureResult`, `PinchResult`,
`HandState` and `GestureEvent` carry optional track-ID metadata. It is not
recognition evidence. In track mode, ID, timestamp and handedness metadata must
align across the supplied static/pinch channels; swapped same-label channels
are rejected instead of being attributed to the wrong track.

Each track has independent pinch hysteresis, static confirmation/cooldowns and
swipe history. PINCH precedence, swipe distance/velocity/dominance/consistency,
timing, cooldown and stationary reset remain unchanged. Opposing multi-hand
swipe evidence retains the existing conflict suppression. Supported poses and
events remain OPEN_PALM, FIST, POINTING, UNKNOWN, PINCH and SWIPE_LEFT/RIGHT.

Gesture history is canceled **immediately** on missing/uncertain association,
even if its geometric ID is retained temporarily. Cancellation events carry the
former track ID and historical-association flag. A returning closed hand must
open again before a fresh pinch can start; loss never fabricates RELEASED,
GESTURE_ENDED or a completed swipe. Raw static geometry can still be displayed
alongside an UNCERTAIN association, but no stateful gesture is admitted for it.

## Desktop safety boundary

`--controls` with `--max-hands 3/4` is rejected in **both simulation and live**
modes. Experimental `--track-ids` is also incompatible with controls at 1/2 hands.
There is no automatic selection among duplicate Right or Left predictions.
Max-one controls remain supported; Left rearm/resume requires max-two because
its existing validator requires two distinct hands.

The restriction is enforced in CLI validation, the controller factory and direct
processing entry point. The controller itself additionally rejects any track-ID
state/event, disarming and releasing owned input if one is supplied directly.
An accidental caller cannot turn an experimental track into desktop ownership.
Existing legacy/palm profiles, click/drag, region/inversion, automatic/manual
resume, Left system rearm, A/D, emergency shortcut, watchdog and cleanup remain
covered by the full controls suite. No multi-person control or new actions exist.

## Preview and diagnostics

The experimental preview draws all valid skeletons, readable track IDs, raw
Left/Right classification and its API score, static classification, optional
pinch/state/swipe rows, association status and `HANDS: visible / requested`.
Four distinct colors assist recognition; text IDs also distinguish tracks.
Spatial columns and vertical annotation bands prevent labels overwriting each
other. UI placement is not association. Raw comparison crosses cover every hand.
Default two-hand overlays retain their original layout.

Handedness percentages are model predictions. Association is a qualitative
unique-match/uncertain decision, **not a calibrated confidence percentage**.
Geometric costs appear only in optional debug output. Every two seconds the
debug summary reports current IDs/reasons/costs, visible count, retirements since
the last sample and cumulative creation/loss/reacquisition/retirement/label-change/
uncertainty counts. Brief transitions are reflected in totals even if between
samples. Event-debug lines include track IDs. No camera images, raw landmark
coordinates or per-frame action logs are saved by these diagnostics.

A synthetic four-hand preview including all optional numeric rows was rendered
and visually inspected. It is not a real-camera acceptance image.

## Exact PowerShell commands

Run one preview at a time from the repository. None of these observation commands
enables a controller, sends Windows input or registers an input emergency thread.
Q/H retain their existing preview meaning.

```powershell
Set-Location C:\Users\Darsh\VisionControl

# 1. Two-hand ID preview; omit --track-ids for the unchanged default preview.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 2 --track-ids

# 2. Three-hand tracking preview.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 3

# 3. Four-hand tracking preview.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 4

# 4. Four-hand static, pinch, state and POINTING swipe recognition.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 4 --gestures --pinch --gesture-states --swipes --swipe-pose pointing

# 5. Optional sampled association debugging and raw comparison.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 4 --gestures --pinch --gesture-states --swipes --swipe-pose pointing --multi-hand-debug --gesture-event-debug --show-raw-landmarks

# 6. Four-hand visible end-to-end benchmark; choose a fresh report path.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands 4 --gestures --pinch --gesture-states --swipes --swipe-pose pointing --benchmark --warmup 3 --duration 30 --report hand_tracking\benchmarks\four_hands_preview.json

# 7. Matched 2/3/4 maxima, all using the same observation-ID path.
New-Item -ItemType Directory -Force -Path .\hand_tracking\benchmarks | Out-Null
$phase38Stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
foreach ($phase38Maximum in @(2, 3, 4)) {
    .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands $phase38Maximum --track-ids --gestures --pinch --gesture-states --swipes --swipe-pose pointing --backend msmf --width 1920 --height 1080 --fps 60 --inference-resolution full --smoothing-alpha 0.75 --benchmark --warmup 3 --duration 30 --report "hand_tracking\benchmarks\${phase38Stamp}_${phase38Maximum}_hands.json"
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed: max-hands $phase38Maximum" }
}

# 8. Complete hardware-independent regression suites.
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
```

Repeat the comparison at least three times, reverse order with a fresh timestamp,
and show the intended number of hands for each maximum. Use only reports with
`status=completed`. Maximum four with only one detected hand is not four-hand FPS.
Keep lighting, camera framing, gestures, actual visible count, capture/inference
size, smoothing and GUI mode matched. Disable debug overlays/logging for timing.
Also compare default `--max-hands 2` without IDs to quantify the opt-in overhead.
Try `--inference-resolution 1280x720` or `960x540` as separate controlled runs;
capture still requests 1080p and detection quality must be checked again.

The JSON retains requested capture settings, driver readback, actual capture and
inference-size distributions, observed-hand-count bins, inference, association,
smoothing, feature/rule/pinch/state/swipe, rendering/GUI, total processing and
end-to-end timings, plus process CPU usage. Means use all measured frames;
median/P95/P99 use the existing bounded sample window. Warmup is excluded from
timings/counters of measured frames; association lifecycle totals describe the
entire session, including warmup.

Requested capture FPS and driver-reported FPS are not measured application FPS.
The synchronous tracker does not independently measure free-running camera
delivery or buffered frame age. For a separate capture-only throughput check:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --benchmark --backend msmf --width 1920 --height 1080 --fps 60 --warmup 3 --duration 30
```

That excludes inference/recognition/rendering and must be reported separately,
not substituted for end-to-end processed FPS. These physical commands were not
executed during implementation.

## Synthetic validation and performance

Initial Git status was clean on `main`, `cd2ffcd`. The measured baseline was
**590 tests** (574 root-discovered + 16 camera). Final results are **642 passing**:
16 camera, 163 gestures, 211 hand tracking, 252 controls. No prior tests were
deleted, skipped or weakened.

New tests cover 0–4 observations, duplicate/interleaved labels, all four-hand
result permutations, a greedy-assignment trap, births/expiry, scale/motion gates,
dropouts, horizontal/vertical overlap, ambiguity and bounded storage; independent
EMA; track-key channel alignment and pinch/swipe history; closed reacquisition;
four-hand preview clearing/raw overlays; CLI/model options; warmup exclusion and
four-hand JSON bins; and controller-level refusal/drag cleanup. Existing desktop
profile, rearm, resume, watchdog, emergency and backend tests remain intact.

The extended offline benchmark accepts `--max-hands` and `--track-ids`, uses
identical-scale prefix fixtures for matched observation counts, and rejects
3/4-hand simulated-control workloads. It makes no camera/GUI/SendInput calls:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.benchmark_synthetic --max-hands 4 --track-ids --frames 500 --warmup 100 --repeats 3 --report hand_tracking\benchmarks\phase3_8_matched.json
```

The local report is in `hand_tracking/benchmarks/phase3_8_matched.json` (Git-ignored).
It contains 45 runs across 0–4 fixture counts and static/pinch/swipe workloads,
using the existing profiler. The protocol is **100 warmup + 500 measured frames,
three repeats**, with 33 ms
synthetic observation timestamps. Capture, conversion, MediaPipe, rendering,
watchdog and real desktop input are excluded. Synthetic iteration rate is never
webcam FPS. No four-hand hardware throughput, accuracy or latency was measured.

Matched swipe-enabled host-processing results (milliseconds/frame):

| Visible synthetic hands | Association mean | Association P95 | Smoothing mean | Host total mean | Host total P50 | Host total P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 0.182 | 0.324 | 0.140 | 1.588 | 1.416 | 2.684 |
| 3 | 0.267 | 0.529 | 0.213 | 2.333 | 2.085 | 3.929 |
| 4 | 0.341 | 0.606 | 0.266 | 3.035 | 2.759 | 5.018 |

Means and P50 entries above average the three equal-length run statistics; P95
entries show the worst run's P95, not pooled percentiles. Per-run mean/median/P95
and CPU statistics are retained in JSON. Host total includes adaptation,
association, smoothing, features and recognition/state processing. It excludes
MediaPipe/camera/rendering, so these costs cannot be converted to webcam FPS.

## Manual acceptance and remaining limits

1. Start with one then two hands; verify ID continuity under smooth movement,
   detection order changes, Left/Right prediction mistakes and score changes.
2. Have two people show three then four hands. Confirm simultaneous detection,
   21 points/skeleton per valid hand, duplicate Left/Right labels and all overlays.
3. Move hands horizontally/vertically across each other, overlap palms and partly
   hide fingers. Ambiguous hands should show UNCERTAIN and cancel their state;
   separated reacquisition should not assert the old crossing identity.
4. Briefly remove one/two hands, then return open and already pinched. IDs can
   survive a unique short dropout, but smoothing/gestures must start fresh with
   no phantom release, swipe completion or held overlay.
5. Enter a new hand near a lost track, vary distance/apparent size, and test fast
   motion. Record mistaken matches and conservative resets; IDs are not proof
   that the same physical person/hand returned.
6. Exercise independent OPEN_PALM/FIST/POINTING, individual and simultaneous
   pinches, and both swipe directions. Confirm another hand cannot alter a
   track's pinch/swipe history. Test opposing-swipe suppression separately.
7. Collect matched 2/3/4 visible benchmarks and inspect observed-count bins,
   inference/association/smoothing/rendering cost and CPU. Recheck recognition
   quality when reducing inference size, rather than judging FPS alone.
8. Separately rerun the existing one/two-hand desktop acceptance (legacy/palm,
   click/drag, both resume modes, Left system rearm, D/emergency, watchdog and
   cleanup). Confirm 3/4-hand controls fail validation, never downgrade silently.

Provisional four-hand preview targets are 35+ FPS excellent, 30–35 very good,
25–30 usable for demonstration, below 25 a reason to evaluate three hands or
lower inference resolution. They are owner experience targets, not measured
results or automatic switching thresholds. Keep default two until hardware
measurements support another choice; experimental four remains selectable.

Crossings/occlusion, similar replacements, rapid motion, strong perspective and
detector confidence errors remain limitations. The geometric gates may need
real landmark-only calibration. Future work can evaluate confidence-aware
geometry and more recorded crossing fixtures, with explicit privacy safeguards.
Persistent person identity, hand pairing, asynchronous inference and multi-user
desktop control are not implemented or authorized by this phase.

## Changed files and review boundary

* New association/bridge/fixtures: `hand_tracking/association.py`,
  `hand_tracking/multi_hand.py`, `hand_tracking/multi_hand_fixtures.py`.
* Tracking integration: `hand_tracking/hand_tracker.py`, `smoothing.py`,
  `tracking_utils.py`, `performance.py`, `benchmark_synthetic.py`.
* Optional recognition namespace/metadata: `gestures/association.py`, `events.py`,
  `pinch.py`, `state_machine.py`, `static_gestures.py` (no rule changes).
* Desktop isolation only: `controls/cli.py`, `controls/controller.py`.
* New tests: `hand_tracking/test_association.py`, `hand_tracking/test_multi_hand.py`,
  `gestures/tests/test_track_namespace.py`, `controls/tests/test_track_isolation.py`.
* Documentation: this file, `hand_tracking/README.md` and `hand_tracking/PERFORMANCE.md`.

Changes remain unstaged/uncommitted for owner testing. Suggested future commit:

```text
feat(hand-tracking): add experimental four-hand tracking and stable track IDs
```
