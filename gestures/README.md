# Phase 3.1: Gesture recognition foundation

This package turns landmark observations into validated data and reusable
geometric measurements. It extracts **features**, not gesture names or pose
classes. It has no recognition thresholds, motion history, desktop actions,
capture, rendering, threads or model inference. Nothing calls it from the live
hand tracker yet; the Phase 2.5 pipeline and its CLI are unchanged.

The package uses only Python's standard library (Python 3.11+; the existing
environment is Python 3.13.7). No requirements changes or installations are needed.

## Modules

| File | Responsibility |
| --- | --- |
| `models.py` | Official landmark indices; immutable validated landmarks, predictions, hands, frame observations and image dimensions |
| `landmarks.py` | Snapshot adapter for raw/EMA Tasks results; explicit image-coordinate conversion |
| `geometry.py` | Stateless distances, vectors, unit directions, dot products, angles, palm scale and distance ratios |
| `features.py` | Named per-finger/per-hand features and the lightweight `FrameFeatures` consumer contract |
| `__init__.py` | Public observation/feature/adapter exports |
| `tests/` | Synthetic fixtures and hardware-independent model, adapter, geometry and feature tests |

Existing tracking helpers are display-oriented and import OpenCV/NumPy. The new
models add validation, metadata and immutable snapshots without importing that
rendering stack. The adapter also accepts the existing EMA `DisplayLandmark`
objects structurally; neither the tracker nor its smoothing code is refactored.

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
frames explicitly represent no observations. **No classifier, matching, temporal
state, recognition result, event interface or gesture algorithm is implemented.**
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

Call this **outside the existing live loop** when using the foundation explicitly:

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
38.77 FPS; this package adds no work to that tracker. Live recognition integration
and physical accuracy/performance evaluation belong to later milestones.

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -v
.\.venv\Scripts\python.exe -m unittest discover -s camera -v
.\.venv\Scripts\python.exe -m compileall -q gestures hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

The 36 new tests cover indexing/validation/immutability, adapter cardinality and
metadata pairing, input snapshots, distances/vectors/angles/degeneracy, aspect and
image conversion, expected feature measurements, translation/scaling, planar
rotation, projection limits and independent hands/loss. All 77 prior tests are
also run. Compatibility smoke checks additionally use the installed Tasks enum,
real Tasks result containers and the existing EMA output without a camera.

Suggested commit after review:

```text
feat(gestures): add recognition foundation and geometry utilities
```

Phase 3.1 stops here. No automatic commit or push is performed.
