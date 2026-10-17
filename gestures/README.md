# Phase 3.2: Static gesture recognition

This package provides the Phase 3.1 landmark geometry foundation and Phase 3.2
deterministic static rules: **OPEN_PALM, FIST, POINTING, UNKNOWN**. Feature
extraction stays separate from classification. The existing hand-tracking
preview can show per-hand gesture labels with `--gestures`; recognition is
opt-in pending physical accuracy and performance validation. The classifier
imports no camera, GUI, MediaPipe or desktop-control code. No motion history,
additional model, threads, cooldowns or gesture-triggered actions are added.

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
| `__init__.py` | Public observation/feature/adapter exports |
| `tests/` | Synthetic fixtures and hardware-independent model, adapter, geometry and feature tests |

Existing tracking helpers are display-oriented and import OpenCV/NumPy. The new
models add validation, metadata and immutable snapshots without importing that
rendering stack. The adapter also accepts the existing EMA `DisplayLandmark`
objects structurally; neither the tracker nor its smoothing code is refactored.

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

The classifier consumes `HandFeatures`; geometry is computed once using the
Phase 3.1 utilities with the **actual capture aspect ratio**. Every required long
finger must have valid measurements. The four long fingers are index, middle,
ring and pinky. Thumb posture is not a gate: a relaxed/tucked thumb is allowed,
and four clearly extended long fingers count as most fingers extended.

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
- `FIST`: all four long fingers clearly curled.
- `POINTING`: index clearly extended, the other three clearly curled.
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
may flicker; temporal debouncing/states/events belong to Phase 3.4. Pinches and
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
this contract; no matching, temporal state or gesture event system is implemented.
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
All **134 automated tests pass**: 48 gesture tests, 70 tracking tests and 16 camera tests.
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
