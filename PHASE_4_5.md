# Phase 4.5 — Simulated motor controller and conceptual pan/tilt mount

Implemented a hardware-independent motor planning/safety layer, deterministic
virtual motor dynamics, an optional OpenCV visualizer, a separate synthetic
closed-loop scene and editable OpenSCAD concept source. **Hardware output is
always disabled.** No GPIO, PWM, serial, network, Raspberry Pi or real motor
driver is implemented. The implementation was handed off without staging,
committing or pushing; the owner subsequently authorized committing and pushing
Phase 4.5. Phase 4.6 has not begun; owner application/CAD acceptance remains pending.

## Initial Git state and verified baseline

Started clean on `main`, HEAD `9fdf0d0a396267486d435b916a10a6f2fd2d00de`,
`feat(visioncontrol): add smooth digital face auto-framing`. Git confirms Phase
4.4 was committed, superseding the request's older unstaged-work note. The owner
reports successful Phase 4.4 hardware acceptance; no new Phase 4.5 webcam or
physical motor results are inferred from that report. No `AGENTS.md` was found.

All **1,022 existing tests** passed before modifications: camera 75, gestures
165, hand tracking 259, desktop controls 267, face tracking/centering/reframing
256. Existing Phase 4.1–4.4 source, documents and evidence were preserved. Camera
and inference settings, dependencies and Windows timer/capture defaults remain
unchanged. No additional application dependency was installed.

## Architecture and files

The existing single camera/frame still supplies hand inference/gestures/desktop
controls and face detection/tracking/locking/smoothing. After face centering, the
immutable result branches independently to existing digital reframing and the
new motor adapter. The motor path never changes the original image, crop inputs,
hand coordinates, primary selection or existing input-controller state.

```text
Locked fresh centering snapshot -> centering_adapter -> normalized MotorInput
 -> MotorController validation/planning -> bounded MotorCommand
 -> SimulatedMotorDriver -> immutable MotorState -> optional motor window
```

`MotorController`, models and simulated driver contain no face/MediaPipe, camera,
GUI or device APIs. Only `centering_adapter.py` bridges face-specific results.
The visualizer owns one reusable canvas, not a GUI loop. All HighGUI creation,
event pumping, state checks/display/destruction stay on the existing main thread.
No new camera owner, model pass, frame copy, background thread or hardware factory
is introduced. The `MotorDriver` protocol documents a future interface; Phase 4.5
constructs only `SimulatedMotorDriver` and has no live backend selector.

Created `motor_control/` with `models.py`, `controller.py`, `simulator.py`,
`centering_adapter.py`, `closed_loop.py`, `visualization.py`, `benchmark.py`,
README, four test modules and `examples/virtual_state.png`. Created
`hardware/concepts/pan_tilt_concept.scad` and its README, this report and five new
numeric artifacts under `performance_reports/phase4_5_*.json`. Modified
`hand_tracking/hand_tracker.py` and root/hand/face READMEs. Existing face, hand,
gesture, desktop safety, capture-owner, GUI-helper and timing implementations
are unchanged.

## Public models and units

| Model | Meaning |
|---|---|
| AxisConfig / MotorConfig | Virtual min/max/home degrees, speed deg/s, acceleration deg/s², update/freshness limits |
| MotorInput | Normalized pan/tilt demand, actual observation time, source milliseconds, primary ID and validity/reason |
| AngularVelocity | Separate virtual pan/tilt deg/s values |
| MotorCommand | Requested versus accepted velocities, source metadata, validity and reason |
| AxisState | Actual simulated angle/velocity, target velocity, min/max flags |
| MotorState | Both axes, command, status/reason, update time and last valid update; immutable hardware-output flag false |

Normalized error/demand, pixels and angular units are not mixed. Positive pan
means scene-right; negative pan left. Positive tilt means down; negative tilt up.
These are conceptual conventions, not future motor shaft/wiring polarity.
Constructor home initializes virtual angles; it does not measure or home hardware.
Enable/disable and stops retain pose instead of teleporting home.

Default illustrative settings:

| Axis | Software angle envelope | Max speed | Max acceleration | Home |
|---|---|---|---|---|
| Pan | -45° to +45° | 30°/s | 60°/s² | 0° |
| Tilt | -25° to +25° | 20°/s | 40°/s² | 0° |

These are not specifications for any motor or mount. Typed configuration supports
asymmetric bounds, independent acceleration and home. Software sanity validation
requires finite values, -180<=min<max<=180, home inside bounds, speed (0,360]
deg/s and acceleration (0,3600] deg/s². These caps are not hardware certification.
Update/freshness limits are positive and at most 250 ms.

## Planning, dynamics and limits

The adapter accepts only the confirmed, current, certain centering primary and
rechecks geometry, timestamp/freshness, axis activity, direction and finite demand.
Raw face coordinates are never converted directly into motor angles. The generic
controller independently validates the normalized input and source metadata.

For normalized demand `(p,t)`, define `k=max(1,hypot(p,t))`:

```text
requested_pan_deg_s  = (p/k) * max_pan_speed
requested_tilt_deg_s = (t/k) * max_tilt_speed
```

This prevents diagonal amplification in per-axis-speed space while respecting
each independent speed bound. Out-of-range/nonfinite demands are rejected, not
silently treated as physical commands. Axis limits suppress outward accepted
velocity while retaining the raw requested velocity for diagnostics. An inward
request can move away from a limit on a later fresh update.

Ordinary nonzero motion follows a common velocity-ramp duration:
`T=max(abs(target_velocity-current_velocity)/axis_acceleration)` over both axes.
Velocity moves along a straight line in velocity space, preserving normalized
vector bounds and keeping each acceleration at/below its configured maximum.
Position integrates analytically across the ramp and any remaining constant-speed
interval. The constant-command test reaches exactly 22.5° after one second at
30°/s with 60°/s² acceleration, consistently at 30 and 60 FPS. Changing feedback
commands across sample rates is only approximately equivalent, as expected.

The driver enforces bounds again. It checks velocity-zero extrema as well as end
positions, so an intermediate reversal peak cannot pass a limit and return inside
unnoticed. A limit hit clamps pose and zeroes actual velocity, target velocity and
the accepted command in that same update; later fresh inward motion is permitted.
No periodic wrapping, PID, torque/load model or accumulated position command is used.

An inactive/zero-demand axis stops **immediately**, without coasting, even while
the other axis continues. Unsafe stops and limit stops also bypass ordinary
acceleration ramps. This is an explicit simulation safety policy, not a claim
that real mechanics can stop instantly. Ordinary nonzero direction reversals
decelerate through zero under the acceleration bound, so actual velocity may
briefly retain its old direction while requested velocity has reversed.

## Time, safety and stopping behavior

The controller is disabled by default. The application explicitly constructs it
enabled only for `--motor-simulate`. No key or validated simulated command can
enable physical output. Every `MotorState.hardware_output_enabled` is false and
cannot be set through the dataclass initializer/replacement interface.

Default maximum control interval is **100 ms**; maximum actual observation age
is **250 ms**. Both use supplied monotonic host seconds. Source timestamps retain
the signed-64-bit nonnegative millisecond convention independently of host origin.
Repeated/backward host/source/actual-observation timestamps are rejected. Actual
detection time and last valid update are never refreshed by reusing a command.

Missing, tentative, lost, expired, uncertain, stale, malformed or unsupported
input clears accepted velocity and immediately zeroes both simulated velocities.
Positions remain held. Long update gaps report STALLED and discard the entire
elapsed movement backlog. The current observation is consumed; replay cannot
resume it. A new fresh observation initializes timing without movement, and
subsequent fresh updates resume the ramp. New primary IDs stop with TARGET_CHANGED
rather than inheriting old velocity or claiming personal identity continuity.

`check_timeout(now=...)` can stop while waiting for capture or before rendering;
it never integrates or refreshes observation time. It is called by the existing
event/capture-wait path, including headless worker waits. A native blocking call
cannot run Python timeout checks until it returns; meanwhile no virtual position
integration occurs. On return, the gap check stops without catching up. This is
not an independent real-device watchdog; future hardware requires its own local
timeout, arming and physical limit enforcement.

Statuses distinguish DISABLED, IDLE, MOVING, CENTERED, STOPPED, STALLED, FAULTED
and LIMIT_REACHED, with specific reasons. Stops clear pending demand, retain
historical source metadata explicitly as invalid commands, and require fresh
input. Driver faults stop the controller before propagating to existing fail-closed
application cleanup. Shutdown stops/disables simulation and releases its canvas.

## Real webcam mode versus synthetic closed-loop mode

**The real UGREEN webcam does not rotate in Phase 4.5.** The application uses
actual original-frame centering demand to update virtual angles. The simulated
orientation never alters webcam images, inference coordinates or tracking.
Persistent off-center demand can legitimately drive the virtual mechanism to
its limits. That is not proof of controller failure or real-world centering.
Even if a digital crop centers the face, the motor branch still uses the original
frame's centering result. The two outputs are independent.

`motor_control.closed_loop` is a separate offline harness. It uses a fixed world
target ray, virtual yaw/pitch and a pinhole projection, with **explicit required
horizontal and vertical FOV assumptions**. World +X is right, +Y forward, +Z up;
inverse `R_x(+tilt) R_z(+pan)` maps the world ray into camera coordinates. Image X
uses right/forward and image Y uses -up/forward, scaled by each FOV half-angle
tangent. Invisible/behind-camera targets yield loss, not fabricated observations.
The synthetic target has a known symbolic track ID; the harness does not test
face detection or association accuracy.

The recorded example assumes HFOV 60°, VFOV 40°, target pan +18°, tilt -8°,
60 FPS for eight seconds. Error changed from approximately
`(+0.5628,-0.4060)` to `(+0.0702,-0.0701)` normalized half-frame units, with
virtual angles about `(+15.6567,-6.5457)` degrees. This lies within the activation
band after hysteresis; exact zero is not the centering goal. Tests compare 30/60
FPS, loss/recovery and insufficient angle envelopes. Assumptions include rigid,
noise-free geometry with no actuator delay, backlash, load or calibration error.
No FOV is derived from the advertised uncalibrated 75° specification.

## Visual simulator and window lifecycle

The separate owned `VisionControl - Motor Simulation (No Hardware)` window shows
a fixed base, rotating pan platform/top view and a tilted camera/side view. It
displays actual virtual angles, current/target velocities, direction, limits,
primary ID and status/reason. Hardware output disabled and the stationary-webcam
limitation remain visible. Debug mode adds requested velocity and source time.
The [generated example](motor_control/examples/virtual_state.png) uses synthetic
controller state (pan +19.2°, tilt -6.4°); it is not a camera capture or CAD render.

All windows share the existing HighGUI event pump and PID/title/class ownership
checks. Minimize skips motor rendering while calculations continue; restoring
does not integrate a delayed time backlog. Original preview, motor preview and
optional crop minimize independently. Headless/explicit calculations-only modes
do not construct a motor renderer. Disabled simulation is not imported at all.

Closing the **motor window stops and disables simulation until restart**, while
camera, hand processing and any crop continue. Closing the crop disables only
that crop preview, as before. Original-window X or Q from any owned preview quits
the session with existing cleanup. A/D remain desktop-control keys; they are not
motor or hardware arming keys. No new keyboard hook/event loop is introduced.

## Conceptual 3D mount

[hardware/concepts/pan_tilt_concept.scad](hardware/concepts/pan_tilt_concept.scad)
is editable parameterized OpenSCAD source. Its [README](hardware/concepts/README.md)
explains layout, units, directions and unverified assumptions. It contains a
stationary base, vertical pan axis, rotating platform, two tilt brackets,
horizontal pivot, cradle/plate, approximate webcam body/lens, two approximate
motor enclosures, range indicators and optional cable-clearance marker.

Parameters include base/camera dimensions, bracket spacing, motor envelopes,
mounting offset, pan/tilt angles and illustrative ranges. Dimensions are invented
for concept visualization in millimetres, **not manufacturer dimensions**. Logical
pan-right/tilt-down conventions match the runtime; motor polarity remains unknown.
Transparent axes/ranges indicate motion, not fabricated structural shafts.

OpenSCAD was not found on PATH or in standard installation locations. Source
structure/parameter/delimiter tests pass, but **no OpenSCAD compilation, mesh or
CAD render was generated**. Open the source in OpenSCAD and Preview (F5). Inspect
neutral 0/0, pan -30/+30 with tilt zero, and tilt -15/+15 with pan zero. The runtime
example PNG is a different deliverable. OpenSCAD is never a Python dependency.

Moving clearances, pivot/bearing details, mounting compatibility, torque, load,
cable bends, screws and printable wall thickness remain unverified. Basic source
assertions do not establish mechanical feasibility. No fabrication file, final
bill of materials or purchasing recommendation is supplied.

## CLI

| Option | Default / behavior |
|---|---|
| `--motor-simulate` | Off; virtual controller on, implies face centering/tracking/detection |
| `--motor-sim-preview` / `--no-motor-sim-preview` | Visual window when enabled; disable for calculations only |
| `--motor-sim-debug` | Off; requires simulation; extra command diagnostics |
| `--motor-pan-limit` | 45°, symmetric virtual pan envelope; (0,180] |
| `--motor-tilt-limit` | 25°, symmetric virtual tilt envelope; (0,180] |
| `--motor-max-pan-speed` | 30°/s; (0,360] |
| `--motor-max-tilt-speed` | 20°/s; (0,360] |

Acceleration, asymmetric limits, home and shorter timing limits are typed API
settings rather than more CLI flags. Existing hand-only, face detection/tracking,
centering and digital reframing interfaces are preserved. Face-only rejects hand
controls; combined mode shares one frame. Digital reframing can coexist without
feedback between outputs. Headless runs use the existing timed benchmark convention.
Capture remains MSMF/sync, timer policy system by default; latest-thread and
`--windows-timer-policy honor-requests` remain explicit options.

## Benchmarks, counters and memory

Existing opt-in reports expose `motor_total` (adapter + controller),
`motor_control_update`, `motor_planning`, `motor_simulated_step`,
`motor_observation_age`, `motor_visualization`, `motor_imshow` and
`motor_preview_total`. Input/update and step sample counts differ during unsafe
states. Existing face-age, inference, frame-pacing P95/P99, camera delivery,
CPU/memory and preview-state metrics remain available. Motor metadata records
bounded reasons, input/invalid updates, stop transitions, per-axis limit entries,
nonzero requested/accepted update-interval seconds and final virtual angles.
These interval totals are not exact physical movement durations. Counters include
warmup; timing summaries exclude it. After session cleanup `simulation_enabled`
is false; `enabled_at_start` records the original explicit opt-in.

No per-frame application disk logging or image/face-coordinate recording is added.
The offline synthetic scene saves at most 256 decimated generated samples and
has no private webcam content. Core calculation timers are absent with profiling
disabled. No priority, timer-default, OpenCV-thread or inference-setting change
was made.

Evidence artifacts:

- `phase4_5_baseline.json`: unchanged Phase 4.4 benchmark before integration.
- `phase4_5_closed_loop_initial.json`: initial synthetic scene result.
- `phase4_5_synthetic.json`: initial motor/panel measurement, preserved.
- `phase4_5_synthetic_final.json`: intermediate report after panel optimization.
- [phase4_5_synthetic_validated.json](performance_reports/phase4_5_synthetic_validated.json):
  final code hashes, paired cases, independent controller, allocation/render
  probes and synthetic closed-loop evidence.

All are under `performance_reports/`. **These are synthetic host costs, not real
webcam FPS, sensor latency, physical motor or mechanical measurements.** Paired
cases use one generated face, optional existing two-hand EMA/static recognition,
optional reframing, 500 measured + 100 warmup iterations and three repetitions
with alternating baseline/motor order. Capture, inference, HighGUI and input are
excluded; synthetic face age is zero. Compare within pairs, not historical runs.

| Hand host | Reframing | Baseline mean ms | + Motors mean ms | Added ms | Change |
|---|---|---:|---:|---:|---:|
| None | Off | 0.1233 | 0.1824 | 0.0591 | +47.9% |
| None | On | 0.1761 | 0.2221 | 0.0460 | +26.1% |
| Two hands | Off | 0.7266 | 0.8059 | 0.0792 | +10.9% |
| Two hands | On | 0.7976 | 0.8488 | 0.0512 | +6.4% |

These are medians of repeat means. Percentages describe small host-only workloads,
not full application FPS. Combined motor adapter/controller stage means were
0.0472–0.0528 ms, median-run P95 0.0536–0.0687 ms and P99 0.0681–0.0818 ms.
The independent 2,000-update controller probe measured mean **0.0253 ms**, P95
**0.0296 ms**, P99 **0.0436 ms**, worst 0.1086 ms. Planning averaged 0.0049 ms;
the simulated step averaged 0.0111 ms. The sub-0.5-ms calculation target is met
for these inputs, not guaranteed for every host/scheduling condition.

The independent sequence includes scripted loss, stale input and stalls: two
limit entries, 27 stop transitions and nine STALLED results across its whole
2,200-update session including warmup. Observation-age tails of 300 ms are
deliberately injected unsafe samples, not measured camera latency. Constant
off-center demand reaches virtual (+45,-25) limits without physical feedback.

Paired process CPU ms/update before → after were 0.1250 → 0.1875 and
0.1875 → 0.2188 without hands (reframing off/on), and 0.7188 → 0.8125 and
0.7813 → 0.8438 with two-hand host work. Short samples have coarse CPU-clock
quantization. A 10,000-update pure controller allocation probe retained **710
Python bytes**, with **115,902 peak traced bytes** including immutable input/state
assembly; it excludes native model/image memory.

The first panel rendered at 0.9530 ms mean. Replacing a NumPy per-pixel color
broadcast with a grayscale byte fill reduced final panel preparation to **0.2182
ms** (P95 0.2450, P99 0.3558), about 77% lower in these probes. Original-preview
preparation averaged 0.6175 ms versus 0.8325 ms with the motor panel, about **0.2149
ms added**; P95/P99 changed from 0.7257/0.7841 to 0.9656/1.0160 ms. These separate
500-sample display probes exclude HighGUI and hand drawing, so are not preview FPS.

The standard motor canvas is **534,600 bytes** (debug: 631,800), reused and freed
on close/shutdown. Sample working sets were 73,625,600 and 74,244,096 bytes in a
shared process/allocator; those are not isolated memory deltas. Render process
CPU was 3.5938 → 3.5000 ms/iteration, including existing native OpenCV workers.
Those short, quantized samples do not establish CPU savings; wall time increased.
CPU percent of one core is not a machine-wide percentage. Actual camera FPS,
delivery, inference/face age, focus/minimize pacing, power and full application
memory remain pending matched owner measurements. No real camera run was made
for Phase 4.5.

## Automated validation and desktop safety

Final tests: camera **75**, gestures **165**, hand tracking **259**, desktop
controls **267**, face tracking **256**, motor simulation **77** — **1,099 passing
tests**. The 77 additions cover mapping/signs/diagonal normalization, exact
30/60-FPS integration, variable dt, acceleration/speed envelopes, all angle bounds,
reversal peaks, first-contact target cancellation, return from limits, zero-demand
no-coasting, invalid clocks/data,
replay, stalls, timeout checks, target changes, loss/recovery, disabled startup,
shutdown, immutable hardware-off states, bounded telemetry, adapter validation,
synthetic pinhole feedback/FOV/loss, visual buffers and concept-source structure.

Integration tests cover disabled imports, face-only/combined, independent digital
reframing, headless/calculations-only, minimized/restored motor and original
windows, motor-X disable, original-X cleanup, one event pump/camera/model chain,
latest-thread shutdown, capture faults, controller/render faults and simulated
held-button release. No real Windows input, motor hardware or webcam is required
or used by tests. CAD tests do not substitute for OpenSCAD compilation.

Existing desktop-control safety implementations were not changed: disarmed
startup, explicit live opt-in, A/D, Ctrl+Shift+F10 support, freshness, tracking-gap
cancellation, watchdog, capture-health fence, mouse release, stale-frame rejection,
rearming and cleanup retain regression coverage. Simulation has no desktop-input
API and cannot arm or authorize gestures. Failures stop/disarm via existing
cleanup. Desktop emergency keys remain desktop safeguards; they are not a new
physical motor arming/stop interface. Future real drivers need independent safety.

## Exact owner-run PowerShell acceptance

Use fresh report timestamps per repeat and run camera consumers sequentially.
The application refuses existing report paths. Keep equivalent face/hand counts,
lighting, pose, capture/inference settings and resource load across comparisons.
No command below enables real motor output or live desktop input.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase45Tag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'

# A-G: real webcam COMMAND simulation, with debug values and hardware OFF.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --motor-simulate --motor-sim-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_5_visual_${phase45Tag}.json"

# Optional independent digital crop + virtual motor views, same original analysis.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --motor-simulate --digital-reframe --motor-sim-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_5_dual_outputs_${phase45Tag}.json"

# Explicitly smaller virtual limits/speeds for a comparison, not hardware settings.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --motor-simulate --motor-pan-limit 30 --motor-tilt-limit 15 --motor-max-pan-speed 20 --motor-max-tilt-speed 12 --motor-sim-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_5_limits_${phase45Tag}.json"

# Paired headless host calculation comparison.
foreach ($phase45Mode in 'faces_baseline','faces_motor','combined_baseline','combined_motor') {
  $phase45Flags = @('--face-centering')
  if ($phase45Mode.StartsWith('faces')) { $phase45Flags += '--face-only' }
  if ($phase45Mode.EndsWith('motor')) { $phase45Flags += '--motor-simulate' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase45Flags --headless --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --report "hand_tracking/benchmarks/owner_4_5_${phase45Mode}_${phase45Tag}.json"
}

# Compare baseline, motor calculations only, and motor visualization.
foreach ($phase45Group in 'faces','combined') {
  foreach ($phase45Mode in 'baseline','calculations','visual') {
    $phase45Flags = @('--face-centering')
    if ($phase45Group -eq 'faces') { $phase45Flags += '--face-only' }
    if ($phase45Mode -ne 'baseline') { $phase45Flags += '--motor-simulate' }
    if ($phase45Mode -eq 'calculations') { $phase45Flags += '--no-motor-sim-preview' }
    .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase45Flags --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_5_preview_${phase45Group}_${phase45Mode}_${phase45Tag}.json"
  }
}

# H: combined gestures/desktop compatibility, SIMULATION; manually A/D.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --motor-simulate --digital-reframe --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --windows-timer-policy honor-requests --performance-profile --report "hand_tracking/benchmarks/owner_4_5_combined_sim_${phase45Tag}.json"

# I: after 5s warmup: 0-30 original focused; 30-60 unfocused/visible;
# 60-90 original minimized, motor visible; 90-120 both minimized;
# 120-150 original restored/motor minimized; 150-180 both restored.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --motor-simulate --benchmark --warmup 5 --duration 180 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_5_windows_${phase45Tag}.json"

# Offline synthetic CLOSED LOOP: explicit assumptions, not UGREEN calibration.
.\.venv\Scripts\python.exe -m motor_control.closed_loop --horizontal-fov 60 --vertical-fov 40 --duration 8 --fps 60 --report "hand_tracking/benchmarks/owner_4_5_scene_${phase45Tag}.json"
.\.venv\Scripts\python.exe -m motor_control.benchmark --frames 500 --warmup 100 --repeats 3 --render-frames 500 --report "hand_tracking/benchmarks/owner_4_5_synthetic_${phase45Tag}.json"

.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s face_tracking/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s motor_control/tests -t . -q
```

A: verify virtual home 0/0, hardware OFF and current face lock. B/C: move left/right
and up/down, checking requested signs, bounded actual speed/angles and limit status.
Remember the real camera does not move; sustained off-center demand reaching a
virtual limit is expected. D: sit centered, confirm zero demand and no coasting.
E: cover/leave, verify an immediate stop after detection loss, then plausible
recovery and gradual ramp with fresh timestamps. Stalls should report STALLED,
not move through missed time. F: introduce a second person after the first lock;
verify no takeover and uncertain crossings stop. If unavailable, mark multi-face
acceptance as synthetic-only. G: compare numeric angles/speeds to both visual
axes and configured limits. No graphic is a measured hardware pose.

H: keep two hands/one face visible; manually arm simulation and test existing
palm/pointing/pinch/drag/swipes/rearm/resume. Original coordinates must remain
correct as the crop and virtual motors act independently. D/Q/original X must
release virtual drag. Motor X disables only simulation; crop X disables only
its preview. Face/motor activity must not create desktop actions. Simulation does
not register the live emergency hotkey and is not physical hotkey acceptance.

I: inspect actual original/motor preview residency, not just intended schedule.
Check continuation while minimized, fresh updates on restore, no delayed jump,
motor-X disable, original-X cleanup and restart. Repeat matched pairs in reverse
order. For experimental worker comparisons, use fresh names and replace sync
with latest-thread in each corresponding command. Do not open multiple webcam
consumers at once. J: open the `.scad` in OpenSCAD, edit pan/tilt parameters for
the five views listed above, inspect axes/plate/camera and record intersections
or clearance issues for later design. This is concept review, not fabrication
or mechanical load validation.

Inspect application FPS; `capture_pipeline.capture_worker_delivery_fps` only
for latest-thread (sync is consumer/read throughput, not independent sensor FPS);
frame completion P95/P99; face ages; motor stages; `motor_simulation.counters`
and reasons; final virtual angles; CPU/memory and per-window state populations.
Original preview may be unfocused while the motor window is focused. Motor
nonzero interval totals/limit hits/stops must be interpreted with pose and scene
history, not as automatic tracking failures.

## Remaining limits and Phase 4.6 requirements

Owner application/visual/CAD acceptance is pending. No real motor performance,
closed-loop UGREEN centering, optical/mechanical calibration, load capacity,
rendered CAD collision check or fabrication feasibility is established. The
100 ms virtual timeout may pause motion on low-rate/contended streams; it is
deliberately conservative. Native stalls can leave old display pixels visible
until the main thread returns; no virtual integration or hardware actuation
continues in the background. Real hardware would need an independent local
watchdog and stop mechanism, not this application's event loop.

For Phase 4.6, first measure webcam dimensions/mass/center of gravity and actual
mounting interface; define required motion envelope, speed/duty and cable sweep;
then verify pivot/bearing/stiffness, base stability, load/torque margins, motor
envelopes, electrical/power/communication requirements and safe hard/soft stops.
Revise the CAD with actual parts and collision/load checks. Specify independent
arming, command timeout/watchdog, calibrated polarity/limits and fault recovery
before any physical output. No purchasing decision, finalized BOM, GPIO/network
driver, physical calibration, face-to-hand ownership, voice or later-phase
integration was implemented. Suggested eventual commit:
`feat(visioncontrol): add simulated pan-tilt controller and mount concept`.
