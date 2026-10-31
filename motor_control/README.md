# Virtual motor controller — Phase 4.5

This package provides normalized-demand planning, a **simulated** pan/tilt driver,
stop/freshness checks and an optional OpenCV view. It has no GPIO, PWM, serial,
network, Raspberry Pi or actual motor implementation. Future drivers need
independent arming, watchdogs, calibrated limits and command timeout checks.
See [PHASE_4_5.md](../PHASE_4_5.md) for tests, measurements and owner acceptance.
Run the commands below from the repository root.

```powershell
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --motor-simulate --motor-sim-debug
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --motor-simulate
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --motor-simulate --digital-reframe
```

`--motor-simulate` explicitly enables virtual calculations and implies face
centering/tracking/detection. Default capture and timer policies stay sync/system.
`--no-motor-sim-preview` calculates without a motor window. `--motor-sim-debug`
adds requested velocity/source-time diagnostics. Headless benchmark mode skips
the visualizer. Existing controls remain separately opted-in and disarmed.

Defaults are illustrative, not motor specifications: pan +/-45°, tilt +/-25°,
max speeds 30/20 deg/s, accelerations 60/40 deg/s², home 0/0. Symmetric angle
limits and maximum speeds have CLI options `--motor-pan-limit`,
`--motor-tilt-limit`, `--motor-max-pan-speed`, `--motor-max-tilt-speed`.
Typed `MotorConfig` / `AxisConfig` expose acceleration, home and asymmetric limits.
Positive pan means scene-right; positive tilt means down. No hardware polarity
or optical calibration is assumed.

`centering_adapter.from_centering` bridges the existing immutable centering
snapshot into a normalized `MotorInput`. The core `MotorController` and
`SimulatedMotorDriver` do not import MediaPipe or face models. Velocity demand is
scaled to deg/s; diagonal demand is normalized in per-axis-speed space. Shared
analytic velocity ramps enforce acceleration bounds. Axis limits clamp, stop
outward motion, and allow a later inward request. Zero-demand axes stop without
coasting. Unsafe input stops both velocities immediately, bypassing normal ramps.

The maximum control interval is 100 ms and maximum actual observation age is
250 ms. Gaps, replay, invalid metadata or tracking loss stop and require fresh
observations; no missed-time movement is caught up. The first fresh update after
stop initializes timing without moving. New primary IDs stop rather than inherit
old velocity. `check_timeout(now=...)` can stop during capture waits, never move
or refresh freshness. `MotorController()` defaults disabled; the application
constructs it enabled only for the explicit simulation flag. Hardware output is
always false, including every immutable `MotorState`.

The motor window uses the existing HighGUI event pump and owned-window checks.
Minimize skips its rendering while calculations continue. Closing this window
**stops and disables simulation until restart**, while capture, gestures and any
digital crop continue. Original-window X or Q shuts down the whole session.
There are no new control keys; A/D remain desktop-control keys.

Real webcam mode has **no simulated physical feedback**: virtual orientation does
not move the real camera or alter its images. Constant off-center face demand
can drive the simulator to its limits. This is expected and does not establish
physical centering. The optional crop and virtual motor orientation are independent.

The separate offline scene harness supplies explicit synthetic feedback:

```powershell
.\.venv\Scripts\python.exe -m motor_control.closed_loop --horizontal-fov 60 --vertical-fov 40 --duration 8 --fps 60 --report "hand_tracking/benchmarks/synthetic_scene_$((Get-Date).ToString('yyyyMMdd_HHmmss_fff')).json"
.\.venv\Scripts\python.exe -m motor_control.benchmark --frames 500 --warmup 100 --repeats 3 --render-frames 500 --report "hand_tracking/benchmarks/motor_bench_$((Get-Date).ToString('yyyyMMdd_HHmmss_fff')).json"
.\.venv\Scripts\python.exe -m unittest discover -s motor_control/tests -t . -q
```

FOV parameters in this scene are **required assumptions**, not UGREEN calibration.
The rigid yaw/pitch pinhole scene is noise-free and omits actuator delay, backlash,
inertia and real load effects. It does not validate real motors.

The [example visualizer image](examples/virtual_state.png) was generated from
synthetic controller state (pan +19.2°, tilt -6.4°). It is not a CAD render or a
webcam/hardware result. The separate [editable mount concept](../hardware/concepts/README.md)
is optional `.scad` source, with unverified illustrative dimensions.
