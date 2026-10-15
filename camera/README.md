# Phase 1: Camera testing

This Windows/OpenCV tool requests 1920 × 1080 at 60 FPS using Media Foundation
(MSMF) by default. DirectShow remains available with `--backend dshow`.
The default format request remains `MJPG`, but this does not establish the actual
transport format. The webcam and driver negotiate the actual settings; accepting
a request does not prove that the advertised mode is delivered.

From the repository root in PowerShell, use the existing environment:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py
```

Override the device or requested mode:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --camera-index 1 --width 1920 --height 1080 --fps 60
.\.venv\Scripts\python.exe camera\camera_test.py --width 1280 --height 720 --fps 30
.\.venv\Scripts\python.exe camera\camera_test.py --backend dshow
.\.venv\Scripts\python.exe camera\camera_test.py --help
```

The existing `requirements.txt` contains OpenCV and NumPy (required by OpenCV).
If they are missing from the environment, install with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Preview and controls

Focus the preview window for keyboard input:

| Key | Action |
| --- | --- |
| S | Save the current full-resolution frame as a PNG |
| Q | Quit and print results |
| H | Toggle the FPS/resolution overlay |

Closing the preview or pressing Ctrl+C also ends the test. The preview fits
within 1100 × 650 pixels; resizing it does not change the capture or saved image.
Only measured FPS and captured resolution appear in a compact black box with
white text at the top left. FPS displays `--` until the first measurement window
completes. Keyboard instructions and detailed diagnostics remain in the console.
Screenshots have timestamps including microseconds and are saved without the
overlay in `camera/captures/`, created automatically and ignored by Git. The path
is relative to the script, regardless of the shell's working directory.

## Manual test procedure

1. **Resolution:** Compare the requested mode with the logged actual frame
   dimensions and saved PNG dimensions. Matching dimensions confirm the image
   size delivered by the driver, not the sensor's native resolution or detail.
2. **Autofocus:** Move your hand or a textured object slowly toward and away from
   the lens, then pause at each distance. Observe refocus delay, sharpness and
   hunting. The tool leaves focus controls at their driver defaults: autofocus
   availability, enabled state and speed require local observation or the
   manufacturer's camera controls.
3. **Motion:** Move your hands quickly across the image. Look for motion blur,
   repeated-looking frames and stuttering; compare with slower movement.
4. **Field of view:** At a fixed camera position, inspect how much of your desk
   and room fit in the frame. This is a framing check, not a calibrated optical
   FOV measurement. Optical angle requires a separate calibration.
5. **Lighting:** Run separate tests in bright, normal and dim lighting, keeping
   camera position, requested mode and movements consistent. Allow exposure and
   focus to settle, then observe sharpness, noise, blur and measured rate for
   at least 10–20 seconds per condition. Dim light may increase exposure time.

To retain console measurements alongside a run:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py 2>&1 | Tee-Object -FilePath camera\captures\normal-light.txt
```

Run the tester once first so the captures directory exists before using that
logging command. Name logs for each lighting condition and requested mode.

## Interpreting results

- **Requested FPS:** The target passed to the driver, 60 by default.
- **Driver-reported FPS:** The driver's `CAP_PROP_FPS` value. Zero, negative,
  NaN or infinite values are displayed as unavailable. Even a positive value
  can be misleading; it is a driver claim, not a measurement.
- **Application preview-loop FPS:** Successful frame reads divided by elapsed
  `time.perf_counter()` time. Live rates are non-overlapping windows of roughly
  two seconds. A warning appears below 80% of the requested FPS (below 48 for a
  60 FPS request). This threshold indicates a shortfall relative to the target,
  not an independently established hardware failure.

On exit, the console reports requested settings, all observed frame dimensions
and their counts, driver FPS, overall average FPS, minimum/maximum completed
measurement-window FPS, total duration and successful frame count. The overall
average includes startup reads, final partial windows and read/preview/save
overhead. Min/max exclude the final incomplete window; they are unavailable
when no window reaches two seconds. Duration covers the capture loop, excluding
device setup and cleanup. A failed first read produces a zero-frame summary;
failure to open the camera reports an error without fabricated measurements.

Application FPS does **not** definitively measure true sensor FPS: buffering,
duplicate exposures, USB bandwidth, driver behavior, exposure time, preview
rendering and screenshot encoding can affect the result. This tool does not
detect unique sensor exposures. For comparison, avoid saving screenshots during
the timed portion and repeat runs with the same settings and lighting.

## Troubleshooting and scope

If opening fails, check the USB connection, Windows camera privacy permissions,
and whether another app is using the webcam. Try another nonnegative camera
index. If a requested mode is rejected or performs poorly, compare 1080p/30 and
720p/60, another USB port, and brighter lighting. MJPEG is requested first, but
the driver may use another format; the reported FourCC is printed when available.
The test continues with negotiated settings when a property request fails.

This Windows test supports Media Foundation (default) and DirectShow and requires
a local desktop and attached camera for the interactive preview.
It does not verify hardware claims without actual webcam measurements and does
not implement hand tracking, face detection, voice control or motor integration.

## Local hardware benchmark findings

The project owner's hardware tests on Windows with the UGREEN USB autofocus
webcam measured the following application capture throughput:

| Backend | Captured resolution | Measured FPS |
| --- | --- | --- |
| DirectShow | 1920 × 1080 | Approximately 5 |
| Media Foundation (MSMF) | 1920 × 1080 | 59.97 |

The MSMF benchmark captured **600 frames over 10.005 seconds**, with an average
frame read time of **16.655 ms**. These results support making MSMF the default
for this tested setup. They point to a difference in the backend capture paths;
they do not establish the precise cause of DirectShow's slower performance.

The MSMF FOURCC readback was **inconclusive**. These results do not verify MJPEG
or any other underlying transport format, even though the program requests MJPG
by default. Measured application throughput also does not prove unique sensor
exposures. Other camera models, drivers and systems may behave differently.
The automated tests use mocked hardware and do not repeat these physical tests.

## Diagnosing low FPS

All existing preview commands and S/Q/H controls still work. The black text panel
and full-resolution screenshots are preserved. Preview runs now report cumulative
mean and maximum milliseconds per call for `cap.read`, resize, overlay, `imshow`
and `waitKey`, every measurement interval and on exit. Timing includes startup;
ignore the first intervals when judging settled preview behavior. `imshow` and
`waitKey` are reported separately; GUI event handling can happen during `waitKey`.
Their sum is useful when assessing display cost. The rate is the application's
preview loop rate, not the monitor's refresh rate or an isolated capture rate.
Timing totals exclude console logging, screenshots and other small loop costs,
so they need not add up exactly to elapsed time. Avoid screenshots while profiling.

Run these commands one at a time from the repository root. They create parent
log directories automatically and append to log files without changing images.

Profile the original 1080p/60 DirectShow preview:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --backend dshow --log-file camera\captures\preview-dshow.log
```

Measure headless 1080p/60 throughput with an MJPG format request using DirectShow,
discarding 3 seconds of warm-up before a 10-second measurement. The requested
format is not proof of the actual transport:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --benchmark --backend dshow --fourcc MJPG --warmup 3 --duration 10 --log-file camera\captures\headless-dshow.log
```

Repeat the successful Media Foundation configuration (now the default backend):

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --benchmark --backend msmf --fourcc MJPG --warmup 3 --duration 10 --log-file camera\captures\headless-msmf.log
```

Try uncompressed YUY2 at a lower resolution:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --benchmark --backend dshow --fourcc YUY2 --width 640 --height 480 --fps 30
```

Run the complete sequential headless comparison:

```powershell
.\.venv\Scripts\python.exe camera\camera_test.py --compare-modes --warmup 3 --duration 10 --log-file camera\captures\mode-comparison.log
```

This tests 1920×1080/60, 1920×1080/30, 1280×720/60, 1280×720/30 and 640×480/30
with both MJPG and YUY2, using both DirectShow and Media Foundation (20 runs).
In comparison mode, those fixed modes replace `--width`, `--height`, `--fps`,
`--backend` and `--fourcc`; `--camera-index`, timing and log settings still apply.
Default capture and warm-up time totals about 260 seconds, plus device setup and
any blocking reads. Each handle is released before the next run, including after
failures. Failed runs are logged and the comparison continues; any failure gives
a nonzero exit code. Ctrl+C stops the entire comparison and releases the handle
once the native call returns. Backends may enumerate devices differently: with
multiple webcams, confirm each backend's index selects the UGREEN camera using
the preview before comparing. Close other camera apps before each run.

The headless loop has no preview, resizing, overlays, keyboard polling or image
saving. It only reads frames and records lightweight timing, counts and frame
dimensions. Warm-up reads do not count toward its FPS or read timing. The actual
measured duration is logged and may exceed the requested duration by the final
blocking read. Longer warm-up (for example `--warmup 8`) may be needed for exposure
to settle. The program cannot guarantee a particular driver has settled, enforce
a portable DirectShow/MSMF read timeout, or prove unique sensor exposures.

### Configuration evidence

Logs show camera index, selected and reported backend, requested dimensions/FPS/
FOURCC, every `cap.set()` acceptance result, driver property readbacks and actual
frame dimensions. Readbacks are sampled after configuration and after the first
preview frame, or after warm-up and measurement in a benchmark. Unsupported
readbacks are logged as unavailable. A comparison row flags rejected requests,
unknown readbacks or mismatches instead of silently attributing a fallback's rate
to the requested mode. Even agreeing readbacks do not verify the advertised mode.
FOURCC is the driver's reported transport format; OpenCV normally returns decoded
BGR images. It is not direct evidence of the wire format. `MJPG` is the FourCC
spelling for MJPEG.

### Choosing the next step from your measurements

| Observed result | Interpretation and next step |
| --- | --- |
| Headless is fast; preview is near 5 FPS | Check the dominant preview timing. Large resize/overlay times suggest CPU work; large imshow/waitKey times suggest the GUI/event path. Target that stage before changing capture architecture. |
| Both are near 5 FPS and read takes about 200 ms | The delay is in or below OpenCV's read path, which includes waiting, decoding and conversion. Compare formats/backends, then repeat under bright light and on a direct USB port. It does not isolate the sensor itself. |
| MJPG is much faster than YUY2 with matching readbacks | Investigate USB bandwidth and uncompressed mode limits. A fallback or unknown FOURCC prevents a firm format comparison. |
| Only one backend is fast | Use the faster backend for a confirming preview run with matching readbacks. This points toward backend negotiation or conversion differences. |
| Lower resolutions or 30 FPS perform normally | Check exact supported combinations for the camera model, USB connection and format; the advertised maxima may require a specific mode. |
| Bright light restores throughput | Investigate exposure/low-light compensation using the camera's controls. The tester does not change exposure or autofocus. |
| Rejected requests, fallback dimensions or mismatched FOURCC | Treat the requested mode as unverified. Compare the actual values before drawing conclusions. |

The table gives diagnostic hypotheses; the separate local benchmark findings
above are measurements reported by the project owner. No physical webcam tests
were run by the implementation agent. For background,
[OpenCV documents property acceptance limits](https://docs.opencv.org/4.10.0/d8/dfe/classcv_1_1VideoCapture.html),
[Microsoft describes MJPEG decoding and YUY2's 16 bits per pixel](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/mjpeg-at-source-autodecode-for-uvc),
and [Microsoft explains how low-light exposure priority can lower frame rate](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/ksproperty-cameracontrol-auto-exposure-priority).

## Checks without a webcam

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m compileall -q camera
.\.venv\Scripts\python.exe -m unittest discover -s camera -v
```

These checks use synthetic frames, controlled timestamps and a mocked camera.
They cover arguments, FPS calculations, missing driver FPS, summaries, preview
scaling, PNG preservation, timing aggregation, warm-up exclusion, FOURCC readback
mismatches and sequential camera failure/cleanup paths. They do not access
or verify a physical webcam. Actual resolution, FPS, autofocus, motion quality,
lighting behavior and framing must be tested locally with the procedure above.
