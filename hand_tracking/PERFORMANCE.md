# Recognition performance: Phase 3.4 states and existing recognition

## Phase 3.4 state-management overhead

`--gesture-states` reuses raw static/pinch results and their shared cached features.
`state_management` measures validation, continuity, arbitration, transitions and
immutable event creation separately. The stage is included in overall and
per-hand-count profiles, even for zero-hand frames. Drawing the extra state row is
included in `landmark_drawing`; optional event logs are outside the engine timer
but included in end-to-end FPS. No additional inference/feature extraction,
threads, models, image copies or dependencies are introduced.

An interleaved two-hand synthetic comparison (100 warm-up/1000 measured samples
per configuration, five repeated approach/release poses, alternating order,
disabled Profile collection and no logs) measured ms per observation:

| Work | Mean | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Static + pinch recognition bridge | 1.268 | 1.065 | 2.372 | 3.834 |
| Bridge + state manager | 1.351 | 1.111 | 2.471 | 4.283 |
| State manager portion | 0.044 | 0.036 | 0.085 | 0.174 |

These exclude camera, inference, smoothing, rendering and GUI. Host scheduling
noise affects samples and the total difference; this is not a physical FPS or
accuracy result. Default 100 ms static confirmation adds intentional interaction
latency independently of the small processing cost. Pinch transitions have no
additional delay. The ~35+ FPS target still requires the owner's webcam test.

Compare runs sequentially using the [Phase 3.4 commands](../gestures/README.md#manual-acceptance-and-benchmarking)
with the same hand count, movement, lighting and capture/inference settings. Disable
all debug flags. JSON `gesture_states` separates measured event/state counts from
shutdown cancellations; warm-up affects continuity but is excluded from counters
and timing samples. Reports contain summaries, not an unbounded event journal.

## Earlier Phase 3.3 measurements

Phase 3.3 adds synchronous opt-in `--pinch`, independent of `--gestures`. Both
channels share the smoothed observation and one extraction per hand. Separate
`pinch_processing` includes cached measurement validation and conservative state
tracking; `pinch_features` appears only in pinch-only runs (combined runs share
`gesture_features`). New overlay work remains in `landmark_drawing`. All stages
are included in existing end-to-end/FPS/per-hand-count timings and warm-up rules.

A two-hand interleaved host comparison (100 warm-up/1000 measured samples per
configuration, five repeated approach/release poses, alternating order, disabled
Profile collection) measured mean/p50/p95/p99 in ms:

| Work | Mean | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| Static bridge | 1.479 | 1.042 | 3.906 | 5.692 |
| Static bridge + pinch | 1.555 | 1.112 | 4.186 | 6.060 |
| Pinch portion of combined run | 0.105 | 0.072 | 0.279 | 0.405 |

This includes SDK-result adaptation, geometry and rules, but excludes camera,
inference, smoothing and preview. Host scheduling noise affects tails; it cannot
predict physical accuracy, responsiveness or webcam FPS. The target is ~35+ FPS
against the owner's ~36 FPS static baseline. Follow the [sequential preview
benchmark commands](../gestures/README.md#manual-calibration-and-acceptance-checklist)
with the same lighting/motion/hand count; disable both diagnostic flags for FPS
comparisons. The new pinch implementation has not been physically tested.

## Earlier Phase 3.2 measurements

The owner subsequently measured approximately **36 FPS with recognition** and
accepted its overhead. The targeted POINTING calibration adds no capture/GUI/model
changes. Its optional `--gesture-debug` logs sampled numeric checks once per two
seconds; keep it disabled for performance comparisons. JSON records that flag.
In a sequential cached-feature two-hand check (100 warm-up/2000 measured iterations,
no camera/feature extraction/GUI), original vs calibrated debug-off rule evaluation
measured mean/p95 **0.021/0.035 ms** vs **0.053/0.107 ms**. These host timings do not
establish current webcam FPS or accuracy; local validation is still required.
The remaining measurements below record the original Phase 3.2 implementation.

The owner's verified Phase 2.5 two-hand comparison was 28.98 FPS for the original
GUI path and 38.77 FPS with native Win32 polling. Gesture recognition is opt-in
with `--gestures`; `--no-gestures` (default) skips the adapter/features/classifier.
The capture backend, model, inference size, EMA and event pump are preserved.

New per-frame stages are `gesture_features` (adaptation plus geometry),
`gesture_classification` (rules/results) and their containing `gesture_total`.
They retain all existing timing statistics and warm-up behavior, appear in
per-hand-count profiles, and are included in existing processing/loop/FPS timing.
JSON also records gesture settings, thresholds and measured classification counts.

Synthetic measurements in the existing environment used two articulated fabricated
hands, 100 warm-up and 1000 measured recognition iterations, without camera,
inference or GUI. All values are milliseconds per two-hand frame:

| Stage | Mean | p50 | p95 | p99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Adaptation/features | 1.006 | 0.956 | 1.338 | 1.713 | 2.495 |
| Static rules/results | 0.024 | 0.022 | 0.032 | 0.048 | 0.103 |
| Total recognition | 1.030 | 0.979 | 1.366 | 1.742 | 2.540 |

Separate preview-only batches (20 warm-up, 300 samples each) measured mean/p95
0.769/0.972 ms without gesture labels and 0.822/1.097 ms with them. These checks
do not measure live application FPS, physical gesture accuracy or frame age.
No physical Phase 3.2 performance claim is made. Extra work is measurable;
keeping recognition opt-in protects the established default until local tests.

See [the gesture README](../gestures/README.md#manual-webcam-validation-and-performance)
for exact PowerShell off/on commands and the manual quality checklist. Use the
same capture/inference/smoothing settings, repeat matched zero/one/two-hand
conditions, compare only completed reports and reverse order on a repeat.
Headless tracking includes recognition when enabled but excludes drawing/GUI;
compare it separately from preview FPS. Future pinches and temporal gesture
states/events are deferred to later milestones.

---

# Historical Phase 2.5: targeted GUI optimization and workload profiling

## Findings before changing the pipeline

The starting point is Phase 2.4, commit `9cbbb77`. The owner's physical tests
reported 42.00 FPS with no hands, 28.42 with one, 28.76 with two, and 28.87 with
two hands plus smoothing. Prior full-resolution stage means were approximately
15.96 ms inference, 11.02 ms `waitKey`, 4.17 ms camera read and 0.49 ms drawing.
These supplied measurements identify inference and GUI scheduling as the main
candidates; they do not provide per-condition stage profiles or prove a cause.
Smaller inference images did not materially improve application FPS locally.

The existing pipeline already reuses BGR/RGB/preview buffers, downsizes before
RGB conversion when requested, and draws on a preview made from the original
capture. Inspection found no duplicate full-frame color conversion. Constructing
the public MediaPipe Image and synchronous result objects still costs work;
private native pointers or speculative zero-copy reuse would add lifetime risks.
Rendering at the supplied 0.49 ms mean offers little headroom. Those paths,
confidence thresholds, model, VIDEO/CPU/two-hand options and EMA are preserved.
Full inference and 1080p60 MSMF capture remain the defaults.

### Why one hand can cost nearly as much as two

The upstream MediaPipe graph checks whether tracked rectangles reach the configured
hand limit before skipping palm detection. With a limit of two, one tracked hand
can still require a detector pass looking for another. Two tracked hands can skip
that pass; losing tracking can trigger it again. No-hand frames also search, but
have no detected hands for landmark processing, smoothing or skeleton drawing.
This is a plausible explanation of the nonlinear cost, based on
[MediaPipe's graph implementation](https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/mediapipe/tasks/cc/vision/hand_landmarker/hand_landmarker_graph.cc).
It does **not** demonstrate which native paths or costs occurred in the installed
binary during the owner's runs. Python result conversion also varies with hand
count. Per-observed-hand-count timings now help investigate correlations; they
cannot identify internal detector invocation, ground truth or tracking accuracy.
Reducing the hand limit or confidence thresholds would change behavior and is
not used as a performance shortcut.

## Changes and measured GUI-only effect

OpenCV documents that a `waitKey` delay is a minimum subject to OS scheduling,
and that an event pump must be called for a responsive window. The native Win32
implementation offers `pollKey` to process queued events without the waitKey
sleep path. Other UI backends can implement polling differently, so the default
uses it only when `currentUIFramework()` reports `WIN32` and the API is callable.
See [HighGUI documentation](https://docs.opencv.org/4.x/d7/dfc/group__highgui.html)
and [Win32 implementation](https://raw.githubusercontent.com/opencv/opencv/5.x/modules/highgui/src/window_w32.cpp).

- `--gui-mode auto`: one native Win32 `pollKey` call per processed frame; no
  busy-wait loop, global timer changes, added sleep or removal of event processing.
- `--gui-mode waitkey`: preserve the earlier `waitKey(1)` GUI path for comparison.
- `--gui-mode pollkey`: request native polling explicitly. Unsupported UI builds
  fall back with a warning. A polling runtime error switches to waitKey as well.
- Q/H and window close handling stay in the synchronous loop. Effective backend,
  mode and fallback reason are logged and saved. Slow capture/inference can still
  delay event processing; polling cannot fix a blocking camera read.
- `--benchmark --headless` runs capture, preparation, inference and smoothing,
  with no rendering or GUI work. This isolates throughput costs and has a timed
  exit; Ctrl+C interrupts. Q/H and raw comparison overlays require a preview.

Before pipeline edits, a native Win32 GUI-only comparison used a synthetic static
1100×619 image, a **20 ms sleep between frames in the probe only**, 10 warm-up
iterations and 100 measured iterations per mode, in the installed Windows /
Python 3.13.7 / OpenCV 5.0.0 environment:

| Event API | Mean ms | p50 ms | p95 ms | p99 ms | Maximum ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| waitKey(1) | 3.955 | 1.849 | 12.153 | 13.153 | 14.201 |
| native pollKey | 1.745 | 1.790 | 2.566 | 2.816 | 6.268 |

`imshow` mean/p95 was 0.605/0.992 ms with waitKey and 0.667/1.012 ms with pollKey.
These measurements support reducing avoidable GUI waiting in this environment.
They are **not live webcam, inference, CPU or application-FPS comparisons** and
must not be subtracted from the owner's supplied live timings to predict FPS.
Scheduling and window state affect results. No physical before/after tracking
benchmark or accuracy acceptance test was performed during implementation.

## Repeatable Phase 2.5 hardware validation

Run from `C:\Users\Darsh\VisionControl` in PowerShell. Normal tracking:

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker
```

The following compares the old GUI path, optimized path and headless pipeline,
sequentially with identical capture/inference/EMA settings. At each prompt,
prepare the requested number of hands for the warm-up and measured interval.
The condition in the filename describes your intended workload; the report
records what the model actually detected.

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
foreach ($condition in @('zero', 'one', 'two')) {
    foreach ($mode in @('waitkey', 'auto', 'headless')) {
        Read-Host "Prepare $condition hands for $mode; press Enter to start (3s warm-up)"
        $extraArgs = if ($mode -eq 'headless') { @('--headless') } else { @('--gui-mode', $mode) }
        & .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --benchmark --camera-index 0 --backend msmf --width 1920 --height 1080 --fps 60 --inference-resolution full --smoothing --smoothing-alpha 0.75 --warmup 3 --duration 30 @extraArgs --report "hand_tracking\benchmarks\${runStamp}_${condition}_${mode}.json"
        if ($LASTEXITCODE -ne 0) { throw "Run failed or interrupted: $condition / $mode" }
    }
}
```

Review `status`: compare only `completed` runs; Q/window close save a `stopped`
partial report and Ctrl+C saves `interrupted` with exit code 130. Each process
releases its camera/model before the next starts; files are never overwritten.
Use at least three repeats, reverse GUI mode order on a repeat, keep lighting,
hand positions/movement, distance, USB connection and power mode consistent, and
close other camera applications. Headless has no visual feedback; establish the
framing in a preview first and check its detected-hand histogram afterward.

```powershell
Get-ChildItem hand_tracking\benchmarks\*.json | ForEach-Object {
    $r = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    [pscustomobject]@{
        Run = $_.BaseName
        Status = $r.status
        Mode = $r.execution_mode
        GUI = $r.gui.effective
        Capture = ($r.capture_resolution_frames.PSObject.Properties.Name -join ', ')
        Input = ($r.inference_resolution_frames.PSObject.Properties.Name -join ', ')
        FPS = $r.average_application_fps
        InferenceMeanMs = $r.timings.inference.mean_ms
        InferenceP95Ms = $r.timings.inference.p95_ms
        GuiMeanMs = $r.timings.gui_total.mean_ms
        GuiP95Ms = $r.timings.gui_total.p95_ms
        LoopMeanMs = $r.timings.end_to_end.mean_ms
        LoopP95Ms = $r.timings.end_to_end.p95_ms
        SmoothingMeanMs = $r.timings.smoothing.mean_ms
        CpuOneCorePercent = $r.resources.process_cpu_percent_of_one_core
        CpuMsPerFrame = $r.resources.process_cpu_ms_per_frame
    }
} | Format-Table -AutoSize
```

Headless GUI columns are absent/null, not zero-cost display measurements. Reports
also retain mean, p50, p95, p99 and maximum for every measured stage. In
`timings_by_detected_hands`, each group's stage percentiles use its last 8192
samples; its means/maxima cover all its measured samples. Warm-up is excluded.
The groups are observational strata within a run, not separate controlled tests.

Whole-process `time.process_time()` includes native worker threads. CPU percent
is CPU seconds divided by measured process wall time, times 100: **100% is one
fully occupied logical core**, so values can exceed 100%. This is not whole-system
utilization or a memory/GPU measurement. `process_wall_seconds` includes final
loop bookkeeping; report/cleanup work is excluded. Compare CPU milliseconds per
frame as well as FPS and CPU percent: higher throughput can raise CPU utilization
without raising per-frame work. Partial/error runs can include unfinished work
and should not be used for acceptance comparisons.

For preview acceptance, check Q/H, closing, dragging/resizing the window,
responsive labels, one/two hands, fast motion, crossing, loss/reappearance and
raw markers (`--show-raw-landmarks`). Confirm unchanged quality and no noticeable
extra lag, comparable or improved FPS, and no significant CPU increase without
benefit. The 40–45 FPS target is unverified; use the waitkey baseline if polling
does not benefit your actual workload.

## Timing and latency limits

`processing` covers post-read preparation through smoothing and, when enabled,
rendering/GUI. `end_to_end` covers host read-start through completion of those
stages. `frame_interval` covers successive completed frames and also includes
between-frame accounting and window checks. `gui_events` times the actual event
pump; `gui_total` includes imshow plus the pump. API-specific `waitKey`/`pollKey`
keys remain for compatibility. The same report can contain both after fallback.
These overlapping timings must not be summed. `average_application_fps` is
completed frames divided by elapsed measurement wall time; headless throughput
is not display FPS, and neither is necessarily sensor FPS.

The camera/driver can buffer frames, and a fast read can return an old frame.
Neither host timing nor VIDEO timestamps establish capture age. Removing a GUI
wait may instead increase time waiting in the next camera read. Compare complete
runs, not just one reduced stage. A visible stopwatch can help check gross lag;
true camera-to-display timing needs external measurement. No threads, async
inference, frame dropping or buffer flushing are introduced. If measured queue
age remains a problem, a future latest-frame capture worker could improve
freshness but would discard intermediate frames and require new synchronization,
timing and recovery tests. That change is deferred pending hardware evidence.

---

# Historical Phase 2.3 profiling and benchmark procedure

The sections below record the earlier milestone's synthetic experiments. For
current Phase 2.5 validation, use the procedure above; historical commands now
use the Phase 2.5 default GUI path unless `--gui-mode waitkey` is added.

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
