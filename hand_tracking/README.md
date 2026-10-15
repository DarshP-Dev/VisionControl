# Phase 2.3: Hand tracking performance

Detect and draw **up to two hands**, each with 21 landmarks and a skeleton, using the
MediaPipe Tasks Hand Landmarker API in synchronous **VIDEO** mode on the CPU.
This milestone does not recognize gestures or control the cursor, voice or motors.
The existing Phase 1 camera applications are unchanged.
Inference size is configurable independently of capture; detailed benchmarking
and host timing reports are available. See [PERFORMANCE.md](PERFORMANCE.md) for
the measured synthetic baseline, limitations and full comparison procedure.

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
no identity tracker or smoothing layer. The purple fallback is not a persistent ID.
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
hands in Phase 2.2, with 42 landmarks. Phase 2.3 improvement and tracking quality
at lower inference sizes remain unverified pending local hardware testing.
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
MediaPipe image wrapping, inference, preview resize, drawing/labels, text, imshow,
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
buffer reuse, percentile calculations, warm-up exclusion, JSON reports and error/cleanup
paths with mocked cameras. Phase 1 tests cover
the preserved camera tester. A separate smoke check also initialized the actual
downloaded model and processed two blank 1080p RGB images in VIDEO mode, returning
0 hands for both. These checks do not establish real-world detection quality.

Suggested commit after local hardware testing:

```text
perf(hand-tracking): optimize real-time landmark processing
```

This implementation is limited to Phase 2.3. No automatic commit or push is made.
Use local hardware results to decide
the next milestone.
