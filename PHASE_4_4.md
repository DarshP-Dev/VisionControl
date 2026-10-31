# Phase 4.4 — Digital auto-framing and smooth virtual camera following

Implemented a fixed-size translating virtual crop, a separate output preview,
bounded time-aware following and explicit hold behavior. All hand/face inference
and desktop-control coordinates remain on the original capture. No physical
movement, optical zoom, virtual webcam driver or Phase 4.5 feature is implemented.
Phase 4.4 physical acceptance is pending owner testing. The initial delivery left
changes unstaged for review; the owner subsequently authorized committing and
pushing Phase 4.4.

## Initial state and regression baseline

Started clean on `main`, HEAD `83a6dbfdec937e63af8c36736ad93fba4c71dbd7`,
`feat(visioncontrol): add face centering and movement calculations`.
Git confirms Phase 4.3 is committed, superseding the attachment's older unstaged
note. The owner reports successful Phase 4.3 hardware checks in this request;
that is not a fresh Phase 4.4 measurement. Existing Phase 4.1–4.3 documents and
numeric evidence remain intact. No `AGENTS.md` was found.

Reconfirmed **952 baseline tests** before changes: camera 75, gestures 165, hand
tracking 259, controls 267, faces 186. Current environment, capture, model and
dependency versions were retained. MSMF, requested 1920×1080/60 FPS, default sync
capture and system-managed timer policy remain unchanged.

## Architecture and files

The existing camera owner supplies the full BGR frame. The hand path retains
preprocessing/inference, gestures and safety-controller dispatch; the face path
retains detection, association/locking, smoothing and centering. A new per-session
`DigitalReframer` consumes the immutable centering result. That result already
expresses the current confirmed primary's smoothed original-frame position,
availability and actual detection timestamp. No second face-selection policy or
neural pass is added.

The reframer produces geometry only. A separate renderer slices the current
original image for output; cropped pixels never feed back into inference, gesture
geometry or cursor mapping. Source-frame overlays remain on the existing original
preview buffer. One camera/model ownership chain and one existing HighGUI event
pump serve both windows on the main thread. No new workers are introduced.

Added `face_tracking/digital_reframing.py`, `reframing_models.py`,
`reframing_preview.py`, `benchmark_reframing.py`, two focused test modules,
this document and `performance_reports/phase4_4_baseline.json` /
`phase4_4_synthetic.json`. Modified `hand_tracking/hand_tracker.py` and the root,
hand and face READMEs. Detector, tracker, centering, gesture, control, capture,
GUI-helper and Windows-timing implementations are preserved.

## Viewport geometry, aspect and output units

The default scale is **2/3 of both source dimensions**. At 1920×1080 this is
exactly 1280×720. Crop dimensions independently round the equally scaled axes
half-up, clamped to at least one pixel and no larger than the source. For odd or
coprime dimensions an exact fractional aspect cannot always be represented by
integer pixels: each scaled dimension is within half a pixel of the ideal.
For example 1921×1081 becomes 1281×721; 640×360 becomes 427×240. This is raster
rounding, not image stretching. At tiny scales the minimum one-pixel crop imposes
large composition/aspect granularity; useful hardware settings need visual review.

Continuous source-pixel crop-center bounds are:

```text
Cw/2 <= Cx <= W-Cw/2
Ch/2 <= Cy <= H-Ch/2
```

For the default source/crop: X 640–1280, Y 360–720. Crop initialization and source
resolution changes start at source center. Slicing uses exclusive right/bottom
edges, a fixed crop width/height, half-up integer origins and clamping at every
update. `CropRectangle.center` exposes the raster center; `ReframeResult.center`
is the continuous animation state. They may differ by at most half a pixel per
axis. Composition error is reported against the actual integer slice.

The renderer respects the slice's aspect ratio, fits within **960×540 display
bounds**, and never upscales. Native crop resolution and display resolution are
distinct. A view is extracted with NumPy slicing and marked read-only; annotations
use a separate reused output buffer. Downscaling writes directly into that buffer;
an already-fitting crop is copied before labeling. No extra full-source copy or
color conversion is introduced. A scale of 1 is valid but offers no movement room.

## Following algorithm and composition

Default crop composition is `(0.5,0.5)`. `ReframeConfig.composition` supports an
explicit fixed normalized point in [0,1]²; the CLI keeps centered composition.
No headroom, gaze, dynamic composition, subject-size adjustment or zoom is added.
For composition `(tx,ty)`:

```text
crop_composition_source = current_center + ((tx-.5)*Cw, (ty-.5)*Ch)
crop_error = (face_source - crop_composition_source) / (Cw/2, Ch/2)
raw_desired_center = face_source - ((tx-.5)*Cw, (ty-.5)*Ch)
desired_center = clamp(raw_desired_center, valid_crop_center_bounds)
```

The existing smoothed face position is reused. Original-frame Phase 4.3 demand
is **not integrated**. CENTERED and CORRECTION_NEEDED centering snapshots are both
eligible when fresh, because original-frame and crop-relative centers differ.
When the face is outside the current crop, crop-relative errors/positions can
legitimately lie outside [-1,1]/the crop; they are not servo commands or fabricated
pixels. The viewport moves toward the face within available source boundaries.

Independent crop-relative Schmitt axes use default activation **0.10** and
deactivation **0.06** of half crop width/height: 64/38.4 horizontal pixels and
36/21.6 vertical pixels for 1280×720. Public Phase 4.3 `DeadZone` validation and
freshness conventions are reused; its original-frame demand is not reused.
The original geometry helper rejects points outside its image, so crop-relative
errors are computed directly to support a face temporarily outside the viewport.

Inactive axes hold their current center. Active axes move toward the clamped
desired center. Same-sign motion deactivates at/below the inner threshold; a
sign reversal must exceed the opposite outer threshold. Numerical threshold
round-trip noise uses the same approximately 1.8e-15 tolerance as centering.
Stationary faces settle within the inner band instead of causing micro-movement.

## Smoothing, speed and time

Viewport response has its own **200 ms tau**, distinct from the tracker's 70 ms
observation EMA. Each update uses `alpha = 1-exp(-dt/tau)` and a step toward the
valid desired center. Tau zero bypasses EMA but retains all limits. The complete
two-dimensional step is capped to **600 source pixels/second × dt**, preventing
faster diagonal motion. Interpolation and final clamping cannot overshoot bounds.
At 60 FPS this is at most 10 continuous pixels per regular frame; at 30 FPS, 20.

No elapsed-time debt is accumulated. First observations, recovery from hold,
new primary IDs and gaps over **250 ms** restart timing with a zero-distance first
step. Subsequent integration dt is capped at **100 ms**. This avoids a large
restoration/reacquisition lurch. Very low delivery rates with repeated >250 ms
gaps can keep movement paused; stability is preferred to catch-up jumps.
Changing source dimensions reinitializes a centered fitting crop and timing.

At a constrained edge, an EMA's otherwise invisible tail finishes when the
remaining displacement is <=0.01 source pixel and within the current speed
budget. This prevents indefinite internal drift without a visible snap or
speed-limit violation. Integer slicing adds at most pixel-scale quantization;
the Euclidean speed limit applies to continuous motion, not subpixel interpolation
of raster output. There is no PID, extrapolation, spring, command accumulation or
physical movement model.

## Tracking loss, freshness, boundaries and result models

`DigitalReframer.update(CenteringResult, source_size=(W,H), now=host_time,
profile=optional)` returns immutable `ReframeResult`. It exposes primary ID,
TRACKING/HOLDING status and reason, source/crop dimensions, integer rectangle,
continuous center, valid desired center, current target position/error within the
slice, axis activity, boundary constraints, actual detection timestamp/age,
fresh-target availability and moving/holding state.

Only the validated locked primary's fresh smoothed center is used. Inconsistent
dimensions/IDs, invalid clocks/positions, tentative/unavailable/lost/expired or
uncertain targets hold the last safe viewport immediately. Paused results have
no new desired center, current face-in-crop position or error; historical geometry
never becomes a fresh target. The held viewport displays **new camera frames**,
not a frozen historical image. Reacquisition or a newly selected primary resumes
gradually from the held crop; the reframer never chooses another person.

Freshness is recomputed from the actual detection timestamp using the existing
250 ms maximum. Repeated/backward source observations cannot drive another step;
source fences also advance across stale observations. Host and actual-detection
times must be monotonic; no timestamp is invented by animation. Reset retains
session clock/source fences, while a new session gets a new reframer. Stored
results expose `fresh_at(now)` for later display/consumer checks. The preview labels
an aged result as paused, while continuing to show the bounded current crop.

Boundary constraints are explicit LEFT/RIGHT/TOP/BOTTOM flags on the desired
composition. Targets are clamped before interpolation, so an uncenterable face
does not produce a continually advancing impossible target. For example a face
at source X=1700 has a right-constrained desired center of 1280, not 1700, for
the default crop. Edge limitations are expected; no wrapping or synthesized
content is used. Position-only face IDs remain continuity observations, not proof
of real-world identity. Existing conservative crossing handling remains authoritative.

## Two-window lifecycle and CLI

The original `VisionControl - Hand Tracking` preview retains all existing hand,
face and centering overlays. `--reframe-debug` optionally outlines the actual crop.
The separate `VisionControl - Digital Auto-Frame` window shows pristine source
crop pixels and a minimal face/paused/boundary label. It does not duplicate hand
or face inference. Main-thread HighGUI events serve both windows; auxiliary
handling adds owned-window state checks, not a second event loop.

Native Win32 window detection uses the existing PID/title/class HWND ownership
checks independently for both windows, distinguishing minimized from closed.
Each visible window renders independently; minimizing one does not suppress the
other. Both minimized skip all preview preparation/crop extraction while face,
hand and viewport processing continue. Restoring shows the latest bounded state,
without queued frames or elapsed-time catch-up. A crop may have legitimately
followed fresh observations while hidden; restoring does not rewind that history.
The portable fallback retains its existing limited focus/minimize observability.

Auxiliary **X disables only that preview for the session**, frees its display
buffer, and does not stop capture/calculation or disarm controls. It is not
silently reopened; restart the application to reopen it. Original X retains
safe session shutdown. Q from either preview quits; existing A/D/H semantics,
global emergency handling and camera/model cleanup remain intact.

| Flag | Default / behavior |
|---|---|
| `--digital-reframe` | Off; implies face centering, tracking and detection |
| `--reframe-preview` / `--no-reframe-preview` | Secondary window on when reframing is enabled; disable for calculations only |
| `--reframe-scale` | 2/3, finite (0,1] fraction on each source axis |
| `--reframe-follow-tau` | 0.2 seconds; finite nonnegative |
| `--reframe-max-speed` | 600, finite positive Euclidean source pixels/second |
| `--reframe-dead-zone` | 0.10 outer half-crop fraction; inner = 60% of outer; (0,1] |
| `--reframe-debug` | Off; requires reframing; original-preview crop outline |

Separate axis thresholds and fixed composition are API-only. Face-only mode
skips the hand model and rejects desktop controls. Existing hand-only, stateless
face, tracking and centering commands are unchanged. Headless benchmark mode
performs geometry only, with no crop renderer, image extraction or second window.
`--windows-timer-policy honor-requests` remains explicit; sync/system defaults
and experimental latest-thread compatibility are preserved. This output is not
a system-wide virtual webcam and installs no driver or OBS integration.

## Profiling and reproducible performance evidence

Existing benchmark/profile/report opt-ins now expose `reframe_update`,
`reframe_observation_age`, `reframe_crop_extraction`, `reframe_rendering`,
`reframe_imshow`, `reframe_preview_total` and optional `reframe_debug_overlay`.
Original `gui_total` remains the original-window event/display series; inspect
the separate auxiliary stages and total processing/frame intervals for dual-window
costs. Application end-to-end/pacing times include auxiliary display work.

`digital_reframing` metadata includes configuration, bounded hold/follow reasons,
timing/source restarts, moving/stationary updates, boundary counts, accumulated
distance and maximum continuous step. Secondary metadata records rendered/skipped
frames, actual state distribution and close policy. Counters cover the whole
session including warmup; stage timings use existing measured/warmup rules.
Reports contain no images or per-frame face/crop coordinates. Calculation timing
reads are absent when profiling is disabled; disabled reframing is not imported.

Before integration, the unchanged Phase 4.3 benchmark was saved as
[phase4_4_baseline.json](performance_reports/phase4_4_baseline.json).
The paired final artifact
[phase4_4_synthetic.json](performance_reports/phase4_4_synthetic.json) contains
source hashes, repeat results, CPU/memory samples and separate state/render probes.
Timed host cases use 1,000 measured + 100 warmup iterations, three repetitions,
alternating centering-only/reframing order, one/two/four faces and optional
existing two-hand EMA/static recognition fixtures.

**These are synthetic host costs, excluding capture, neural inference, HighGUI
and desktop input. Iteration rates are not measured webcam/application FPS.**
Synthetic observation ages are zero by construction; they do not establish
sensor-to-display latency or camera frame-pacing consistency.

| Faces | Hand host | Centering baseline mean ms | + Reframing mean ms | Added ms | Change |
|---|---|---:|---:|---:|---:|
| 1 | None | 0.1429 | 0.2124 | 0.0695 | +48.6% |
| 1 | Two hands | 0.8942 | 0.9728 | 0.0786 | +8.8% |
| 2 | None | 0.2257 | 0.2849 | 0.0592 | +26.2% |
| 2 | Two hands | 0.9822 | 1.0437 | 0.0615 | +6.3% |
| 4 | None | 0.4411 | 0.4913 | 0.0503 | +11.4% |
| 4 | Two hands | 1.2047 | 1.2763 | 0.0717 | +5.9% |

Values are medians of repeat means; percentages apply only to these small host
workloads, not the full camera application. Separately median viewport-stage
means/P95/P99 were 0.0562/0.0856/0.1175 ms for one face, 0.0575/0.0840/0.2027 ms
for two, and 0.0941/0.4446/0.8620 ms for four without hand host work. With two
hands, viewport means were 0.0593–0.0611 ms and P99 0.1195–0.1358 ms. The four-face
tail is not a demonstrated geometry scaling effect: this module consumes one
primary and all host stages remain subject to GC/scheduling/other work. Raw per-run
tails are preserved rather than claiming a stall-free result.

Process CPU ms/iteration before → after: 0.1406 → 0.2188, 0.2188 → 0.2813,
0.4375 → 0.4844 for one/two/four faces alone; with two-hand host work,
0.8750 → 0.9531, 0.9688 → 1.0156 and 1.2031 → 1.2500. CPU samples are coarse
for short cases. A separate 10,000-update fixed-geometry state probe retained
**264 Python bytes** after collection, with **125,464 peak traced bytes** including
immutable input assembly. This does not measure native camera/model memory.

A 500-sample synthetic display-preparation probe used full 1920×1080 blank frames,
the existing 1100×619 original preview, and the default 960×540 crop display.
Original-only preparation averaged **0.8100 ms** (P95 1.2632, P99 1.7166);
dual preparation averaged **1.3231 ms** (P95 1.9313, P99 2.2135): about **0.5130 ms
added**. Inside dual preparation, slicing averaged 0.0104 ms and crop resize/labels
0.4475 ms. These are preparation times, not HighGUI/window behavior or real FPS.

The original display buffer is 2,042,700 bytes; the secondary adds **1,555,200
bytes** while visible. It is reused and released on auxiliary closure/session
cleanup. Sample process working sets were 74,063,872 and 75,665,408 bytes in a
shared process/allocator, not isolated memory deltas. Rendering process CPU rose
from 6.5313 to 12.1250 ms/iteration, with native OpenCV worker CPU included; 100%
of one core is not a machine-wide utilization percentage. The short, sequential
probe does not establish physical-camera CPU/power costs. A second display has
measurable cost: minimize it or use `--no-reframe-preview` when assessing geometry
alone. No global OpenCV thread count or camera/inference resolution was changed.

Phase 4.4 processed webcam FPS, worker delivery, inference latency, actual frame
P95/P99 and visible/minimized behavior remain unmeasured pending owner acceptance.
The historical approximately 30 FPS combined-preview result is not substituted
for a fresh result, and no 60 FPS end-to-end or 30 FPS dual-window claim is made.

## Automated tests and safety validation

Final suites: camera **75**, gestures **165**, hand tracking **259**, controls
**267**, faces **256** — **1,022 passing tests**, up from 952. The 70 new tests
cover crop geometry/slicing, odd dimensions/bounds, directions, fixed points,
crop-relative dead zone, no original-demand drift, variable dt/30/60 FPS,
vector speed/no overshoot, large-gap restart, invalid/repeated/backward clocks,
source fences, clamped targets, composition, immutable snapshots, bounded state,
loss/recovery/new IDs, stale/uncertain/unavailable targets and source resolution.

Renderer/integration tests verify read-only slices, source pixel isolation,
reused buffers/live video during hold, stale labels, original-only and dual modes,
independent minimize/restore/closure, no extra event loop, one camera/model owner,
headless/disabled allocation paths, full-frame hand/face inputs, camera failures,
geometry/render failures, simulated drag release, model/window/camera cleanup and
benchmark JSON/provenance. Synthetic frames, fake tasks/cameras and simulation
backends require no physical webcam, native input or motors.

No control/capture safety implementation changed. Disarmed startup, explicit live
opt-in, A/D, Ctrl+Shift+F10 support, tracking-loss cancellation, the 250 ms
freshness gate, 500 ms watchdog, capture-health fence, stale-frame rejection,
button release, gesture rearming and safe shutdown retain their regression tests.
Face-to-hand ownership and the 3/4-hand observation-only restriction are unchanged.
Reframing calculations have no input/camera/model APIs. Failures use existing
fail-closed cleanup; test faults release a simulated held mouse button.

## Exact owner-run PowerShell acceptance

Run matched comparisons sequentially, keeping camera settings, one face/two hands,
lighting, pose and system load comparable. Use fresh timestamps for every repeat;
existing report paths are refused. No commands below enable real desktop input.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase44Tag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'

# A-G: two face-only previews, with the crop outlined on the original.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --digital-reframe --reframe-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_4_visual_${phase44Tag}.json"

# Explicit responsiveness comparison; fixed scale, no auto-zoom.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --digital-reframe --reframe-follow-tau .12 --reframe-max-speed 900 --reframe-dead-zone .08 --reframe-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_4_tuning_${phase44Tag}.json"

# H / paired headless geometry: same two hands + one face in combined runs.
foreach ($phase44Mode in 'faces_baseline','faces_reframe','combined_baseline','combined_reframe') {
  $phase44Flags = @('--face-centering')
  if ($phase44Mode.StartsWith('faces')) { $phase44Flags += '--face-only' }
  if ($phase44Mode.EndsWith('reframe')) { $phase44Flags += '--digital-reframe' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase44Flags --headless --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --report "hand_tracking/benchmarks/owner_4_4_${phase44Mode}_${phase44Tag}.json"
}

# Isolate original preview versus calculations-only versus dual-preview cost.
# First run face-only, then combined; keep equivalent scenes within each group.
foreach ($phase44Group in 'faces','combined') {
  foreach ($phase44Mode in 'baseline','calculations','dual') {
    $phase44Flags = @('--face-centering')
    if ($phase44Group -eq 'faces') { $phase44Flags += '--face-only' }
    if ($phase44Mode -ne 'baseline') { $phase44Flags += '--digital-reframe' }
    if ($phase44Mode -eq 'calculations') { $phase44Flags += '--no-reframe-preview' }
    .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase44Flags --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_4_preview_${phase44Group}_${phase44Mode}_${phase44Tag}.json"
  }
}

# I: after 5s warmup, 0-30 original focused; 30-60 both visible/unfocused;
# 60-90 original minimized, crop visible; 90-120 both minimized;
# 120-150 original restored, crop minimized; 150-180 both restored.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --digital-reframe --benchmark --warmup 5 --duration 180 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_4_windows_${phase44Tag}.json"

# H: gesture/control compatibility, SIMULATION. Starts DISARMED; manually A/D.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --digital-reframe --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --windows-timer-policy honor-requests --performance-profile --report "hand_tracking/benchmarks/owner_4_4_sim_${phase44Tag}.json"

# Reproduce host/render measurements without camera, models or HighGUI.
.\.venv\Scripts\python.exe -m face_tracking.benchmark_reframing --frames 1000 --warmup 100 --repeats 3 --render-frames 500 --report "hand_tracking/benchmarks/owner_4_4_synthetic_${phase44Tag}.json"

.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s face_tracking/tests -t . -q
```

A: verify both previews, matching aspect/no distortion, valid initial crop and
the locked ID. B/C: move horizontally/vertically, observe gradual motion, limits
at each source edge and crop-relative centering. D: hold still and make small
movements; verify settling without vibration/drift. E: move quickly, observe the
bounded response, then stop and allow catch-up. Tuning values are explicit
experiments, not measured better defaults. No optical zoom occurs.

F: cover/leave briefly and verify immediate hold after detection loss while new
video pixels continue. Return within the tracker's 800 ms recovery window near
the old position, then test longer expiry/new ID and gradual transition. G: add
a second person after locking the first; verify the newcomer cannot steal the
viewport. During uncertain crossings expect hold, not identity recognition. If
no second person is available, mark this as synthetic-only validation.

H: keep hand coordinates/gestures correct on the original view while the crop
moves. In simulation manually arm and test palm cursor, pointing swipes, pinch
click/drag/release, tracking loss/rearm and left-pinch resume. D/Q/original X must
release a virtual drag; auxiliary X only disables the crop window. Face appearance
or reframing must not arm controls or issue actions. Simulation does not register
a live global shortcut and does not establish physical emergency-hotkey acceptance.

I: time states from warmup completion and inspect actual residency. Check both
minimize cases independently, restoration without delayed-time jumps, auxiliary
X continuation, original X cleanup and a fresh restart. The crop may legitimately
move while hidden if fresh tracking continues. Repeat matched runs in reverse
order. For experimental worker delivery, use fresh report names and replace
`--capture-pipeline sync` with `latest-thread` in each corresponding comparison;
do not open two camera consumers simultaneously.

Inspect measured application FPS and total frame P95/P99, inference/tracker/
centering/reframe stages, observation ages, CPU, memory, detected hand/face count
distributions, `digital_reframing.reasons/counters` and
`digital_reframing.secondary_preview.frames_by_state`. Original preview focus
states are in existing pacing reports; when the crop is focused the original is
unfocused, so use both state populations. Worker delivery FPS is
`capture_pipeline.capture_worker_delivery_fps` only for latest-thread. Sync read
throughput is not an independent sensor FPS measurement. Do not confuse hidden
rendering savings with inference improvements or intentional holds with tracking loss.

## Remaining limits and Phase 4.5 recommendation

Physical following quality, the two-stage smoothing delay, dead-zone/speed tuning,
dual-window FPS, CPU/power and minimized behavior await owner acceptance. Pixel
rounding, finite source boundaries and a fixed crop limit composition; the face
can leave the viewport briefly during fast movement. Larger scale leaves less
translation room; smaller scale changes output composition but is not optical
zoom. Low-rate/stalled streams hold conservatively. Spatial IDs cannot guarantee
identity through difficult crossings, and no hand ownership is inferred.

Current summaries are bounded numeric aggregates, not complete motion histories.
Native main-thread stalls can leave previously displayed pixels visible until
the event loop resumes; independent desktop safety remains active. A stored
viewport is not permission for a future actuator. If owner tests show meaningful
render cost, a separately measured auxiliary refresh cadence may be considered;
no speculative thread/priority/global OpenCV scheduling change was introduced.

After owner review, Phase 4.5 can separately define a motor-controller interface,
explicit units/polarity and independent safety/freshness requirements. Do not
derive servo angles from crop pixels or advertised uncalibrated 75° FOV. No
motor/Pi/driver, optical calibration, face-to-hand association, voice or new gesture
work was implemented. Suggested eventual commit:
`feat(visioncontrol): add smooth digital face auto-framing`.
