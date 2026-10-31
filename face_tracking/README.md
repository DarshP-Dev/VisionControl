# Face detection, tracking, centering and digital framing — Phases 4.1–4.4

Optional MediaPipe BlazeFace **detection**, using the existing camera owner and
application loop. Optional Phase 4.2 spatial tracking adds temporary IDs and a
primary lock. No identity recognition, pose, motor or desktop actions.
See [PHASE_4_1.md](../PHASE_4_1.md) for architecture, real measurements and acceptance.
See [PHASE_4_2.md](../PHASE_4_2.md) for temporal tracking, synthetic measurements
and pending physical acceptance.
Phase 4.3 adds optional, read-only centering recommendations. See
[PHASE_4_3.md](../PHASE_4_3.md) for calculations, measurements and owner acceptance.
Phase 4.4 adds output-only digital following. See
[PHASE_4_4.md](../PHASE_4_4.md) for geometry, dual-window behavior and acceptance.
Phase 4.5 optionally consumes the same locked centering snapshot for a
[virtual motor simulator](../motor_control/README.md). `--motor-simulate` enables
the prerequisites; no physical motion or feedback into webcam images occurs.
The separate [mount concept](../hardware/concepts/README.md) is not fabrication-ready.

```powershell
Set-Location C:\Users\Darsh\VisionControl
.\.venv\Scripts\python.exe -m face_tracking.download_model
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-detection
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-tracking --face-tracking-debug
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-tracking
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-centering --face-centering-debug
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-centering
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --digital-reframe --reframe-debug
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --digital-reframe
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

## Read-only centering (opt-in)

`--face-centering` implies both tracking and detection. It uses the confirmed,
currently detected, certain primary track's existing smoothed position. Positive
X means conceptual pan right; positive Y means tilt down. Pixels are always in
the original captured frame; normalized error divides by half width/height.
Demand is bounded to [-1,1] and is not degrees, motor speed or input authorization.
No second EMA, crop, model pass, camera instance or output backend is added.

Independent X/Y hysteresis activates above `.12` and deactivates at/below `.07`.
Tune both axes with `--face-centering-activation .12` and
`--face-centering-deactivation .07`. Reversals need the opposite activation
threshold; small reversals become inactive. `--face-centering-debug` draws the
dead zones. `--no-face-overlay` hides drawing while calculations continue.
Lost, uncertain, unconfirmed, invalid or older-than-250-ms observations produce
zero demand and no current coordinates. Recovery/target changes reset hysteresis.

`FaceCentering.update(TrackedFaces, now=host_monotonic_time, profile=optional)`
returns immutable `CenteringResult` with per-axis measured/raw errors, active
state, conceptual direction and demand, plus target ID, status, current centers,
frame dimensions and actual observation timestamp/age. `actionable` describes
validity at calculation time, including a zero-demand centered hold; a stored
result must pass `fresh_at(now)` before later use. `CenteringConfig` supports
separate axis thresholds and a manually configured normalized target point;
the CLI uses frame center. Angles await explicit FOV calibration in a later phase.

Headless/minimized modes share the existing processing and capture ownership.
Existing report opt-ins include `face_centering`, `centering_observation_age`,
`face_centering_overlay` timings and bounded state/transition/stale counters.
Reports store numeric summaries, not face coordinates or camera frames.

## Digital reframing (opt-in)

`--digital-reframe` enables centering, persistent tracking and detection, and adds
the `VisionControl - Digital Auto-Frame` window. All inference/gesture/control
coordinates still use the full original capture. The output crop uses the locked
smoothed face center, with its own viewport-relative dead zone; it does not
integrate the original-frame pan/tilt demand. No camera is moved or reopened.

Defaults: `--reframe-scale` 2/3 (1280×720 from 1920×1080),
`--reframe-follow-tau .2`, `--reframe-max-speed 600` source pixels/second,
`--reframe-dead-zone .10` of crop half-size (inner threshold .06).
`--reframe-debug` outlines the crop on the original preview. The renderer uses a
read-only NumPy slice and a separate reusable display buffer, preserving source
pixels and crop aspect. Full-resolution output is not upscaled for processing.

`--no-reframe-preview` retains calculations without the auxiliary window.
Headless benchmarking performs calculations only. Minimized windows independently
skip their drawing while capture/tracking/reframing continue. Auxiliary X closes
only that preview for the rest of the session; original X or Q ends the session
with existing safety/resource cleanup. Restart to reopen the auxiliary preview.
No additional event pump, GUI framework or system-wide virtual webcam is created.

`DigitalReframer.update(CenteringResult, source_size=(W,H), now=host_time,
profile=optional)` returns immutable `ReframeResult` and `CropRectangle` metadata.
Loss, uncertainty, expiry, stale/invalid observations hold the crop without a new
target. Current video pixels remain live in the held viewport. Recovery/new IDs
restart timing and resume gradually. `fresh_at(now)` rechecks stored-result age.
Configurable fixed composition and independent axis thresholds are API-only;
no automatic zoom, composition rules, motor or ownership features are included.

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
