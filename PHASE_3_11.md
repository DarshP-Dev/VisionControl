# Phase 3.11 — Background capture regression investigation

Status: a small, opt-in Windows 11 correction is physically validated on this
UGREEN/MSMF system. `--windows-timer-policy honor-requests` recovered minimized
camera delivery from about 14 to 60 FPS and full two-hand simulated processing to
41 FPS. See the continuation results below for latency/CPU costs and remaining
acceptance limits. Sync and system-managed timer policy remain defaults;
latest-thread remains opt-in. The implementation was initially left unstaged for
review; the owner subsequently authorized committing and pushing using DarshP-Dev.

## Starting state

The working tree was clean on `main`, commit
`c465dc9388dd2bf34c3daa09f8c41c6ce2e05121` (Phase 3.10). No repository
`AGENTS.md` was present. The actual baseline was 720 passing tests:
camera 36, gestures 165, hand tracking 253, controls 266.

The fix continuation began with the uncommitted diagnostics intact and reconfirmed
745 passing tests (59/165/254/267). All diagnostic work was preserved.

Phase 3.10 documentation and raw reports remain intact. This phase neither changes
the default pipeline nor promotes `latest-thread` to normal operation.

## Historical evidence reviewed

These are owner-run historical measurements, not fresh matched comparisons:

| Configuration | Processed FPS | Worker delivery FPS | Mean read ms | Read P95 ms | Frame interval P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full application, focused population | 36.63 | Not separated by state | 15.62 consumed | 30.67 consumed | 30.50 |
| Full application, aggregate unfocused population | 30.05 | Not separated by state | 23.11 consumed | 77.96 consumed | 78.08 |
| Full application, all minimized, two hands throughout | 14.53 | 14.53 | 67.96 producer | 94.72 producer | 95.44 |
| Camera only, owner switched to Notepad, no HighGUI | 59.99 | 59.99 | 15.70 producer | 30.84 producer | Not a full application run |

Sources in the ignored `hand_tracking/benchmarks/` directory:

- `phase3_10_focus_diagnostic.json`: 3,848 frames; actual focus/state populations
  were about 36.56/83.48 seconds. The reported 30-second foreground-app sequence
  cannot independently label Terminal, Notepad and Chrome in this old report.
- `phase3_10_minimized_30s.json`: 436 measured frames, all two-hand/minimized;
  all renders skipped; inference mean 18.20 ms, capture wait mean 47.11 ms,
  controller host age mean 22.46 ms; no failures, stale rejections or backlog.
- `phase3_11_camera_only_background_retry1.json`: 1,800 deliveries over 30.003 s;
  successful cleanup. Earlier interrupted/retry reports are retained and excluded
  from that historical primary result.
- `phase3_10_acceptance_sync_2.json` and `_3.json`: approximately 24.715 focused
  versus 24.694 unfocused FPS. These suggest the visible-background collapse is
  not inevitable in sync mode, but are separate runs without matched minimized
  evidence. They do not establish a causal sync/thread difference.

The initial reports located the observed slowdown in **delivery opportunities**, rather
than increased neural inference execution time or continued minimized drawing.
By themselves they cannot distinguish driver/native wait, thread descheduling, GIL reacquisition,
camera exposure changes or an interaction involving HighGUI. Read-wall latency is
not a measurement of exposure time. A general Windows background FPS cap is not
established.

## Ownership and processing architecture inspected

In synchronous mode the main thread opens/configures/queries/reads/releases the
camera. Its serial path is read → resize/RGB/image preparation → synchronous CPU
MediaPipe VIDEO inference → observation extraction/optional global association →
EMA → feature/static/pinch/swipe/state/arbitration → safety controller → preview
drawing/`imshow` → subsequent iteration. Events are also pumped before input.

In `latest-thread`, one existing owning worker performs **all** operations on its
VideoCapture, including native destruction. It reads decoded BGR, makes one owned
immutable snapshot, and replaces one pending slot. The main thread consumes each
session/sequence once, waits in bounded 10 ms condition waits when necessary,
and owns MediaPipe, all gesture/controller updates and HighGUI. Waiting also pumps
Q/X/A/D/help. There is no camera-frame queue and no inference/render worker.

The capture condition protects metadata and slot changes. Neither `read()`, frame
copy, initialization, native release, inference nor GUI queries execute under it.
The existing global live-input emergency/watchdog thread remains independent of
camera/model progress. Its capture-health check uses short metadata access only.

Preview state uses the owned Win32 HighGUI HWND, process ID/class/title validation,
`IsIconic`, existence/visibility and foreground-window identity. Minimize is distinct
from destruction; focus does not select capture rates or inference settings. The
main thread skips drawing and display submission when minimized/hidden, while
continuing event pumping, capture, recognition and already-armed controls. Restore
uses the current observation; X ends the run, fences input and releases buttons.

Inspection found no focus-dependent sleep, capture reconfiguration or model
reinitialization. `GuiEvents(auto)` uses native Win32 `pollKey`; its compatibility
fallback remains `waitKey(1)`. Its module description historically says one call
per frame, but the experimental capture path also polls around frame waits and
before dispatch. This is intentional for close/disarm responsiveness.

## Diagnostic matrix and changes

| Configuration | Implementation | Purpose / current result |
| --- | --- | --- |
| A: camera without GUI/model | `camera.benchmark_delivery` | Fresh host delivery approximately 59.95 FPS; does not reproduce full-app collapse |
| B: camera + HighGUI, no model | Same module with new `--preview` | Owner reproduced approximately 60→14 FPS when minimized in both pipelines; correction measured below |
| C: camera + real MediaPipe, no HighGUI | Existing timed `--headless` tracker | Owner repeated with 100% two-hand frames: latest 42.56 FPS, sync 25.78 FPS; latest producer about 60 FPS |
| D: full application, simulated controls | Existing full tracker with timeline | Owner matched baseline and corrected 100% two-hand full run are documented below |
| E: synchronous fallback | `--capture-pipeline sync` in each path | Same minimized collapse reproduced; process timer-policy A/B/A also corrects synchronous capture |

The camera diagnostic uses the shared backend/configuration, capture worker, GUI
event class, owned-window lifecycle and reusable preview buffer. Preview fits the
same 1100×650 bounds as the application, without overlays, gestures, MediaPipe or
input backends. Warmup draws/pumps the GUI too. Minimized frames skip rendering;
restoring resumes drawing. Q/X stop and release resources. An early Q/X exit is
not reported as a completed timed benchmark (exit 1 with `stopped`/`preview_closed`).
There are no desktop controls to arm/disarm in this diagnostic; D remains effective
in the full application. A visible measurement-start message anchors manual timing.

The initial pass stopped at diagnostics rather than making a speculative change.
The later matched runs and single-setting A/B/A experiment below justify honoring
existing process timer requests. Capture delivery architecture, priority, requested
timer period, affinity, inference, gesture work and GUI polling remain unchanged.
No recognition threshold, smoothing, gesture history or controller action changed.

### Capture timeline

Existing `--benchmark`, `--report` or `--performance-profile` opt-ins enable the
new numeric timeline. Ordinary tracker execution keeps it disabled. The camera
benchmark always profiles. Reports contain `capture_timeline`; latest-thread
cleanup reports also contain `capture_pipeline.timeline`.

Fixed two-second buckets retain at most 300 buckets (about ten minutes), with
256 percentile samples per named series per bucket. Discarded bucket count is
explicit. There is no per-frame disk logging. Means/counts/maxima cover all events
in each retained bucket; percentile windows are bounded. No images, landmarks,
foreign window titles, screen content or foreground application names are recorded.

Each bucket contains:

- Monotonic start/end, relative offset and actual elapsed duration, including a
  partial final bucket; zero-publication intervals remain visible.
- Last-main-thread-observed preview state and its wall-time residency. A bucket
  spanning a transition is `mixed`, rather than incorrectly labeled steady state.
- Read attempts, successful publications, consumption/completion, overwritten
  snapshots, missing-frame waits, failures/timeouts and stale rejections.
- Independent worker publication FPS only in latest-thread mode; sync host-read
  FPS is explicitly separate. Camera-only completion rate is not recognition FPS.
- Read-wall P50/P95/P99/max, snapshot copy, copy-to-publication, publication lock
  wait, publication intervals, post-publication-to-next-read gap, handoff age and
  individual `take()` wait durations. Full tracker `capture_wait` still measures
  the entire wait including repeated takes and event pumping.
- Processed frame intervals, real inference times, GUI/render time, host age at
  controller update, and accepted cursor move intervals/dispatch host age where
  those stages run. Intentional cursor pauses still count in cursor intervals.
- Observed-hand frame distribution and explicitly **last observed** hand count.
  A last hand count during missing deliveries is metadata, never a reused result.
- Process CPU and main/capture-thread CPU estimates. Python's `thread_time()`
  measures the calling thread only; MediaPipe/MSMF helper-thread CPU is included
  in process CPU but cannot be assigned to inference/capture from these counters.

Events are attributed to their endpoint bucket; a read/publication interval can
span a state/bucket boundary. Warmup resets statistics and interval history.
Process CPU deltas spanning boundaries are apportioned by elapsed wall time and
marked estimated. Thread CPU is likewise endpoint-based. On this machine observed
thread CPU ticks are often 15.625 ms: do not interpret zero per-read thread CPU as
proof the read did no CPU work. This is not an ETW scheduler trace.

The main thread publishes numeric state only **after** querying the GUI. The
worker never queries a window or reads foreign application state. Telemetry uses
a separate short metadata lock; no native camera/GUI call, percentile calculation,
JSON serialization or disk I/O runs under it. Capture condition → telemetry lock
is the only nested acquisition direction; no reverse path exists. Summary detaches
the current bounded bucket and computes percentiles outside the telemetry lock.
The lock still has a small bounded acquisition/accounting cost when profiling;
new tests prove that a slow GUI query or percentile export cannot hold capture
publication or the independent emergency path.

Read time is measured at the Python boundary around `read_frame()`/OpenCV. It
includes native delivery/conversion, scheduling and GIL reacquisition; it cannot
on its own prove the native driver was blocked throughout. A long read with small
post-publication gaps supports investigation inside that boundary; a large gap
between read calls supports scheduling/metadata/GIL investigation outside it.
Fast publication with slow consumption points downstream. No interpretation
equates any of these metrics with sensor exposure or unique sensor frames.

### Camera settings and scheduling

MSMF, requested 1920×1080 at 60 FPS, full inference and existing format request
remain. The driver rejects MJPG and reports FOURCC `\x16\x00\x00\x00`; do not
name the actual transport from this value. No alternate backend was tested here.
Supported modes are not enumerated by these OpenCV readbacks.

Diagnostic configuration now queries exposure/auto-exposure, autofocus/focus,
RGB conversion and buffer-size properties **on the capture owner**, without setting
them. Unsupported properties may return zero: these values do not establish
actual exposure or ambient lighting. Reports also record OS/OpenCV version and
configured OpenCV thread count; that count is not measured active utilization.

Windows timer policy was initially one hypothesis. Microsoft's
[timeBeginPeriod documentation](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod)
describes changed timer-resolution guarantees for fully occluded/minimized window
owners on Windows 11. It does **not** establish a camera FPS cap or diagnose this
regression by itself. The continuation below tests a specific process-policy
intervention and reversal. No priority, global power, registry, affinity or timer
period is changed. A Windows Performance Recorder/Analyzer trace would be needed
to identify the exact native helper/wait responsible, with separate trace privacy
review; it is not needed to use the demonstrated policy correction.

OpenCV's [video-I/O flags](https://docs.opencv.org/5.0.0-alpha/d4/d15/group__videoio__flags__base.html)
restrict read-timeout properties to FFmpeg/GStreamer. The existing MSMF native
open/read/release limitation and bounded join/quarantine policy remain; a Python
deadline cannot safely terminate a stuck native camera call.

## Initial exploratory hardware measurements

All runs used the existing UGREEN/MSMF request, 1920×1080 delivered BGR, 15 s
warmup after first delivery and 30 s measurement. Camera access required execution
outside the sandbox; the initial sandbox-open failure is retained as an environment
failure and excluded from performance comparison. No camera frames were saved,
and no real Windows input was sent. Other applications, lighting and scene were
not controlled by the agent; foreground state cannot be established for headless
processes by preview telemetry. These are exploratory, not matched acceptance.

| Camera only | Before Phase 3.11 telemetry | With telemetry |
| --- | ---: | ---: |
| Frames | 1,799 | 1,799 |
| Host consumer FPS | 59.9530 | 59.9566 |
| Producer FPS | 59.9531 | 59.9566 |
| Producer read mean / P95 / P99 ms | 15.691 / 30.180 / 33.021 | 15.750 / 30.846 / 33.045 |
| Consumer interval P95 / P99 ms | 31.206 / 33.978 | 31.789 / 33.913 |
| Mean read-completion age at consumption ms | 1.138 | 1.189 |
| Process CPU, one-core equivalent % | 95.24 | 110.92 |
| Working set sampled after cleanup, MiB | 136.27 | 125.06 |
| Peak working set over process lifetime, MiB | 160.95 | 168.50 |

FPS changed approximately +0.006%, not a regression fix. Read P95 increased
approximately 2.2%; CPU increased 15.68 percentage points of one logical core.
These single non-controlled samples cannot isolate telemetry CPU cost or prove a
memory improvement; repeated matched measurements are needed. The opt-in remains
off during ordinary operation. Both owners released cleanly; worker alive false,
no capture failures, no overwrites in the measured camera-only runs.

| Real camera + CPU VIDEO inference, no HighGUI/gestures/controls | Before | With telemetry |
| --- | ---: | ---: |
| Measured frames | 1,236 | 1,497 |
| Observed 0 / 1 / 2 hands | 151 / 494 / 591 | 1,237 / 243 / 17 |
| Application FPS | 41.18 | 49.88 |
| Producer FPS | 60.04 | 60.01 |
| Frame interval P95 / P99 ms | 34.106 / 36.191 | 32.694 / 35.197 |
| Mean inference ms | 21.338 | 16.237 |
| Mean host age at inference start ms | 11.082 | 8.429 |
| Process CPU, one-core equivalent % | 257.35 | 284.90 |
| Working set after cleanup, MiB | 283.77 | 270.26 |

**Hand populations differ substantially; do not calculate an optimization gain
from this table.** It establishes only that this workload can coexist with
approximately 60 producer publications/s without HighGUI. It does not establish
two-hand minimized performance, live cursor smoothness, sensor latency or matched
foreground/background behavior. No stale results/read failures occurred; both
workers released. Camera-only and headless tests cannot validate preview lifecycle.

Over full two-second buckets, the after camera-only run had weighted mean
post-publication gap about 0.060 ms, publication lock wait 0.0028 ms and handoff
age 0.110 ms. The after headless run had about 0.124 / 0.0040 / 4.940 ms respectively.
These runs show no large between-read synchronization gap; they do not explain
the historical minimized native-boundary delay. Do not pool bucket P95s into a
fabricated global percentile.

A separate synthetic numeric-timeline microbenchmark (five × 20,000 event calls)
measured median 0.236 microseconds/event disabled versus 4.025 enabled. It excludes
camera, inference, GUI, capture-condition and thread-CPU sampling costs; it is
neither webcam FPS nor complete instrumentation overhead. Its raw JSON includes
all repeats. No synthetic overlap FPS improvement is claimed in this phase.

All original raw reports remain in the ignored benchmark directory. Numeric raw
snapshots and SHA-256 hashes of selected historical and fresh evidence are preserved
in `performance_reports/phase3_11.json`. The fresh after reports precede final
metadata/read-error/report-label refinements; core acquisition/inference remained
unchanged. These initial reports predate the matched owner evidence and correction below.

## Safety and automated verification

Production controller, safety-monitor, gesture, smoothing and association logic is
unchanged. The new tracker move observer adds numeric timing after an accepted
backend move; it does not send input. Startup-disarmed/manual arming, live opt-in,
250 ms observation/capture freshness, 500 ms host watchdog, cancellation generations,
held-button cleanup and emergency latching remain. No new production thread,
buffered action, prediction, replay or automatic rearm is introduced.

Camera single ownership, immutable capacity-one handoff, session/sequence checks,
MediaPipe VIDEO timestamps, cooperative stop, bounded join and unreleased-device quarantine
are preserved. No diagnostic function calls native camera operations from the
consumer of latest-thread mode.

Initial diagnostic suite: **745 passing tests** (25 new): camera 59, gestures 165,
hand tracking 254, controls 267. Tests use fake cameras, clocks, models, windows,
virtual inputs and injected waits; no real Windows keyboard/mouse input.

Added coverage includes exact bucket/rate/percentile/state-residency/CPU accounting,
warmup reset, partial/empty/missing/stalled intervals, bounded retention including
long suspend, cursor intervals, sync/producer distinction, actual publication and
consumption counts, producer idle/copy/lock/handoff series, unknown metric rejection,
disabled instrumentation, owner-only queries, slow percentile export and slow main
GUI query without blocking producer publication, both diagnostic pipelines,
minimize/restore skipping, X/fault cleanup and unfocused/minimized emergency drag
release while telemetry is contended. Existing stale-dispatch, in-flight stop,
critical fault, identity and gesture regression tests all pass.

## Original diagnostic matrix commands (system-policy baseline)

Run one benchmark at a time from a normal PowerShell terminal. Keep two hands
visible continuously in C/D; the owner has agreed to perform these matched runs.
Use the same lighting, hand position, webcam position, foreground application,
USB port, power state and background load for both pipelines. Note auto-exposure
uncertainty, other camera clients, lighting, foreground app and physical sequence
in a sidecar text note. Do not change camera settings to improve a comparison.
Repeat at least three times, reversing pipeline order on alternate repetitions.
Report filenames below get a fresh timestamp; earlier evidence is never overwritten.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase311Tag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$phase311Camera = @('--camera-index','0','--backend','msmf','--width','1920','--height','1080','--fps','60','--fourcc','MJPG','--warmup','15')
$phase311Tracking = @('--max-hands','2','--inference-resolution','full','--benchmark')
$phase311Gestures = @('--gestures','--pinch','--gesture-states','--swipes')
$phase311Simulation = @('--controls','--control-mode','simulate','--control-gesture-profile','palm-cursor','--control-mapping','absolute','--control-region-width','.8','--control-region-height','.8','--control-mouse','--control-tabs','--control-gesture-rearm','--control-emergency-hotkey','ctrl+shift+f10')

# A: switch to the SAME other application before measurement; no HighGUI/model.
foreach ($phase311Pipeline in 'latest-thread','sync') {
  .\.venv\Scripts\python.exe -m camera.benchmark_delivery @phase311Camera --capture-pipeline $phase311Pipeline --duration 30 --report "hand_tracking/benchmarks/owner_3_11_A_${phase311Pipeline}_${phase311Tag}.json"
}

# B: camera + HighGUI; no model or input. Use the 120-second sequence below.
foreach ($phase311Pipeline in 'latest-thread','sync') {
  .\.venv\Scripts\python.exe -m camera.benchmark_delivery @phase311Camera --capture-pipeline $phase311Pipeline --preview --gui-mode auto --duration 120 --report "hand_tracking/benchmarks/owner_3_11_B_${phase311Pipeline}_${phase311Tag}.json"
}

# C: two continuously visible hands, real inference, no HighGUI/input.
# Keep the process unfocused, with the same scene/light/other application as A/B/D.
foreach ($phase311Pipeline in 'latest-thread','sync') {
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase311Camera @phase311Tracking --capture-pipeline $phase311Pipeline --headless --duration 30 --report "hand_tracking/benchmarks/owner_3_11_C_${phase311Pipeline}_${phase311Tag}.json"
}

# D: full two-hand workload, SIMULATION only. Press A yourself to arm virtual input.
# Use the same focused/unfocused/minimized/restored 120-second sequence as B.
foreach ($phase311Pipeline in 'latest-thread','sync') {
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase311Camera @phase311Tracking @phase311Gestures @phase311Simulation --capture-pipeline $phase311Pipeline --duration 120 --report "hand_tracking/benchmarks/owner_3_11_D_${phase311Pipeline}_${phase311Tag}.json"
}
```

Time B/D from the **Warm-up complete** message, not process launch:
0–30 s preview focused; 30–60 s preview visible/unfocused with a recorded other
application focused; 60–90 s fully minimized; 90–120 s restored/focused.
Keep two hands visible in D for the entire measurement. State telemetry, not the
intended schedule, determines the usable full buckets. Mixed transition and short
partial buckets should be inspected separately. Leave a full 30 seconds minimized;
if a transition takes time, extend D/B `--duration` (for example 150) and record the
actual sequence. Headless reports intentionally say `headless`, not `unfocused`.

Do a separate interactive simulation run to test closing while a virtual drag is
held (D/Q/X before the timer ends). Also test palm/pointing/fist, pinch click and
hold/release, POINTING swipes, loss/reacquisition, resume and eligible left-pinch
rearm. No restore jump, duplicate click/swipe, stuck virtual button or automatic
rearm after deliberate disarm is acceptable. Simulation does not register a real
global Windows hotkey; its independent hotkey/cancellation path is validated with
mocks. Physical global-hotkey/live-input testing is deferred until simulation
acceptance passes. No live command or automatic arming is offered at this stage.

To inspect the timeline after a run (set the exact fresh report path):

```powershell
$phase311Report = Get-Content -Raw 'hand_tracking/benchmarks/REPLACE_WITH_REPORT.json' | ConvertFrom-Json
$phase311Report.capture_timeline.buckets | Select-Object `
  @{n='Offset_s';e={[math]::Round($_.offset_seconds,1)}}, preview_state, `
  capture_worker_delivery_fps, processed_application_fps, `
  @{n='ReadP95_ms';e={$_.timings.camera_read.p95_ms}}, `
  @{n='ReadP99_ms';e={$_.timings.camera_read.p99_ms}}, `
  @{n='GapP95_ms';e={$_.timings.post_publication_to_next_read.p95_ms}}, `
  @{n='InferMean_ms';e={$_.timings.inference.mean_ms}}, `
  @{n='FrameP99_ms';e={$_.timings.frame_interval.p99_ms}}, `
  @{n='Hands';e={$_.hand_count_frames | ConvertTo-Json -Compress}} | Format-Table -AutoSize
$phase311Report.capture_pipeline | Select-Object worker_alive, release_completed, error, shutdown_error
$phase311Report.resources
$phase311Report.memory

# Actual regression commands; all camera/model/input activity here is mocked.
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
```

Compare steady two-hand populations for processed FPS, camera worker FPS,
P95/P99/max frame and cursor intervals, read/idle/copy/lock/handoff/wait timings,
inference, host frame age at controller/dispatch, CPU/memory, failed/stale counts,
capacity and worker cleanup. If no accepted cursor moves occurred, cursor timing
is unavailable rather than zero. Ignore `capture_worker_delivery_fps` in sync;
its host-read rate is limited by the consumer too. No FPS tolerance is asserted
in unit tests. The 30–35+ FPS and 10–15% focused/minimized gap are hardware targets,
not claimed achievements.

## Files and next decision

Created `camera/capture_timeline.py`, its tests, the camera preview benchmark tests,
this guide and `performance_reports/phase3_11.json`.
Modified `camera/latest_capture.py`, `camera/benchmark_delivery.py`,
`camera/camera_diagnostics.py`, `camera/test_latest_capture.py`,
`camera/test_camera_diagnostics.py`, `hand_tracking/hand_tracker.py`,
`hand_tracking/test_capture_pipeline.py`, `controls/tests/test_capture_fence.py`,
and relevant camera/tracking performance README documentation.

At the end of the initial pass, the next decision depended on matched B/C/D evidence. A B-only collapse implicates
the HighGUI/native interaction without model work. A C collapse with small
between-read gaps implicates camera/native delivery under model workload;
large between-read gaps warrant thread/GIL/scheduling traces. D-only collapse
requires further isolation of the complete workload. If all rates drop with the
same scene/lighting, investigate exposure/USB/driver behavior before scheduling.
These are diagnostic branches, not confirmed causal conclusions.

Keep sync as default and latest-thread experimental. The measured timer-policy
correction described below remains opt-in, with focused-performance, age, CPU
and safety checks. No priority or alternate backend mitigation was needed. No new gestures,
models, dependencies, Phase 4 work or global OS configuration changes were made.
Suggested commit after owner review:
`perf(visioncontrol): improve background camera capture stability`.

## Fix continuation — matched evidence and timer-policy intervention

The owner supplied matched reports after the initial diagnostic pass. Local files
confirm the supplied observations:

- `owner_3_11_B_latest-thread_20261028_010836_481.json`: full steady two-second
  buckets show 59.63 FPS visible/unfocused and 14.08 FPS minimized.
- `owner_3_11_B_sync_20261028_010836_481.json`: 58.55 FPS visible/unfocused versus
  13.97 minimized. This run was interrupted before the full timer completed;
  its 38 s unfocused and 36 s minimized steady buckets remain usable, rather than
  pretending the complete 120-second sequence passed.
- `redo_C_latest_20261028_012745_943.json`: 1,277/1,277 frames with two hands,
  42.56 processed FPS, 19.83 ms mean inference, 25.75 ms frame P95; producer 59.96 FPS.
- `redo_C_sync_20261028_012745_943.json`: 774/774 frames with two hands,
  25.78 processed FPS and 18.35 ms mean inference; frame P95 approximately 44.70 ms.
- `redo_D_latest_20261028_012745_943.json`: two hands in 3,437/3,670 frames (93.7%),
  and 340/340 completed frames in steady minimized buckets. Steady focused /
  unfocused / minimized FPS: 35.75 / 34.88 / 14.17; producer 60.02 / 60.04 / 14.17.
  Mean read durations: 14.92 / 14.62 / 69.32 ms; between-read gaps:
  0.263 / 0.312 / 0.065 ms; inference: 20.03 / 20.42 / 18.41 ms.

Earlier C/D runs with intermittent hands are preserved but are not substituted for
these repeated matched baselines. MediaPipe, gestures, controls and the asynchronous
worker are unnecessary for reproduction; visible focus loss alone did not cause
the owner's collapse. The small producer gaps locate most of the delay across the
read boundary, rather than in Python work before the next read.

### Reversible A/B/A experiment

Microsoft documents that disabling
`PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION` causes Windows to honor previous
process timer requests. See [SetProcessInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation)
and [GetProcessInformation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessinformation).
The experimental intervention changes only that mechanism. It does not request
1 ms via `timeBeginPeriod`, alter execution-speed QoS, raise priority or change a
camera property. No administrator privilege or permanent OS configuration is used.

Using the same open camera/session, a diagnostic controlled only its owned HighGUI
HWND. Each phase lasted 12 s. Analysis discards the first 2 s after each requested
transition and uses only complete two-second buckets wholly within the phase
(8 s of samples per phase in these runs). Window state was independently observed;
the worker never manipulated the GUI. No real input backend was initialized.

| Phase, still minimized | Latest-thread host FPS | Sync host FPS |
| --- | ---: | ---: |
| A: original system-managed policy | 14.625 | 14.875 |
| B: honor existing process timer requests | 60.000 | 60.000 |
| A: original policy restored | 13.625 | 14.750 |

Reports: `phase3_11_probe_honor_latest_r1.json` and
`phase3_11_probe_honor_sync_r1.json`. Original masks `(version=1, control=0, state=0)`
became `(1,4,0)` during B and returned exactly to `(1,0,0)` afterward. Latest-thread
mean minimized read time changed 67.55→15.74→72.08 ms while its between-read gap
stayed about 0.06 ms. Both processes released their cameras successfully; the
latest worker exited. Separate requests for a timer period were unnecessary, so
no such candidate was added to production.

The same probes also tested hidden rather than minimized owned windows. Hidden
baseline / intervention / reverted phases remained about 59.88–60 FPS in latest
and 60 FPS in sync. A normal restored preview recovered to about 60 FPS too.
This is a hardware/run-specific observation, not a guarantee that hidden windows
always escape Windows occlusion policy. The first sync visible phase ran at 14
FPS despite being non-iconic; its foreground/occlusion conditions were not controlled.
Do not discard that result or label it a focused baseline. Production retains
ordinary minimize/restore semantics; no invisible-window workaround was introduced.

The intervention and reversal provide **strong causal evidence that Windows 11's
process timer-request handling causes this minimized delivery regression on this
system**. They do not identify which internal MSMF/driver/helper wait relies on
the timer or prove all read-wall time was native blocking. No claim is made that
MSMF alone is faulty or Windows applies a universal camera FPS cap. A native
scheduler trace would be needed for that finer attribution.

### Integrated correction

New shared resource `camera/windows_timing.py` implements:

```text
--windows-timer-policy system          # existing default, makes no Windows API calls
--windows-timer-policy honor-requests  # opt-in Windows 11 correction
```

Both the full tracker and camera benchmark accept the flag. The resource reads
`ProcessPowerThrottling` through the current-process pseudo-handle, saves the exact
version/control/state masks, sets only the timer-control bit while preserving all
other bits, and verifies readback. It runs once before camera/model/input setup.
There is no per-frame policy call, state transition hook, extra timer-period
request, new thread, frame queue or camera ownership change.

Shutdown restores and verifies the exact original masks after input, camera,
model and GUI cleanup. Startup failure—including partial application—rolls back
before model/camera/controller creation. Unsupported platforms/API failure refuse
an explicit request with a visible error; they do not silently claim correction.
Restoration failures appear in the report and cause an error result. Cleanup is
idempotent; a failed restoration can be retried. Ending the process also ends this
process-local setting, but normal cleanup does not rely on process termination.
Reports record `windows_timer_policy` with requested mode, original/applied/final
masks, restoration status and errors.

### Full two-hand hardware acceptance with the correction

`phase3_11_fix_full_latest_r1.json` ran the production tracker with full-resolution
inference, all gestures and simulated controls, 15 s model warmup and 120 s measured.
The owner kept two hands visible: **4,540/4,540 measured frames detected two hands**.
Only the owned preview was automatically minimized at 60 s and restored at 90 s.
The intended visible/unfocused interval was actually recorded as focused; no
separate corrected unfocused result is claimed from this run.

| Steady two-second buckets | Owner system policy | Corrected honor-requests |
| --- | ---: | ---: |
| Focused processed FPS | 35.75 | 36.86 |
| Minimized processed FPS | 14.17 | 41.00 |
| Minimized producer FPS | 14.17 | 59.93 |
| Minimized mean producer read ms | 69.32 | 15.27 |
| Minimized mean inference ms | 18.41 | 20.05 |
| Minimized completed two-hand frames / seconds in steady buckets | 340 / 24 | 1,148 / 28 |

The minimized processed rate increased about 189%; focused processing did not
show a regression in this comparison. These are individual real runs with
different poses/session times, not confidence intervals or guarantees for other
machines. The A/B/A camera tests provide the closer causal control.

The following percentiles use each report's full minimized-state completed-frame
population (including transition-edge observations), rather than pooling bucket
percentiles or mixing them with the steady FPS denominator above:

| Minimized frame pacing / host latency | Owner system policy | Corrected |
| --- | ---: | ---: |
| Frame interval P95 / P99 ms | 96.62 / 100.14 | 28.32 / 34.25 |
| Worst frame interval ms | 112.27 | 38.83 |
| Consumed-frame read P95 / P99 ms | 94.63 / 95.02 | 31.08 / 33.56 |
| Capture wait mean / P95 ms | 47.38 / 73.81 | 0.282 / 0.087 |
| Host frame age at controller mean / P95 / P99 ms | 24.24 / 26.02 / 35.20 | 32.76 / 42.11 / 45.95 |
| Maximum host frame age at controller ms | 106.04 | 56.68 |

Host age increases by about 8.5 ms on average while update opportunities become
far more regular. It remains near the focused host-age range and well inside
the unchanged 250 ms gate; no stale frames or model results were rejected. This
tradeoff is reported, not hidden by the FPS gain. Host age starts at read completion,
so it cannot establish sensor-to-cursor latency. The run stayed disarmed and
reported **zero accepted cursor updates**: no real cursor-feel or cursor-dispatch
latency improvement is claimed. Separate manual simulation interaction remains
necessary, and live input was never dispatched.

Whole-run CPU was 277.95→294.46% of one logical core while mean CPU per processed
frame fell 90.90→77.85 ms. The state mix and actual work rates differ; the higher
minimized work rate naturally costs more CPU. Working set after cleanup was
333,897,728→329,101,312 bytes, and lifetime peak 345,690,112→340,373,504 bytes.
These single samples are not evidence of a memory optimization. Honoring existing
timer requests can increase wakeups and energy use; battery/energy use was not
measured. Do not promote the flag to an unconditional cross-machine default on
these results alone.

Both full runs had zero capture failures, worker exceptions and stale rejections.
The corrected worker exited, released its camera, retained capacity one, and the
policy read back the original masks after shutdown. There were no >100 ms
completed-frame stalls in the corrected run. Preview renders were skipped for all
1,227 minimized-state completed frames; restore did not reinitialize the model.

### Camera-only acceptance, remaining validation and exact commands

The integrated 120 s camera-plus-HighGUI latest-thread run
`phase3_11_fix_B_latest_r1.json` delivered 7,193 consumed frames. Steady focused
producer rate was 59.90 FPS and minimized rate 60.00 FPS, with successful owner
release, worker exit and exact process-policy restoration. Its visible periods
also remained focused, so it supplies no separate corrected unfocused population.
The synchronous integrated run and final regression totals are recorded in the
closing validation below.

Original raw reports are preserved. New matched/correction reports, filtered
numeric summaries, SHA-256 hashes and reproducible diagnostic runner source are
archived in `performance_reports/phase3_11_fix.json`; exact raw JSON is compressed
inside the archive to avoid duplicating large producer/consumer timeline trees.
No pixels, screen content or video are included.

Run these commands in normal PowerShell. Existing CLI modes and thresholds are
preserved; no administrator elevation is required. Use the warmup message to time
0–30 s focused, 30–60 s visible/unfocused, 60–90 s minimized, 90–120 s restored.
Only actual observed states count, and mixed/partial buckets are separate.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase311FixTag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'

# Corrected B, both pipelines. No model, gestures or input.
foreach ($phase311FixPipeline in 'latest-thread','sync') {
  .\.venv\Scripts\python.exe -m camera.benchmark_delivery --capture-pipeline $phase311FixPipeline --windows-timer-policy honor-requests --backend msmf --width 1920 --height 1080 --fps 60 --preview --warmup 15 --duration 120 --report "hand_tracking/benchmarks/verify_3_11_B_${phase311FixPipeline}_${phase311FixTag}.json"
}

# Corrected D. Hold TWO hands continuously; SIMULATION, starts disarmed.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --capture-pipeline latest-thread --windows-timer-policy honor-requests --backend msmf --width 1920 --height 1080 --fps 60 --max-hands 2 --inference-resolution full --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --benchmark --warmup 15 --duration 120 --report "hand_tracking/benchmarks/verify_3_11_D_latest_${phase311FixTag}.json"

# Separate manual simulated cursor/pinch/drag/loss/rearm/close acceptance.
# Press A yourself; D disarms. Q/X ends the application and releases virtual buttons.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --capture-pipeline latest-thread --windows-timer-policy honor-requests --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --performance-profile --report "hand_tracking/benchmarks/verify_3_11_interactions_${phase311FixTag}.json"
```

For an A/B control run, use `--windows-timer-policy system` and a different fresh
report filename, keeping lighting, scene, foreground app, hand positions, USB
configuration and background load matched. Repeat in reversed order. Do not change
exposure/autofocus/resolution to improve a comparison. Keep the existing sync
default; the owner may explicitly select latest-thread plus honor-requests on this
tested Windows 11 system. Latest-thread remains experimental; physical simulated
interactions, real emergency-hotkey/live-cursor acceptance and independent corrected
unfocused data remain separate from the demonstrated minimized FPS recovery.

### Closing validation

The integrated synchronous camera/HighGUI run
`phase3_11_fix_B_sync_r1.json` also completed 120 s: 7,184 deliveries, steady
focused 59.83 FPS and minimized 60.04 FPS. Original process masks were restored
and camera release completed. Together with the latest-thread run and both
same-session reversal probes, this validates the correction in both capture modes
on this webcam/Windows build. The corrected visible periods remained focused;
an independently measured corrected unfocused population is still pending.

Final full suite: **766 passing tests**, versus the reconfirmed 745-test
continuation baseline: camera **75**, gestures **165**, hand tracking **259**,
controls **267**. The 21 additional tests cover mask preservation, exact restoration,
default-no-API behavior, unsupported platforms, partial/failed startup, invalid
readback, interrupted startup and cleanup, failed/restorable cleanup, idempotence,
native ABI binding, both diagnostic pipelines through repeated minimize/restore,
Q/X/capture failures, startup refusal before input/model creation, and release of
a virtual held mouse button before policy restoration after a tracking fault.
The minimized/unfocused global-emergency test now runs with a fake applied timer
policy as well. All camera/model/input calls in automated tests are mocked.

An intermittent sandbox temporary-directory permission failure in a diagnostic
test was corrected by locating that test's temporary files within the workspace,
consistent with existing test fixtures. No test was removed or weakened. Numeric
evidence serialization and PowerShell/parser checks are separate from FPS tests.

The measured full run's latest slot overwrote 2,658 unconsumed snapshots from
7,198 publications while consuming/processing 4,540 frames. This is the intended
bounded latest-frame policy, not a backlog or stale-frame replay. No read failures,
delivery timeouts, model/capture stale rejections or worker exceptions occurred.
The host sensor-exposure age and duplicate sensor exposures remain unknown.

Fix-specific source changes are limited to the new shared timer-policy resource,
CLI/lifetime wiring in `camera/benchmark_delivery.py` and
`hand_tracking/hand_tracker.py`, focused tests in
`camera/test_windows_timing.py`, `camera/test_benchmark_preview.py`,
`hand_tracking/test_windows_timing.py` and `controls/tests/test_capture_fence.py`,
plus this guide, relevant READMEs/performance documentation and
`performance_reports/phase3_11_fix.json`. Prior diagnostics, model/gesture/controller
logic and Phase 3.10 documentation are preserved. Final cleanup hardening followed
the hardware runs and changes no acquisition/processing behavior.

Normal-operation recommendation: keep `sync` and `system` as defaults. On this
tested Windows 11 system, explicitly opt into `honor-requests` to prevent the
minimized collapse; select `latest-thread` explicitly when its higher two-hand
throughput is desired. Preserve disarmed startup and complete manual simulated
interaction checks before considering live use. No live-cursor smoothness,
sensor-to-input latency, battery improvement or cross-machine guarantee is claimed.
No work beyond Phase 3.11 was performed. The owner subsequently authorized
committing and pushing this phase using DarshP-Dev.
