# VisionControl
AI-powered computer vision system for gesture recognition, face tracking, and voice control

Current implementation: [camera diagnostics](camera/README.md),
[two-hand tracking and recognition](hand_tracking/README.md), and opt-in
[Phase 3.6 Windows controls](controls/README.md). Desktop controls default to
simulation and DISARMED; live input requires explicit arming. Face/voice/motor
features remain future work. Follow the staged controls validation before live use.

[Phase 3.7 reliability report and final acceptance plan](PHASE_3_7.md) documents
the audit, measured CPU changes, safety hardening, regression tests and exact
PowerShell commands. Real webcam/desktop acceptance remains pending owner testing.
