# Face detection and temporal tracking — Phases 4.1 / 4.2

Optional MediaPipe BlazeFace **detection**, using the existing camera owner and
application loop. Optional Phase 4.2 spatial tracking adds temporary IDs and a
primary lock. No identity recognition, pose, motor or desktop actions.
See [PHASE_4_1.md](../PHASE_4_1.md) for architecture, real measurements and acceptance.
See [PHASE_4_2.md](../PHASE_4_2.md) for temporal tracking, synthetic measurements
and pending physical acceptance.

```powershell
Set-Location C:\Users\Darsh\VisionControl
.\.venv\Scripts\python.exe -m face_tracking.download_model
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-detection
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-tracking --face-tracking-debug
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-tracking
```

The hand-only command is unchanged. `--face-only` skips the hand model and rejects
gestures/controls. `--face-detection` adds faces to the current capture; it opens
no additional camera or worker. Existing sync/latest-thread, benchmark/headless,
preview lifecycle and explicit Windows timer policy are shared.

Options: `--face-model PATH`, `--face-inference-resolution 640x360|full|WIDTHxHEIGHT`,
`--face-min-confidence 0.5`, `--face-overlay` / `--no-face-overlay`.
Defaults: faces off, bounds 640×360, confidence threshold .5, overlays on when faces
are enabled. The separate hand inference resolution is unchanged. RGB buffers
prepared for the same hand frame can be reused; insufficient or incompatible
buffers fall back to the original captured BGR frame.

`FaceDetector.detect(frame, timestamp_ms, profile, rgb_hint=None)` accepts the
already-captured BGR image. Immutable `FaceFrame` contains all valid detections
and a current-frame primary. Pixel boxes use continuous edges in `[0,W]×[0,H]`,
with partially outside boxes clipped to the frame. The center is the clipped
visible box center. Normalized boxes are within `[0,1]`; normalized offsets are
`(cx-W/2)/(W/2)` and `(cy-H/2)/(H/2)`. Negative X is image-left, negative Y above;
preview and results are unmirrored. Cursor inversion does not affect face geometry.

Primary selection: highest known confidence, then largest clipped area, then
ascending box coordinates. Missing confidence ranks last. `FACE 1` is a current
rank, never a persistent identity. Empty results have no primary/coordinates;
results older than 250 ms at completion/draw are cleared and marked expired.
Detection-only mode has no smoothing, reuse of old detections or reduced cadence.

## Temporal tracking (opt-in)

`--face-tracking` implies detection, retaining the same camera and model. It runs
after current hand-controller processing. Defaults: three observations spanning
at least 60 ms to confirm, 800 ms missing timeout, 70 ms EMA time constant. Tune
`--face-confirmation-hits 3`, `--face-lost-timeout .8`, `--face-smoothing-tau .07`
(zero disables EMA). `--face-tracking-debug` adds raw magenta centers alongside
smoothed centers; `--no-face-overlay` skips both kinds of face drawing.

`FaceTracker.update(FaceFrame, observed_at=host_read_completion, now=host_now,
profile=optional_profile)` returns immutable `TrackedFaces` / `FaceTrack`
snapshots. Current raw/smoothed `FaceDetection` values are absent when lost,
expired or uncertain. Confidence and timestamps describe the last real detection.
Default offline clocks derive from source milliseconds; production passes actual
monotonic host times. Replay/backward timestamps never refresh detections.

IDs increment per tracker session, including across `reset()`, and are never
stored persistently. Initial primary selection uses confidence, area and geometry
after confirmation; healthy locks survive score changes and short losses.
Expired locks can reacquire only a single confirmed visible candidate. Ambiguous
matches quarantine affected IDs until expiration, withholding current coordinates.
Position-only reacquisition is spatial plausibility, never proof of identity.
All active/lost state is bounded to eight tracks; no frame/trajectory archive.

Existing `--benchmark`, `--performance-profile` and `--report` expose association,
smoothing, total tracker overhead and observation ages, plus session transition
counters. No camera frames, face coordinates or identifying data are written to
reports. The synthetic benchmark uses generated boxes and existing hand fixtures:

```powershell
.\.venv\Scripts\python.exe -m face_tracking.benchmark_tracking --frames 2000 --warmup 200 --repeats 3 --report "hand_tracking/benchmarks/face_tracking_$((Get-Date).ToString('yyyyMMdd_HHmmss_fff')).json"
```

## Model provenance and license

Google MediaPipe **BlazeFace short-range, float16, version 1**, CPU IMAGE mode.
The [official guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector)
describes the short-range webcam model and its fixed 128×128 network input.
The SDK handles internal model resizing; configured bounds control the external
image preparation and task-image copy, not the native network architecture.

- Asset: [Google's versioned TFLite download](https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite).
- Size: 229,746 bytes. SHA-256:
  `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f`.
- License: **Apache-2.0**, as stated in Google's
  [short-range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf).
  [Apache license text](https://www.apache.org/licenses/LICENSE-2.0).
- Setup explicitly downloads and verifies the pinned asset. Startup verifies the
  local checksum and never downloads anything. Assets under `face_tracking/models/`
  are ignored by Git and are not redistributed in this repository. Alternate
  `--face-model` paths must contain the same verified model in this phase.

Short-range frontal/webcam use is the intended case. Distant, occluded, rotated
or poorly lit faces can be missed; false positives are possible. Raising external
resolution is not a guarantee of accuracy. No demographic/identity attributes are
computed or inferred. Multiple emitted detections alone do not prove multiple
actual people without human validation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s face_tracking/tests -t . -q
```

Tests use fake tasks and synthetic frames, with no webcam or real Windows input.
Their geometry and lifecycle assertions are not real face-accuracy measurements.
