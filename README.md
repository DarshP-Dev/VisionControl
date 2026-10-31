# VisionControl
AI-powered computer vision system for gesture recognition, face tracking, and voice control

Current implementation: [camera diagnostics](camera/README.md),
[two-hand tracking and recognition](hand_tracking/README.md), and opt-in
[Phase 3.6 Windows controls](controls/README.md). Desktop controls default to
simulation and DISARMED; live input requires explicit arming. Optional
[face detection and temporal tracking](face_tracking/README.md) share the same
camera frames. `--face-tracking` adds temporary IDs, primary locking and smoothing;
combine with `--face-only` to skip the hand model. Detection alone remains available.
`--face-centering` adds read-only pan/tilt recommendations with dead-zone hysteresis;
it enables face tracking automatically. `--digital-reframe` adds smooth digital
following in a separate crop preview while tracking still uses the original image.
`--motor-simulate` adds a [virtual pan/tilt controller and visualizer](motor_control/README.md)
with hardware output always disabled. An [editable mount concept](hardware/concepts/README.md)
is also available. See [Phase 4.5 validation and acceptance](PHASE_4_5.md).
Voice and physical motor control remain future work. Follow staged controls validation
before live use.

[Phase 3.7 reliability report and final acceptance plan](PHASE_3_7.md) documents
the audit, measured CPU changes, safety hardening, regression tests and exact
PowerShell commands. Real webcam/desktop acceptance remains pending owner testing.
