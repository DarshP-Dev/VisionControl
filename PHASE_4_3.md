# Phase 4.3 — Face centering and camera movement calculations

Phase 4.3 implements an opt-in **read-only recommendation layer**. It calculates
where the locked face lies relative to the desired center, applies independent
axis hysteresis, and reports bounded conceptual pan/tilt demand. It performs no
camera movement, digital cropping, motor communication or desktop input.
Software validation is complete; physical acceptance is pending owner testing.
The initial delivery left changes unstaged for review; the owner subsequently
authorized committing and pushing Phase 4.3. Phase 4.4 has not begun.

## Starting Git state and verified baseline

Started clean on `main` at `6fa32fa3c3293183ee44ea51fbf751afbaf17bc8`,
`feat(visioncontrol): add persistent face tracking and target locking`.
Git confirms Phase 4.2 was committed; the attachment's older unstaged-work note
was not assumed current. No `AGENTS.md` was found. The complete baseline was
rerun before implementation: **872 tests passed** — camera 75, gestures 165,
hand tracking 259, controls 267 and faces 106. Existing source, Phase 3/4 reports
and documentation were preserved. No dependency or model changes were made.

## Architecture and file changes

The existing camera owner supplies one frame to the optional hand and face paths.
Hand inference, gestures and safety-controller dispatch retain their ordering.
Face detection and Phase 4.2 tracking then produce immutable `TrackedFaces`.
One `FaceCentering` per processing session consumes that snapshot, before preview
rendering, and returns immutable `CenteringResult`. It is independent of hand
controls, association, target selection and model initialization.

Added:

- `face_tracking/centering_geometry.py`: original-frame pixel/normalized offsets.
- `face_tracking/centering.py`: typed configuration/results, freshness validation,
  per-axis Schmitt hysteresis, direction/demand and bounded counters.
- `face_tracking/centering_preview.py`: annotations on the existing preview.
- `face_tracking/benchmark_centering.py`: paired synthetic host and render probes.
- `face_tracking/tests/test_centering.py` and `test_centering_integration.py`.
- This report, `performance_reports/phase4_3_baseline_tracking.json` and
  `performance_reports/phase4_3_synthetic.json`.

Modified `hand_tracking/hand_tracker.py` for opt-in CLI/lifecycle/report plumbing,
the shared face integration-test fixture, and root/hand/face READMEs. The face
tracker, detector, existing overlays, hand recognition/control implementations,
capture owners and Windows timer policy were not modified. There is no new
camera, worker, neural pass, frame copy, output backend or smoothing system.
Disabled centering is not imported or constructed; it adds only inactive branches.

## Geometry and coordinate conventions

Input positions are the locked track's **original-frame** smoothed center;
Phase 4.2 raw centers are retained separately for diagnostics. The existing
640×360 face-inference adapter already maps observations to captured pixels,
for example 1920×1080. Centering validates pixel/normalized consistency rather
than accidentally treating inference pixels as camera pixels.

For original dimensions W,H and the default normalized target `(0.5,0.5)`:

```text
target_px = (W/2, H/2)
error_px = smoothed_center_px - target_px
error = (error_px.x / (W/2), error_px.y / (H/2))
```

| Error | Meaning | Conceptual correction |
|---|---|---|
| X < 0 | Face image-left of target | PAN LEFT |
| X > 0 | Face image-right of target | PAN RIGHT |
| Y < 0 | Face above target | TILT UP |
| Y > 0 | Face below target | TILT DOWN |

The image is unmirrored. Cursor horizontal inversion does not apply here.
There is no rounding before presentation. Geometry validates positive integer
dimensions and finite in-frame coordinates, including continuous outer edges.
Partially off-frame detections use the upstream clipped visible box center.
At the default target, edge errors lie in [-1,1]. `calculate_offsets` and
`CenteringConfig.target` also support an explicit, static normalized target in
[0,1]². The denominator remains half width/height for custom targets; measured
errors can then reach [-2,2], while demand is still clamped to [-1,1]. No automatic
composition, headroom placement or framing rules were implemented.

Advertised 75° FOV is not assumed horizontal or vertical. Angles are deferred
until explicitly supplied/calibrated FOV is available. No value here represents
degrees, physical angle, speed, servo polarity or a motor command.

## Dead zone, hysteresis and normalized demand

Each axis owns only its previous active sign. Defaults are activation **0.12**
and deactivation **0.07**, in normalized half-frame units. An inactive axis
activates only above the outer threshold. An active axis with the same sign
stays active above the inner threshold and deactivates at/below it. Axes operate
independently; the API supports separate per-axis `DeadZone` configurations.
Configuration requires `0 <= deactivation < activation <= 1`.

Reversal policy: a changed sign uses the **opposite activation threshold**. A
small reversal becomes inactive and remains so until a full activation crossing.
A large reversal beyond the opposite outer threshold can immediately change
direction. This prevents tiny sign changes from inheriting an active old direction.
An approximately 1.8e-15 comparison tolerance handles floating-point round-trip
noise exactly at threshold boundaries; it is not a smoothing/dead-zone setting.

For an active axis:

```text
demand = sign(error) * clamp((abs(error)-deactivation)/(1-deactivation), 0, 1)
```

Inactive axes output exactly zero and direction NONE. Raw measured error and
smoothed measured error remain available even inside the dead zone. Demand is
distinct from measured error; no integral, PID, accumulated movement, prediction,
acceleration profile or physical output is produced. Threshold defaults are
starting values for hardware validation, not universal optimal settings.

## Primary tracking integration, availability and freshness

The calculator never selects or switches a target. It consumes the Phase 4.2
primary ID and validates its confirmed/current/certain state. A primary change,
resolution change, loss, uncertainty, invalid/stale input, explicit reset or
reacquisition clears hysteresis. Reacquisition can also be recognized through
the track's restarted match streak if a caller skipped the missing snapshot.
Gaps above the freshness limit clear inherited axis state. New decisions use
only the new current smoothed position; no pre-loss error is carried over.

| Centering status | Demand and current geometry |
|---|---|
| NO_TARGET | Zero; no candidate or confirmed primary |
| WAITING_FOR_TARGET | Zero; tentative/candidate tracks await the tracker lock |
| CENTERED | Fresh confirmed observation; both demands zero |
| CORRECTION_NEEDED | Fresh confirmed observation; one/both axes active |
| TARGET_LOST | Zero; locked track missing, expired or unavailable |
| TARGET_UNCERTAIN | Zero; locked track's association uncertain |
| STALE_OBSERVATION | Zero; actual detection too old or upstream frame stale |
| INVALID_OBSERVATION | Zero; invalid clock/source/geometry/lock/frame metadata |

Uncertainty involving only unrelated tracks does not redirect or disable a
healthy certain primary. If no primary exists, candidate presence reports waiting
instead of selecting one. Unavailable results expose no current raw/smoothed
positions or errors: these are `None`, not `(0,0)`. Historical timestamps/ages
may remain explicit, but historical coordinates never become current recommendations.

`update(..., now=...)` requires host monotonic seconds. It recomputes observation
age from **last actual detection time**, ignoring the snapshot's earlier cached
age. Missing, negative, nonfinite, future or backwards host/detection timestamps
and backwards/invalid source milliseconds suppress demand. Repeated calculations
do not refresh the observation timestamp. Source timestamps use the existing
nonnegative signed-64-bit integer millisecond convention, independently of the
host-clock origin. Reset preserves session monotonic/replay fences; a new session
gets a new calculator.

The default maximum age is **250 ms**. API callers may choose a smaller positive
limit, but cannot loosen it above 250 ms here. Age begins at camera read completion,
not sensor exposure. A result is immutable and valid at `evaluated_at`; its
`actionable` property includes a fresh zero-demand centered hold. A later consumer
must call `fresh_at(now)` and enforce its own safety before using a stored result.
The preview performs that recheck after rendering work and suppresses stale arrows,
errors and face-center marks without advancing the detection timestamp.

There is one calculation per consumed face frame, including minimized/headless
frames. If native inference/read blocks, there is no new observation or intervening
centering output; a static preview cannot repaint itself during a blocked main
thread. This phase adds no actuator that could act on the retained display.
Existing hand watchdog/capture fences remain independent. Any future output
consumer must independently enforce freshness rather than trusting an old label.

## CLI and preview behavior

| Flag | Default and behavior |
|---|---|
| `--face-centering` | Off; automatically enables face tracking and detection |
| `--face-centering-activation VALUE` | 0.12, shared outer threshold for X/Y |
| `--face-centering-deactivation VALUE` | 0.07, shared inner threshold for X/Y |
| `--face-centering-debug` | Off; requires centering; draws dead-zone boundaries |

Frame center is the CLI target; custom static targets are currently API-only.
All Phase 4.1/4.2 options retain their meanings. `--face-only --face-centering`
skips the hand model and rejects hand gestures/desktop controls. `--face-centering`
alone combines hand and face observations on the existing shared capture.
Headless runs use the established `--benchmark --headless` requirement.
`--no-face-overlay` hides face/centering drawing while calculation continues.

Existing face boxes, ID/primary labels, hand landmarks, gesture overlays and
Q/H/A/D remain intact. Two compact rows above the existing bottom face strip show
centering status/direction and measured error versus normalized demand. A small
desired-center cross and current smoothed-center mark indicate the offset;
arrows point from target toward the face for conceptual correction. Optional
inner/outer rectangles expose the dead-zone thresholds. Unavailable/stale results
show CENTERING PAUSED and no current face-center geometry.

Focus changes do not reset tracking/centering. Minimized preview continues
calculation and skips drawing; restore uses the latest fresh result. X retains
existing shutdown/disarm/release cleanup. Capture defaults remain synchronous
MSMF, requested 1920×1080/60 FPS; latest-thread remains experimental. Timer policy
remains system-managed unless `--windows-timer-policy honor-requests` is explicit.

## Diagnostics, benchmarks and CPU/memory measurements

Existing profile/report opt-ins expose `face_centering`, `centering_observation_age`
and `face_centering_overlay` stage summaries. Centering metadata contains bounded
status counts, status-transition counts, direct direction-reversal count, reset
count and preview freshness-suppression count. Counts cover the whole session,
including warmup and an evaluated final frame closed before display; timing
summaries honor existing benchmark warmup rules. Observation-age statistics can
include known last-detection ages of lost targets, distinguished by status counts.
No per-frame disk writes, coordinates, images or application contents are logged.
Profiling disabled adds no new calculation-timer reads in the calculator.

Before integration, the unchanged Phase 4.2 synthetic benchmark was rerun and
saved as [phase4_3_baseline_tracking.json](performance_reports/phase4_3_baseline_tracking.json).
The paired final artifact is
[phase4_3_synthetic.json](performance_reports/phase4_3_synthetic.json), with source
hashes, environment, repeat summaries, CPU samples and separate allocation/render
probes. Earlier phase reports were not overwritten. Timed cases use 2,000 measured
and 200 warmup frames, three repetitions, alternating baseline/centering order.

**All Phase 4.3 measurements here are synthetic host measurements. They exclude
capture, neural inference, HighGUI and physical input. Iterations/second are not
webcam FPS.** The baseline is Phase 4.2 geometry/tracking; the optional two-hand
workload is existing EMA/static recognition only. Pairwise results are more
comparable than subtracting an earlier run on a differently loaded process.

| Faces | Hand host | Tracking mean ms | + Centering mean ms | Added ms | Change |
|---|---|---:|---:|---:|---:|
| 1 | None | 0.0807 | 0.1251 | 0.0444 | +55.1% |
| 1 | Two hands | 0.6906 | 0.7276 | 0.0370 | +5.4% |
| 2 | None | 0.1376 | 0.1774 | 0.0398 | +28.9% |
| 2 | Two hands | 0.7414 | 0.7906 | 0.0492 | +6.6% |
| 4 | None | 0.2984 | 0.3549 | 0.0565 | +18.9% |
| 4 | Two hands | 0.9141 | 0.9755 | 0.0615 | +6.7% |

Values are medians of repeat means. Percentages describe these small host-only
workloads; they are not estimates of full application FPS regression.

| Faces, no hand host | Centering mean ms | Centering P95 ms | Centering P99 ms |
|---|---:|---:|---:|
| 1 | 0.0413 | 0.0551 | 0.0680 |
| 2 | 0.0395 | 0.0436 | 0.0534 |
| 4 | 0.0414 | 0.0576 | 0.0770 |

Each column is a median per-repeat statistic, not a pooled distribution. With
two-hand host work, centering means were 0.0423–0.0433 ms and P99 0.0737–0.0786 ms.
The calculation mean is comfortably below the 0.5 ms engineering target on these
synthetic scenes. The report contains host-total P95/P99; actual camera frame
pacing and 30 FPS combined-preview acceptance remain unmeasured for this phase.

Process CPU milliseconds per iteration, before → after: 0.0859 → 0.1328,
0.1406 → 0.1797 and 0.2969 → 0.3594 for one/two/four faces without hands;
with two-hand host work, 0.6953 → 0.7266, 0.7422 → 0.7891 and 0.9063 → 0.9844.
Short CPU samples have coarse clock quantization. Working-set snapshots spanned
46.14–49.16 MiB in a shared process/allocator and do not isolate centering's
working-set delta or represent the full neural application.

A separate 10,000-frame fixed-geometry probe with changing actual timestamps
retained **440 Python bytes** after collection, with **125,208 peak traced bytes**.
It includes immutable input assembly, not native inference/camera memory. Tests
also exercise varied transitions with bounded state/transition keys. A reused
640×360 canvas rendering probe (1,000 samples) measured existing face annotations
at 0.0560 ms mean versus 0.1337 ms with centering annotations: about **0.0777 ms
added**. This probe excludes HighGUI, hand drawing and camera images; focused,
unfocused and minimized performance still requires matched owner measurements.

## Automated validation and safety

Final regression: camera **75**, gestures **165**, hand tracking **259**, controls
**267**, faces **186** — **952 passing tests**, up from 872. New coverage consists
of 61 geometry/calculation tests and 19 integration/preview/benchmark tests.
No webcam, motor, real cursor, mouse button or keystroke was used in automated tests.

Coverage includes cardinal/corner geometry, original/inference resolution,
clipped boxes, invalid data, all directions, demand bounds, raw versus smoothed
input, exact threshold boundaries, chatter, independent axes, reversal rules,
new IDs, confirmation/lock retention, loss/reacquisition/expiration/crossing,
freshness/repeated calculations/invalid clocks, reset/session isolation, bounded
telemetry, optional profiling and JSON. Integration exercises face-only/combined,
disabled imports, headless, sync/latest-thread, focused/unfocused/minimized/restored,
stale rendering, X/model/camera cleanup, capture failures and calculator failures.

Centering contains no camera, UI, input or motor references. Its only retained
state is configuration, small scalar hysteresis/time/ID fences and bounded counter
keys. The renderer separately annotates the existing preview. A calculator fault
uses existing fail-closed cleanup: simulated held drag is released, controller
disarmed, capture stopped and model/camera cleanup remains owned by `run()`.
Faces never arm or dispatch via the desktop controller.

Existing regression suites preserve disarmed startup, explicit live opt-in, A/D,
Ctrl+Shift+F10 configuration, generation cancellation, freshness, capture-health
fences, watchdog, tracking-gap cancellation, safe release, rearming and reliable
shutdown. The 3/4-hand observation-only restriction is unchanged. No concurrency,
global timer-policy change or scheduling modification was added.

## Exact owner-run PowerShell acceptance

Use fresh timestamps for every repeat. These commands preserve earlier results;
the application refuses existing report names. The user performs hardware tests.
No hardware acceptance is claimed from the automated or synthetic measurements.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase43Tag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'

# A-F: face-only centering, raw/smoothed points and visible inner/outer dead zones.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-centering --face-centering-debug --face-tracking-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_3_visual_${phase43Tag}.json"

# Optional threshold comparison. Keep the scene and other settings the same.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-centering --face-centering-activation .16 --face-centering-deactivation .09 --face-centering-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_3_tuning_${phase43Tag}.json"

# Matched headless Phase 4.2 versus 4.3. Combined runs: same two hands + one face.
foreach ($phase43Mode in 'faces_tracking','faces_centering','combined_tracking','combined_centering') {
  $phase43Flags = @('--face-tracking')
  if ($phase43Mode.StartsWith('faces')) { $phase43Flags += '--face-only' }
  if ($phase43Mode.EndsWith('centering')) { $phase43Flags += '--face-centering' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase43Flags --headless --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --report "hand_tracking/benchmarks/owner_4_3_${phase43Mode}_${phase43Tag}.json"
}

# H: EACH run after warmup: 0-30 focused, 30-60 unfocused/visible,
# 60-90 minimized, 90-120 restored/focused. Keep two hands + one face steady.
foreach ($phase43Mode in 'tracking','centering') {
  $phase43Flags = @('--face-tracking')
  if ($phase43Mode -eq 'centering') { $phase43Flags += '--face-centering' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase43Flags --benchmark --warmup 5 --duration 120 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_3_window_${phase43Mode}_${phase43Tag}.json"
}

# G: gesture compatibility, SIMULATION only. Starts DISARMED; manually A/D.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-centering --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --windows-timer-policy honor-requests --performance-profile --report "hand_tracking/benchmarks/owner_4_3_sim_${phase43Tag}.json"

# Offline reproducible benchmark: no capture, models, HighGUI or input.
.\.venv\Scripts\python.exe -m face_tracking.benchmark_centering --frames 2000 --warmup 200 --repeats 3 --faces 1 2 4 --report "hand_tracking/benchmarks/owner_4_3_synthetic_${phase43Tag}.json"

.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s face_tracking/tests -t . -q
```

A: sit centered, then move slightly inside the boundary; errors should vary while
demand stays exactly zero. B: move image-left/right, verify conceptual pan-left/right
and increasing demand; return to center. C: move up/down and verify tilt-up/down.
D: hover around both thresholds, checking activation/deactivation and small
reversal suppression; compare 0.12/0.07 with an explicitly recorded tuned run.
Existing EMA may delay response; no extra centering smoothing was added.

E: cover/leave briefly, verify paused status, zero demand and no current arrows;
return within 800 ms near the old position to test plausible recovery, then leave
longer to test expiry/new ID. Observe that no pre-loss demand survives. F: establish
one primary, introduce a second person, and verify centering follows only the
original lock even when the newcomer has a larger box/higher score. Crossings
should suppress an uncertain primary; geometric continuity is not identity proof.
If a second person is unavailable, report this as synthetic-only validation.

G: in simulation manually arm, test palm/pointing/pinch/drag/swipes and left-pinch
rearm/resume, then D/Q/X during virtual drag. Face centering must never arm or
generate desktop actions. Simulation does not register a live global shortcut;
this does not establish physical emergency-hotkey acceptance.

H: time states from the warmup-complete message, inspect actual state residency,
and verify that minimizing alone does not reset IDs or timestamps. Close X and
verify resource release. Repeat matched pairs in reverse order with the same
resolution, lighting, face/hand counts and resource load. Repeat with fresh names
and `--capture-pipeline latest-thread` to assess producer FPS separately; never
run two camera consumers at once. `honor-requests` remains opt-in.

Inspect `average_application_fps`, inference/centering/age stages in `timings`,
`pacing.by_preview_state` completion P95/P99/FPS, actual detected hand/face counts,
`resources`, `memory`, and `face_centering.states/transitions`. Stale counts are
`face_centering.states.STALE_OBSERVATION`; delayed-render suppressions are
`face_centering.preview_freshness_suppressions`. When using latest-thread,
`capture_pipeline.capture_worker_delivery_fps` is producer delivery, not processed
FPS. Sync capture throughput is consumer/read throughput, not an independent
sensor FPS measurement. Transition populations may mix window states.

## Limitations and Phase 4.4 recommendation

Physical centering accuracy, threshold feel, EMA delay, gesture compatibility,
camera throughput, frame pacing and focus/minimize performance remain pending.
Synthetic zero-age observations do not validate real sensor latency or a full
30 FPS preview target. No optical calibration is implied. Position-only tracking
can lose or misassociate faces in difficult scenes; the conservative tracker and
primary uncertainty flag remain authoritative. Native stalls can leave static UI
pixels visible until the main thread resumes, so future consumers need their own
freshness checks. Reports contain bounded aggregate samples, not motion histories.

After owner acceptance, Phase 4.4 can separately design digital reframing that
consumes fresh, confirmed, certain recommendations while preserving the original
analysis frame and specifying paused/target-loss behavior. No crop, reframing,
motor/Pi interface, calibration, face-to-hand ownership or physical command was
implemented here. Suggested eventual commit:
`feat(visioncontrol): add face centering and movement calculations`.
