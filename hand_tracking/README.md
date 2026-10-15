# Phase 2.4: Hand tracking stability

Detect and draw **up to two hands**, each with 21 landmarks and a skeleton, using the
MediaPipe Tasks Hand Landmarker API in synchronous **VIDEO** mode on the CPU.
This milestone does not recognize gestures or control the cursor, voice or motors.
The existing Phase 1 camera applications are unchanged.
Inference size is configurable independently of capture; detailed benchmarking
and host timing reports are available. See [PERFORMANCE.md](PERFORMANCE.md) for
the measured synthetic baseline, limitations and full comparison procedure.
Lightweight landmark EMA smoothing is enabled conservatively by default, with
raw comparison and explicit reset behavior described below.

## Run on Windows

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker
```

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
using full inference. Phase 2.4 stability and overhead remain unverified pending
local hardware testing.
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
waitKey, processing and the loop. Means/maxima cover all measured samples;
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
settings and driver readbacks. Report directories are created automatically and
ignored by Git; existing reports are protected from overwrite. Use a fresh filename
for each run. A run stopped with Q is marked `stopped`; Ctrl+C marks `interrupted`.
Only a benchmark reaching its requested duration is marked `completed`.

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
.\.venv\Scripts\python.exe -m unittest discover -s camera -v
.\.venv\Scripts\python.exe -m compileall -q hand_tracking camera
.\.venv\Scripts\python.exe -m pip check
```

The hand-tracking tests cover arguments, timestamps, FPS, RGB conversion,
landmark scaling/topology, 0/1/2-hand rendering, help, VIDEO/CPU/two-hand options,
handedness pairing, order changes, duplicate/missing predictions, disappearing
hands, invalid detections, performance warnings, model checksums, inference sizes,
buffer reuse, percentile calculations, warm-up exclusion, JSON reports, EMA
arithmetic, independent handedness histories, motion bypass, loss/reappearance,
ambiguous identity, reset rules and error/cleanup paths with mocked cameras.
Phase 1 tests cover
the preserved camera tester. A separate smoke check also initialized the actual
downloaded model and processed two blank 1080p RGB images in VIDEO mode, returning
0 hands for both. These checks do not establish real-world detection quality.

Suggested commit after local hardware testing:

```text
feat(hand-tracking): improve landmark smoothing and recovery
```

This implementation is limited to Phase 2.4. No automatic commit or push is made.
Use local hardware results to decide
the next milestone.
