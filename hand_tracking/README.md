# Phase 2.1: MediaPipe hand landmarks

Detect and draw **one hand's 21 landmarks** and connecting skeleton using the
MediaPipe Tasks Hand Landmarker API in synchronous **VIDEO** mode on the CPU.
This milestone does not recognize gestures or control the cursor, voice or motors.
The existing Phase 1 camera applications are unchanged.

## Run on Windows

From `C:\Users\Darsh\VisionControl` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker
```

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
capture request remains unchanged. The camera frame is converted from BGR to RGB
at capture resolution before inference. Landmarks are mapped from normalized
coordinates onto the resized preview, without mirroring the feed. Small yellow
points with dark borders and green lines mark the hand. A compact black status
panel shows application FPS, the hand count (0 or 1), and exit instructions.

For local hardware validation:

1. Close the Phase 1 preview and other webcam apps, then start the tracker.
2. Show one hand with fingers spread. Check that all five fingers and the wrist
   have points and connected lines, aligned with the displayed hand.
3. Move the hand slowly, then quickly, near/far and toward the frame edges.
4. Remove the hand: the count should return to 0 and the skeleton disappear.
5. Test H, Q, and closing the window; confirm the camera is available afterward.

No physical tracking or tracking FPS has been verified by the implementation
agent. The earlier camera's ~60 FPS result is capture throughput, not a promise
of 60 FPS inference. Low light, occlusion, framing and motion can affect detection.

## Performance and failure handling

VIDEO calls are synchronous. Every frame receives a timestamp derived from
`time.perf_counter()`, forced strictly upward by at least one millisecond when
timestamps collide. The timestamp is not derived from requested camera FPS.

The application counts completed capture/conversion/inference/preview/event-pump
iterations over roughly two-second windows. FPS initially shows `--`. Logs give
the end-to-end rate and a final average. On exit, simple mean/max timing reports
separate camera reads, RGB conversion plus inference, and preview plus GUI. Use
these to report the dominant stage if performance is poor. They include startup
and are not a full profiler. Setup/cleanup is excluded from loop timing.

No processing threads or asynchronous capture are introduced. If inference is
slow, this synchronous loop can receive buffered frames and accumulate latency;
this milestone does not attempt buffer management or dropped-frame optimization.
Driver read calls can block; cleanup occurs once they return. Requested modes
and positive driver-reported FPS do not establish actual throughput.

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
landmark scaling/topology, 0-hand handling, help, VIDEO/CPU/one-hand options,
model checksums and error/cleanup paths with mocked cameras. Phase 1 tests cover
the preserved camera tester. A separate smoke check also initialized the actual
downloaded model and processed two blank 1080p RGB images in VIDEO mode, returning
0 hands for both. These checks do not establish real-world detection quality.

Suggested commit after local hardware testing:

```text
feat(hand-tracking): add MediaPipe hand landmark detection
```

This implementation is limited to Phase 2.1. Use local hardware results to decide
the next milestone.
