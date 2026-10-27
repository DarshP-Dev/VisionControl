# Phase 3.9 — Performance, frame pacing and background execution

## Scope and initial state

The working tree was clean on `main`, at Phase 3.8 commit
`46e858f8ab3e1cbb366bc0685932e46db742ccd5`. The earlier description of Phase 3.8
as uncommitted was outdated: that phase had already been committed and pushed.
No existing uncommitted work was present. Phase 3.9 was initially left unstaged
for physical testing; the owner subsequently authorized committing and pushing
this phase using the DarshP-Dev account. Physical acceptance remains unverified.

Initial tests: camera **16**, gestures **163**, hand tracking **211**, controls
**252**, total **642**. Root discovery runs 626; the camera directory needs its
separate discovery command. Final results: **670 passing** (16 / 165 / 230 / 259).
No existing test was removed or skipped. GUI fixtures now explicitly mock window
existence, and close assertions reflect stopping before rendering and input.

Environment used for synthetic measurements: Python 3.13.16, OpenCV 5.0.0,
NumPy 2.5.4, MediaPipe 1.1.1, 16 logical CPUs. Dependencies were not changed.
There were no webcam, real hand, real cursor, background/minimized throughput,
or inference-latency measurements in this task. A native synthetic-window smoke
check on the installed WIN32 backend passed: owned HWND bound successfully,
focused → minimized → restored/focused → closed. It used generated pixels,
`ShowWindow` and an owned-window close message; no camera or SendInput. This
validates lifecycle detection, not tracking or cursor throughput. Physical
acceptance remains pending. Automated runs send no Windows mouse or keyboard input.

## Findings: confirmed and unresolved

Confirmed by code inspection:

* One synchronous main loop runs capture, inference, recognition, controller,
  rendering and HighGUI. Rendering delays the next capture/inference iteration.
* Controls already preceded drawing. Moving controls before drawing was therefore
  not a new optimization to make.
* Every frame was resized, annotated and passed to `imshow`, including minimized
  frames. This work is now skipped while minimized or hidden.
* GUI events were consumed after controller input. A close or D queued during
  inference could therefore be consumed after another controller update. The
  pump and lifecycle check now precede input dispatch.
* Model timestamps described read-completion time, but controller validation did
  not independently bound time spent processing that observation. The new host
  age gate closes that gap without predicting or interpolating any input.
* Interactive execution previously accumulated stage statistics even with no
  benchmark/report requested. Detailed accumulation is now opt-in.

Confirmed by profiling/benchmarks:

* A four-hand, 600-iteration cProfile run spent about 2.94 of 5.49 profiled
  tracking seconds in feature extraction. `finite_number` was called about
  1.35 million times; `numbers.Real` ABC checks were a substantial cost.
  These are profiler-instrumented timings used to locate costs, not normal FPS.
* A common built-in float/int validation path substantially reduces synthetic
  gesture, association and smoothing costs. Other numeric scalar types retain
  the original validation path. Booleans, non-finite values, strings, complex
  values and overflowing conversions remain rejected.

Not confirmed: a Windows background FPS cap, Efficiency Mode, CPU scheduling,
power management, camera backlog, inference spikes, or HighGUI as the primary
cause of the owner's observed choppiness. Focus-specific root cause and physical
smoothness cannot be established from synthetic processing. The diagnostics below
are designed to distinguish these possibilities. No process/thread priority,
power setting, registry setting or scheduling policy was changed.

## Complete processing path

All these stages still share the main thread; no workers or frame queues were
introduced. The existing independent global emergency/watchdog thread remains.

| Work | Location / diagnostic stage |
| --- | --- |
| Blocking MSMF `cap.read()` | `camera_read`; capture delivery intervals |
| Aspect-preserving resize, BGR→RGB | `inference_resize`, `bgr_to_rgb` |
| Construct MediaPipe image; synchronous VIDEO inference | `mediapipe_image`, `inference` |
| Adapt observations, ID descriptors/global matching when enabled | `observation_adaptation`, `association` |
| Raw/EMA landmark processing | `smoothing`; legacy path includes its handedness association |
| Extract shared geometry once per observed hand | `gesture_features` / `pinch_features` |
| Static recognition | `gesture_classification`; `gesture_total` includes features and static rules |
| Pinch hysteresis | `pinch_processing` |
| Swipe, arbitration, gesture histories/events | `state_management`; nested `swipe_processing` includes motion conflict handling |
| HighGUI pump, then owned-window state | `gui_events`, `pollKey` or `waitKey`, `preview_state` |
| Safety controller, mapping, mouse/keyboard actions | `controller_processing`; nested `gesture_rearm` |
| Successful cursor move backend call | `pacing.timings.cursor_dispatch` |
| Visible preview resize/skeleton/text | `preview_rendering`; components `preview_resize`, `landmark_drawing`, `text_overlay` |
| Display submission | `imshow`; `gui_total` includes display and event pump, excludes overlay rendering |

`processing` starts after capture returns; `end_to_end` includes capture.
`frame_interval` measures consecutive loop completions, including loop bookkeeping.
Nested stages must not be added together as independent work. Arbitration is
measured within state management, not falsely reported as a separate isolated stage.
On close/error, overall stage counters can include work from the final incomplete
iteration; completed-frame workload/state strata exclude that unfinished frame.
HighGUI can still block processing through event dispatch/painting, and capture
and inference are still synchronous. The change does not claim to eliminate all
possible GUI or driver stalls.

## Camera, model and recognition decisions

MSMF, 1920×1080, requested 60 FPS, MJPG request, CPU delegate, VIDEO running mode,
full inference default, available inference bounds, two-hand default, and all
landmark/cursor smoothing defaults are preserved. Capture FPS requests/readback
are not evidence of actual processed FPS. Model initialization stays outside the
loop. Existing reusable resize/RGB/preview buffers were inspected and retained;
there is no added frame copy, model, conversion, neural inference, or thread.

Features were already shared between static recognition, pinch and gesture state.
There is no new cross-frame feature cache. The numeric fast path removes repeated
ABC lookup work while preserving finite-value validation and all geometry math.
No gesture, pinch, swipe or association threshold changed. The bounded exhaustive
global matching algorithm, motion prediction, uncertainty retirement, nonreused
IDs, per-ID histories and loss cancellation are unchanged. They benefit from the
same cheaper validation, rather than a different identity algorithm.
Tracking-only runs continue to avoid gesture feature extraction.

## Preview lifecycle and safety

On native Win32, bind the top-level HighGUI HWND once after `namedWindow`, matching
the exact title, HighGUI class and current process PID. Use pointer-sized ctypes
signatures. Revalidate ownership on each state read; use `IsIconic` for minimized,
`IsWindowVisible` for hidden, and comparison with `GetForegroundWindow` for focus.
Never inspect foreign application titles or paths. A destroyed/invalid handle
latches closed and is never rebound. Failure to identify the owned native window
fails startup closed. The HighGUI fallback reports `visible_unknown`, never
invented focus/minimize telemetry.

The upstream [OpenCV Win32 source](https://github.com/opencv/opencv/blob/4.x/modules/highgui/src/window_w32.cpp)
shows native `pollKey` draining messages without an explicit wait, `waitKey`
containing a wait/sleep path, and `WND_PROP_VISIBLE` reporting window existence.
This source inspection is not a measured scheduling guarantee for the installed
binary. Microsoft's [IsIconic documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-isiconic)
defines the minimize test; [IsWindow cautions about handle reuse](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindow).
Creation, event pumping and ownership checks remain on the creating thread.

| State | Behavior |
| --- | --- |
| Focused | Capture, tracking, recognition, safe controls, drawing, event pump |
| Unfocused but visible | Same processing and rendering policy; no focus-based disarm or sleep |
| Minimized / hidden | Same capture, inference, recognition and safe controls; no drawing or `imshow`; still pump events |
| Restored | Draw the current frame; keep current model, histories and controller; no stored preview queue |
| X / destroyed | Exit before that iteration's controller dispatch; disarm/release, then destroy window and release camera/model |

A close event queued during inference is processed before input. Event pumping
still runs once per processed iteration, not on a dedicated GUI thread. A blocked
capture/model call can delay application shutdown; the existing 500 ms watchdog
and global emergency thread continue to gate input independently. No claim of
instant GUI-close response during a blocked native call is made.

The controller now receives capture-completion time in its monotonic clock domain.
An observation older than **250 ms**, future-dated or invalid disarms, resets
anchors and releases owned input. Freshness is rechecked at existing input gates
and after controller work, including a slow cursor query. These failures require
manual recovery. Existing 250 ms tracking-gap logic and 500 ms watchdog remain.
The gate limits known host age; sensor/driver buffering age remains unknown.

No cursor interpolation, movement during tracking loss, new smoothing, mapping
change, active-region change, or pinch/reacquisition change is introduced. Mouse
UP cleanup remains allowed even when other input is blocked. Default legacy and
palm profiles, A/D, initial disarm, Ctrl+Shift+F10 support, emergency generations,
in-flight cancellation, left-pinch rearm/resume and confidence checks remain.
Three/four hands and experimental IDs remain observation-only, including simulation.
Headless controls remain prohibited. Minimizing alone never disarms an armed system;
tracking loss, an expired observation, emergency or a real fault still can.

## Diagnostics and report interpretation

Use existing `--benchmark --warmup --duration --report`, or the new
`--performance-profile` for an interactive bounded profile. `--report` and
`--benchmark` also enable profiling. Ordinary execution stores no detailed stage
or pacing samples and installs no cursor telemetry callback. An explicitly passed
programmatic report opts in unless `profile_enabled=False` is supplied.

Reports retain camera settings/backend/readback, inference bounds and actual
sizes, observed 0–4-hand distribution, smoothing/gesture/control settings, versions,
warmup, measurement duration, application FPS, process CPU and per-stage timing.
Additions:

* `timings_by_preview_state`: stages grouped by state observed before input.
* `pacing`: capture-delivery intervals/FPS, frame-completion intervals,
  >100 ms frame stalls, state transitions and skipped preview frames.
* Successful cursor-update intervals, backend dispatch duration and host frame age
  from read completion to dispatch return, including time in inference and GUI.
  Windows moves count only when `SendInput` succeeds, not when its gate refuses.
  Simulation moves are virtual; the report's control mode distinguishes them.
* Same-state cursor intervals are separated from transition intervals. Long gaps
  include intentional idle/gesture pauses and must not all be called stutter.
  Test with a continuously admitted cursor pose to evaluate smoothness.
* Optional end-of-run Windows working set and process-lifetime peak working set.
  CPU is whole-process percent of one logical core and CPU ms/frame, not system
  load or per-preview-state CPU. Memory includes initialization/warmup history.

Monotonic high-resolution `perf_counter` measures host durations. Means/maxima and
counts cover the entire measured run; median/P95/P99 use the latest **8192** samples
per series. State names and stage keys are bounded. No frame-by-frame disk logging,
pixels, screenshots, foreign window titles or application contents are recorded.
Percentiles/report serialization happen after processing. Sensor FPS, driver frame
age and driver-dropped frames are explicitly `null`: synchronous read delivery
cannot measure independent sensor throughput. There is no application frame queue.
Do not describe read-completion age as exposure-to-cursor latency.

A separate instrumentation microbenchmark (3 × 20,000 iterations; 12 stage adds,
state/workload completion and one cursor notification per iteration) measured
median **2.06 µs/frame disabled** and **21.88 µs/frame enabled**. This includes its
loop/clock arithmetic and excludes actual pipeline work. It does not measure
whole-application overhead, but measures the accumulation cost for that workload.

## Before/after measurements

Full selected per-run statistics, source report hashes, settings and CPU data are
preserved in [performance_reports/phase3_9.json](performance_reports/phase3_9.json).
Raw local JSON reports are retained under `hand_tracking/benchmarks/phase3_9_*.json`
(that directory was already Git-ignored). Baseline runs preceded numeric/loop
optimization. Three repeats, 100 warmup + 500 measured frames, 120-frame fixtures,
33 ms model timestamps. ID fixtures use the first N matched-scale fixed palms.
Legacy and palm use the existing default-control fixtures. Palm benchmark support
was added before collecting its baseline. The new controller benchmark supplies
host observation age, as the application now does.

All figures below are **synthetic host ms/frame**; exclude capture, conversion,
MediaPipe inference, preview/HighGUI and actual Windows input. They are not webcam
FPS or physical cursor measurements. This session's measured baseline, rather than
Phase 3.8's earlier machine-load-dependent numbers, is used for percentages.

| ID path, static + pinch + swipes | Before mean | After mean | Reduction | Before / after median run P95 |
| --- | ---: | ---: | ---: | ---: |
| 1 hand | 0.681 | 0.471 | 30.7% | 0.926 / 0.703 |
| 2 hands | 1.269 | 0.894 | 29.5% | 1.623 / 1.217 |
| 3 hands | 1.941 | 1.301 | 33.0% | 2.580 / 2.097 |
| 4 hands | 2.487 | 1.621 | 34.8% | 3.261 / 1.988 |

The ID association means fell from approximately 0.077/0.145/0.217/0.279 to
0.063/0.123/0.171/0.213 ms for 1/2/3/4 hands without matching-rule changes.
Default two-hand processing and simulated palm/absolute controller comparisons
are measured separately from the ID path:

| Legacy association, complete host workload | Before mean | After mean | Reduction | Before / after median run P95 |
| --- | ---: | ---: | ---: | ---: |
| 2 hands, static + pinch + swipes | 1.221 | 0.722 | 40.8% | 1.991 / 0.831 |
| 2 hands, simulated absolute legacy cursor | 1.194 | 0.757 | 36.6% | 1.442 / 0.894 |
| 1 hand, simulated palm cursor | 0.613 | 0.398 | 35.0% | 0.804 / 0.473 |
| 2 hands, simulated palm cursor | 1.167 | 0.771 | 33.9% | 1.398 / 0.858 |

Virtual action counts match the baselines, including 370 moves and 5 DOWN/UP pairs
per palm run (warmup included). These counts are not a proof of live input accuracy.

Means are averages of equal-sized run means. Reported P95 comparison is the median
of the three run P95 values, **not** a pooled P95. These are preliminary local
measurements with no CPU isolation; one baseline legacy repeat overlapped cProfile
diagnostics. Inspect repeat variation and rerun under comparable machine load.
Empty-hand timings can fluctuate by microseconds despite an unchanged empty path;
such percentage changes are not evidence that numeric validation worsened it.

The separate synthetic 1080p preview-policy replay compares old unconditional
drawing with the new visibility decision. Old minimized drawing averaged
0.676/0.885/1.160/1.436 ms for 1/2/3/4 skeletons. New minimized policy invokes the
renderer zero times. Focused, unfocused and restored policies retain drawing.
These are skeleton/text drawing costs, not actual minimized OS/HighGUI measurements;
the replay excludes GUI, gesture/debug overlays and scheduling. No percent FPS
or cursor-pacing improvement is inferred from skipping those calls.

## Exact PowerShell verification and hardware procedure

Run from the repository root. Choose fresh report paths; raw reports refuse overwrite.

```powershell
Set-Location C:\Users\Darsh\VisionControl
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q

# Repeat matched ID and default/control synthetic comparisons; no camera/input.
.\.venv\Scripts\python.exe -m hand_tracking.benchmark_synthetic --max-hands 4 --track-ids --frames 500 --warmup 100 --repeats 3 --report hand_tracking/benchmarks/phase3_9_owner_ids.json
.\.venv\Scripts\python.exe -m hand_tracking.benchmark_synthetic --max-hands 2 --palm --frames 500 --warmup 100 --repeats 3 --report hand_tracking/benchmarks/phase3_9_owner_legacy_palm.json
.\.venv\Scripts\python.exe -m hand_tracking.benchmark_rendering --frames 200 --warmup 20 --repeats 3 --report hand_tracking/benchmarks/phase3_9_owner_render_policy.json

# Camera + gestures with a preview, no desktop input. Capture defaults stay 1080p60 MSMF.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --benchmark --warmup 5 --duration 120 --report hand_tracking/benchmarks/phase3_9_owner_preview.json

# Palm-cursor simulation; A arms virtual input. Perform the A–E sequence below.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --benchmark --warmup 5 --duration 120 --report hand_tracking/benchmarks/phase3_9_owner_simulation.json

# Live acceptance, after simulation. Starts disarmed; A arms. Test global stop out of focus.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode live --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --benchmark --warmup 5 --duration 120 --report hand_tracking/benchmarks/phase3_9_owner_live.json

# Matched ID observation-only webcam runs. Actually show N hands; inspect detected-hands bins.
foreach ($handCount in 1,2,3,4) {
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --max-hands $handCount --track-ids --gestures --pinch --gesture-states --swipes --benchmark --warmup 5 --duration 120 --report "hand_tracking/benchmarks/phase3_9_owner_ids_${handCount}.json"
}

# Compare GUI cost: no controls in either. Use the same hands, scene and inference bounds.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --benchmark --headless --warmup 5 --duration 60 --report hand_tracking/benchmarks/phase3_9_owner_headless.json
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --gui-mode waitkey --benchmark --warmup 5 --duration 120 --report hand_tracking/benchmarks/phase3_9_owner_waitkey.json
```

For each 120-second preview run, after warmup: A focused ~20 seconds; B keep preview
visible and focus another application ~20 seconds; C minimize ~20 seconds;
D restore ~20 seconds; E click X. Closing early intentionally saves
`status: preview_closed`. Keep the selected hand and OPEN_PALM continuously visible
to the camera during cursor-pacing comparisons. Focus changes alone should not
disarm. Use D/A only for separate manual-disarm/recovery tests. For a legacy
comparison omit `--control-gesture-profile palm-cursor` and use POINTING for movement.
For manual cursor resume add `--control-cursor-resume left-pinch` to the live
command with `--control-gesture-rearm`; confirm existing Left-open/hold/release rules.

Repeat at least three times with the same hand count, inference bounds, lighting,
scene, profile, apps and machine load. Compare per-state inference/processing means,
P95/P99/max frame intervals, cursor intervals, frame age, stalls, hand counts and
skipped renders. Restore is visible focus state plus a `minimized->focused` or
`minimized->unfocused` transition. Exclude intentional pose pauses from interpretation
of cursor gaps. If inference stays steady but GUI tails worsen, investigate HighGUI;
if capture delivery stalls independently, investigate the driver/camera; if several
CPU stages stall under contention, collect OS scheduling evidence before changing priority.

Also check pinch drag across minimize/restore, release on X while dragging, no
phantom click on restore, loss/reacquisition with a new safe anchor, Pointing swipe
arbitration, automatic/manual resume, manual D, global Ctrl+Shift+F10 outside focus,
and correct emergency recovery. Minimized rendering skips must increase while
processed frame/hand counts continue. An empty cursor series means no admitted moves,
not zero-latency input. Verify the process exits and camera becomes available after X.

Inference-bound experiments may explicitly add `--inference-resolution 960x540`
to comparable runs, but quality must be physically checked; no resolution was
silently reduced. Real hardware acceptance is based on P95/P99 pacing and cursor
feel, not on an assumed 60 FPS target. No hardware before/after comparison is claimed.

## Validation, changed files and next steps

New tests cover owned HWND matching/closure, all preview states, continuous actual
gesture/palm-controller updates while minimized, current-frame rendering on restore,
no phantom OPEN_PALM click, close and display-fault cleanup, disabled diagnostics,
bounded samples, state percentiles, cursor intervals/frame age/stalls, malformed or
expired host timestamps, slow cursor queries, suppressed move counting, emergency
cancellation, numeric contract equivalence and virtual-only benchmark JSON.
The complete prior tracking, gesture, multi-hand, cursor profile, pinch/drag,
rearm/resume and emergency race suites also pass. No new controller concurrency
or application buffer exists, so no worker cleanup mechanism was needed.

Implementation files: `hand_tracking/hand_tracker.py`, `preview_window.py`,
`diagnostics.py`, `performance.py`, `benchmark_synthetic.py`, `benchmark_rendering.py`;
`gestures/models.py`; `controls/controller.py`, `backends.py`, `windows.py`.
New tests: `hand_tracking/test_background.py`, `test_diagnostics.py`,
`test_rendering_benchmark.py`, `controls/tests/test_frame_age.py`,
`gestures/tests/test_numeric_fastpath.py`. Existing GUI fixture adjustments are in
`test_hand_tracker.py`, `test_gui_performance.py`, `test_gesture_debug.py`,
`test_performance.py`, `test_reliability.py`, `test_two_hands.py`.
Documentation: this guide, hand-tracking README/PERFORMANCE and the retained JSON.

Remaining limitations: synchronous native calls can stall; visible GUI can still
delay the next observation; camera transport age/drop counts are unavailable; actual
UGREEN/background scheduling and physical cursor pacing need owner data. Priority
changes, capture workers/latest-frame buffering, render throttling and alternate
inference modes should be considered only if those measurements justify them.
Any future worker must preserve bounded ownership, strictly increasing timestamps,
single controller access, cancellation gates and deterministic resource cleanup.
No face tracking or other Phase 4 work is included.

Suggested future commit, after physical acceptance:

`perf(visioncontrol): optimize tracking and background cursor responsiveness`
