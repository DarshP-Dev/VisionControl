# Phase 2.3 profiling and benchmark procedure

Phase 2.4 adds optional display smoothing, enabled by default at alpha 0.75.
Its overhead is reported separately as `smoothing` and included in `processing`
and `end_to_end`. Add `--no-smoothing` to the commands below when reproducing the
Phase 2.3 raw pipeline, or use the raw/EMA comparison commands in README.md.
Disable optional raw-point markers for performance comparisons. The following
synthetic measurements describe Phase 2.3, before smoothing was added.

No physical webcam benchmarks were run during this implementation. Improvements
in application FPS, detection quality and sensor-to-display latency must be
verified locally. All old camera settings, two-hand behavior and controls remain.

## Before changing the pipeline

The starting point was Phase 2.2 plus the resolution UI change (commit 9337207).
It converted every 1920×1080 frame to RGB, constructed a MediaPipe Image, then
resized the original BGR capture separately for display. RGB and preview arrays
were allocated every iteration. Landmark drawing used 21 lines and 42 circle
calls per hand, including point borders. Existing timings combined some stages
and had means/maxima, so they could not isolate all costs or long-tail behavior.

The owner's hardware baselines were 35.81 application FPS for one hand with
about 13.51 ms inference, and approximately 31 FPS for two hands. Neither isolates
all stages. Capture was previously verified near 60 FPS using MSMF at 1080p.

Before pipeline edits, the following synthetic timings were measured on the
existing Python 3.13.7 / OpenCV 5.0.0 Windows environment. They are not live camera
measurements. The real model processed a uniform gray 1920×1080 RGB image with no
hands; a separate fabricated two-hand result exercised the rendering path.
Ten iterations were excluded, followed by 100 measured iterations:

| Stage | Mean ms | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| BGR-to-RGB plus MediaPipe Image construction | 7.131 | 10.409 | 12.832 |
| Real inference, blank image / no hands | 39.972 | 67.216 | 88.904 |
| Existing preview, fabricated two-hand result | 4.265 | 5.398 | 6.983 |

A separate 300-sample rendering-only check, after 30 warm-up iterations, gave:

| Stage | Mean ms | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| Preview resize | 1.345 | 1.767 | 2.275 |
| Landmark mapping, drawing and wrist labels | 0.650 | 0.913 | 1.372 |
| Status text overlay | 0.069 | 0.097 | 0.360 |

Camera read, GUI cost and actual application FPS were not measured here. These
separate microbenchmarks were not simultaneous and must not be summed or treated
as a physical camera profile. Blank-image inference repeatedly runs detection;
it is a different workload from tracking real hands. The fabricated rendering
result used repeated points and does not test tracking quality. Scheduling and
CPU load affect the numbers. The local live profile remains the deciding evidence.

## Targeted changes

- Optional aspect-preserving downscale happens before RGB conversion and MediaPipe
  image creation. Full-frame inference remains the default until hardware tests
  justify changing it. Bounds include full, 1280×720, 960×540 and 640×360.
- RGB, reduced BGR and preview buffers are reused. Full inference skips resize
  and does not allocate an unused reduced-image buffer. Smaller captures use a
  single copy into the reusable display buffer so overlays never alter capture.
- Display is always resized from the original BGR capture; lower inference size
  does not lower preview quality. No crop/pad means normalized landmarks map onto
  the preview identically, including with non-16:9 capture modes.
- The drawing algorithm and antialiased skeleton/point/label appearance are
  preserved. The small rendering baseline did not justify more intrusive batching
  or reduced-quality drawing. Tiny text costs did not justify complicated caches.
- Profiling separates formerly combined stages. Samples are bounded, no
  percentiles are computed inside the frame loop, benchmark windows avoid periodic
  logging, and normal slow-FPS warnings are emitted on entering a slow period.

In a subsequent synthetic check (10 warm-up + 100 samples per size), the new
individual stage means/p95s were as follows. The native model still saw a blank
image with no hands. All values are milliseconds; **none are camera FPS**:

| Inference image | Resize mean/p95 | RGB mean/p95 | MP Image mean/p95 | Inference mean/p95 |
| --- | ---: | ---: | ---: | ---: |
| Full 1920×1080 | 0.011 / 0.013 | 0.956 / 1.270 | 3.972 / 4.831 | 38.983 / 54.626 |
| 1280×720 | 3.078 / 4.205 | 0.297 / 0.422 | 1.349 / 1.627 | 20.158 / 25.699 |
| 960×540 | 0.797 / 1.163 | 0.299 / 0.425 | 1.318 / 1.654 | 36.589 / 50.730 |
| 640×360 | 4.526 / 6.874 | 0.281 / 0.510 | 0.524 / 0.612 | 46.202 / 55.992 |

These results show reduced image wrapping work, but also substantial resize and
inference variation. They do not establish an optimal size or a live FPS gain.
The 640×360 resize was more expensive than 960×540 in this check: fewer pixels
does not guarantee a faster complete pipeline. Shrinking uses INTER_AREA; model
preprocessing still occurs internally. Larger input also does not automatically
imply higher detection accuracy. Test small/distant hands, rapid motion, crossing
and reentry visually at every candidate size.

## Repeatable local comparison

From the repository root, close other webcam apps and keep the USB port, camera
index, lighting, camera position, exposure settings and computer power mode fixed.
First establish a full-inference application baseline with the new stage profile:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --backend msmf --width 1920 --height 1080 --fps 60 --inference-resolution full --warmup 3 --duration 30 --report hand_tracking\benchmarks\baseline-full-01.json
```

Then compare all four resolutions in separate, sequential processes:

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
foreach ($mode in @('full', '1280x720', '960x540', '640x360')) {
    & .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --backend msmf --width 1920 --height 1080 --fps 60 --inference-resolution $mode --warmup 3 --duration 30 --report "hand_tracking\benchmarks\${runStamp}_${mode}.json"
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed or was interrupted: $mode" }
}
```

Each process warms the full pipeline and displays every acquired frame; warm-up
is excluded from reported samples and average FPS. No camera handles overlap.
The timing period includes acquisition, inference, drawing and GUI. Stop with Q
or close the preview to save a partial report; Ctrl+C saves an interrupted report
and returns exit code 130. Review `status` before comparing rows. Existing files
are never overwritten. Rerun with a fresh stamp/name and reverse mode order on a
repeat to reduce ordering, scheduling and thermal bias. Use at least three repeats.

During each run, follow the same workload: keep two hands visible and repeat a
similar movement pattern. Run separate comparisons for one hand, two hands and
no hands. Lighting, hand visibility, distance, occlusion, movement and redetection
change inference cost. The JSON hand-count histogram helps identify unequal runs;
it counts model detections, not ground truth or accuracy. Check quality visually.

Example summary of saved runs:

```powershell
Get-ChildItem hand_tracking\benchmarks\*.json | ForEach-Object {
    $result = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    [pscustomobject]@{
        Run = $_.BaseName
        Status = $result.status
        Capture = ($result.capture_resolution_frames.PSObject.Properties.Name -join ', ')
        Inference = ($result.inference_resolution_frames.PSObject.Properties.Name -join ', ')
        FPS = $result.average_application_fps
        InferenceMeanMs = $result.timings.inference.mean_ms
        InferenceP95Ms = $result.timings.inference.p95_ms
        LoopMeanMs = $result.timings.end_to_end.mean_ms
        LoopP95Ms = $result.timings.end_to_end.p95_ms
    }
} | Format-Table -AutoSize
```

Normal use remains unchanged, or opt into a candidate size:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --inference-resolution 960x540
```

## Reading profiles and investigating latency

Every stage reports all-measurement mean, maximum and count. p50/p95/p99 use the
latest 8192 samples **per stage** (all samples in typical 30-second runs). Sample
count is explicit. Percentiles are empirical, not confidence intervals; a short
run's maximum is not a universal worst-case bound.

- `camera_read`: successful OpenCV read time, including waiting/decode/conversion.
- `inference_resize`, `bgr_to_rgb`, `mediapipe_image`: separate input preparation.
- `inference`: blocking MediaPipe call.
- `preview_resize`: original capture to display-buffer resize or copy.
- `landmark_drawing`: result mapping, skeletons, points and wrist labels.
- `text_overlay`: status/help construction and drawing.
- `imshow`, `waitKey`: separate GUI costs; event handling can occur in waitKey.
- `processing`: read completion through GUI wait completion, excluding acquisition.
- `end_to_end`: host read-start through GUI wait completion, including acquisition.

`processing` and `end_to_end` contain other stages and must not be added to them.
Average application FPS uses measured frames / elapsed monotonic wall time,
including small loop bookkeeping, checks and instrumentation. It can differ from
the reciprocal of mean `end_to_end`. First-frame logs and startup are included in
normal interactive runs; timed benchmarks exclude warm-up. Device/model setup,
cleanup, percentile reporting and JSON writes are outside the timed frame loop.

Profiles identify host work and stalls, not actual frame age. VIDEO timestamps
are host receive times, not exposure timestamps. At 60 FPS capture and roughly
31 FPS processing, the synchronous consumer is slower than capture; whether
MSMF/OpenCV queues frames or supplies recent ones depends on the backend/driver.
Fast reads can be buffered and slow reads can include decoding. Read timing alone
does not prove stale frames. No buffer-size property is assumed effective.

To investigate stale images locally, place a visible rapidly changing stopwatch
in the camera scene and compare it with the preview under full and reduced input
sizes. This is a rough visual check; actual sensor-to-display latency needs
external timing/calibration. Reducing preparation work may help host latency but
does not guarantee a fresher captured frame.

No threads, async calls, manual frame dropping or buffer flushing are added.
A future latest-frame capture worker could reduce queue age, but would drop
intermediate frames, add synchronization/resource complexity, change timing
semantics and need its own accuracy/recovery tests. That is not implemented in
Phase 2.3; first use the local benchmark evidence.

References: [Google's synchronous VIDEO API and normalized landmarks](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python),
[OpenCV resize documentation](https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html).
