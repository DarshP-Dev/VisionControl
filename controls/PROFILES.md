# Phase 3.7: palm cursor and selectable cursor resume

This opt-in interaction enhancement leaves static recognition, pinch thresholds,
swipe motion thresholds and the legacy control profile unchanged. Hardware
acceptance is pending. No real Windows input or webcam session was run for this
implementation; automated tests use synthetic landmarks and virtual/fake backends.

## Profiles and anchor

`--control-gesture-profile legacy|palm-cursor` defaults to `legacy`.

| Profile | Cursor activation | Cursor anchor | Swipe eligibility |
| --- | --- | --- | --- |
| `legacy` | Stable POINTING | Index fingertip 8 | OPEN_PALM (existing explicit open-palm-or-fist option remains supported) |
| `palm-cursor` | Stable right OPEN_PALM | Mean of wrist 0 and MCPs 5, 9, 13, 17 | POINTING |

Assignments live in `controls/profiles.py`. Raw classifications are unchanged;
the existing event manager still handles confirmation, PINCH precedence, swipes
and cancellations. The new profile requires the Right control hand. The Left
hand is reserved for optional rearm/resume commands, never desktop clicks.

The palm anchor reuses `gestures.motion.palm_sample`, the same calculation used
for swipe trajectories. It consumes the existing smoothed observation and cached
palm scale. Each source x/y must be finite and within the frame. The common-axis
swipe y is converted back to normalized image y before passing to the existing
cursor mapper. Fingertips are not averaged. Invalid source geometry stops input.
No additional inference, feature extraction, model, thread or dependency is added.

The new anchor feeds the existing absolute/relative strategies. The centered
80% width/height region, clamping, inversion, DPI/display conventions, gain and
cursor EMA remain unchanged. Absolute X inversion is still on by default;
relative inversion is still off. Region dimensions remain configurable.
Synthetic palm-anchor tests reach all four mathematical region corners, but
comfortable physical reachability with a palm center still needs webcam testing.

## Cursor activity, pinch and swipe priority

System ARMED/DISARMED and cursor activity are separate. Startup still requires A.
OPEN_PALM activates movement only after the existing manager confirms it, while
controls are armed and no pending static replacement or swipe candidate blocks
movement. The default manager activation is 100 ms; this profile adds no second
debounce interval. Existing `--gesture-activation-ms` can increase stabilization
if physical testing warrants it.

A pending POINTING replacement stops cursor movement on its first observation.
A confirmed POINTING intent or actual swipe candidate latches the interaction
pause. A one-frame POINTING flicker stops that frame's movement but does not
commit a manual-resume mode switch. UNKNOWN/FIST stop movement; neither remains
an actionable cursor pose. Actual controlling-hand loss/ambiguity still disarms.

An OPEN_PALM-acquired interaction can continue through an admitted right PINCH
STARTED/HELD, even though the static index posture is no longer OPEN_PALM. A
gradual pinch can briefly pass through UNKNOWN before STARTED: a **250 ms
admission window** from the last active OPEN_PALM permits that fresh manager-
admitted pinch. It sends **no movement on UNKNOWN frames**, expires without a
pinch, and is revoked immediately by FIST, pending POINTING, pause or disarming.
Every observation still passes the original association, continuity, timing and
pinch checks. This window never bridges actual tracking loss or identity ambiguity.

With `--control-mouse`, the right pinch sends one DOWN, tracks the palm while
HELD and sends one UP on a valid release. The existing absolute drag-offset
compensation is retained: query the current cursor and prepare its offset before
DOWN, emit no movement on the activation frame, then move on HELD. A stable palm
usually needs little compensation, but keeping it also protects a pinch started
during cursor resumption. Relative drag keeps its existing fresh acquisition.
Cursor-only mode can track an admitted pinch without sending button events.
Pinch cannot initially acquire a palm interaction or activate one while paused.

An active drag keeps PINCH precedence; it cannot become a swipe. Loss, ambiguity,
disarm, emergency or backend failure still forces owned mouse UP and cleanup.
Release resets the drag offset; stable OPEN_PALM reacquires movement safely.

With explicit `--swipes`, POINTING enters the existing palm-trajectory recognizer.
Distance 1.5 palms, velocity 3 palms/s, dominance 3, consistency 0.85, timing
120–600 ms, cooldown 800 ms, stationary reset 250 ms and the configured scale
limit retain their defaults. No swipe threshold is loosened. UNKNOWN is ineligible.
The existing neutral-pose/reset latch and opposing-two-hand suppression remain.
OPEN_PALM return movement is ineligible for a POINTING swipe, preventing a return
path from becoming an unintended reverse swipe. A new POINTING swipe still needs
the original cooldown and stationary rearm.

Swipe direction remains image x in the unmirrored preview: decreasing x is
SWIPE_LEFT/previous tab (Ctrl+Shift+Tab), increasing x is SWIPE_RIGHT/next tab
(Ctrl+Tab). Cursor inversion does not invert swipe direction. Tabs require both
`--swipes` and `--control-tabs`, with the existing foreground/key safety checks.

## Resume modes

`--control-cursor-resume automatic|left-pinch` defaults to `automatic`.
Legacy accepts the default automatic setting; left-pinch is rejected for legacy.
The profile does not implicitly enable swipes, clicking, tabs or gesture rearming.
An explicitly incompatible `--swipe-pose` is rejected rather than silently ignored.

**Automatic:** Return to a confirmed OPEN_PALM with no pending replacement or
active swipe candidate. Cursor movement can resume without waiting through the
unrelated remaining swipe cooldown: OPEN_PALM is already ineligible for swipes.
Static confirmation/cooldowns still run normally. There is no new recognition
tolerance or label hold. FIST/UNKNOWN do not move the cursor while waiting.

**Left-pinch:** Requires `--control-gesture-rearm`. After a deliberate POINTING/
swipe pause, returning OPEN_PALM alone does not resume. Use the existing
`LeftPinchRearm` validator: two distinct confident hands, 300 ms stable association,
fresh Left OPEN, Left STARTED, HELD for at least 800 ms, then RELEASED with the
existing event lifecycle. Neither default is relaxed. Existing rearm timing flags
apply to this same sequence. Right OPEN_PALM must be stable on confirmation;
otherwise the request is consumed without resuming and a new sequence is needed.

Left loss, low confidence, overlap, hand discontinuity or stale/canceled events
cancel the attempt. A Right pinch cannot resume or click while paused. A Left
pinch while the cursor is active does not reset cursor positioning. The physical
gesture is a deliberate command, **not authentication** or proof of identity.

A successful resume leaves system ARMED unchanged and sends no mouse, movement
or keyboard action on the confirmation frame. The next valid sample acquires a
fresh anchor without movement; later samples move. No completed request is held
for later replay. While armed and paused, **A** is an explicit keyboard fallback
only when Right OPEN_PALM is currently stable, associated and fresh. A while
disarmed keeps its original manual system-arm/recovery meaning; D/emergency
recovery is not redefined.

**Absolute reacquisition:** The first fresh sample anchors to the frozen OS/virtual
cursor. Subsequent mapped/EMA targets are approached with a palm-profile-only
speed bound of one monitor diagonal per 600 ms, with each time step capped at
50 ms. At normal <=50 ms cadence a stationary full-screen mismatch is reconciled
in at most 600 ms of delivered sample time, plus existing EMA settling. Sparse
frames take longer rather than causing a large single-frame jump. Once caught
up, ordinary absolute mapping continues without a lasting offset. This applies
to initial palm acquisition and reacquisition, including after pinch release.
Relative mapping keeps its existing displacement anchoring. Legacy mapping has
no new resumption bound. Very fast hand movement may prolong the catch-up phase;
the displayed RESUMING status makes it visible.

## System safety and status

| System state | Meaning of a complete Left command |
| --- | --- |
| DISARMED after eligible routine loss | Request system rearm using existing policy |
| ARMED, palm cursor paused, left-pinch mode | Request cursor resume only |
| ARMED, cursor active | No cursor reset and no desktop click |
| Startup, D, emergency, watchdog, critical fault or unsafe backend | Gesture recovery blocked; existing manual/restart policy applies |

Only one branch consumes a command per frame. The controller remains the final
authority: stop-generation checks prevent a completed resume from overriding a
newer pending stop. Input guards remain checked before and after backend preflight;
owned UP/cleanup is permitted while disarmed. The configured global emergency
shortcut and existing retry/latching behavior are unchanged. See
[REARMING.md](REARMING.md) for the full system-rearm policy.

The preview uses the existing status renderer: profile and cursor state get a
separate row in palm mode, while ARMED/DISARMED, controlling hand, button state,
A/D, action/reason, STOP shortcut and existing gesture overlays remain. Cursor
states include ACTIVE, PAUSED - SWIPE MODE, WAITING FOR OPEN PALM, WAITING FOR LEFT
PINCH, RESUMING and STOPPED - SYSTEM DISARMED. Manual sequence feedback uses the
same validator with RESUME wording. Legacy retains its existing row count and
shows PROFILE: LEGACY. A synthetic two-hand preview was rendered and inspected.

## Exact PowerShell commands

First define the shared explicit settings; then run one command at a time.
Begin with simulation before any live test. All launches start disarmed.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$visionArgs = @('--gestures', '--pinch', '--gesture-states', '--controls',
    '--control-mapping', 'absolute', '--control-region-width', '0.80',
    '--control-region-height', '0.80', '--control-hand', 'right',
    '--control-emergency-hotkey', 'ctrl+shift+f10')

# 1. Legacy simulation: existing pointing cursor, open-palm swipes.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode simulate --control-gesture-profile legacy --control-mouse --swipes --control-tabs --control-gesture-rearm

# 2. Palm cursor, automatic resume, simulation.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode simulate --control-gesture-profile palm-cursor --control-cursor-resume automatic --control-mouse --swipes --control-tabs --control-gesture-rearm

# 3. Palm cursor, deliberate Left pinch resume, simulation.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode simulate --control-gesture-profile palm-cursor --control-cursor-resume left-pinch --control-gesture-rearm --control-mouse --swipes --control-tabs

# 4. Live palm cursor only: no mouse button or tab actions.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode live --control-gesture-profile palm-cursor --control-cursor-resume automatic --control-gesture-rearm

# 5. Live palm cursor with click/drag; tabs remain disabled.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode live --control-gesture-profile palm-cursor --control-cursor-resume automatic --control-gesture-rearm --control-mouse

# 6. Live POINTING browser-tab swipes, with Left pinch cursor resume.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @visionArgs --control-mode live --control-gesture-profile palm-cursor --control-cursor-resume left-pinch --control-gesture-rearm --control-mouse --swipes --control-tabs

# 7. Full automated suites and optional controller-only synthetic benchmark.
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m controls.tests.benchmark_profiles
```

Use `--control-mapping relative` to compare relative mapping, or adjust the two
region dimensions. The inversion flags retain their existing meanings. Add
`--gesture-debug`, `--swipe-debug`, `--gesture-event-debug`, `--control-debug` or
`--control-rearm-debug` only for the corresponding diagnostic channel. Profile
and resume configuration are recorded in the existing JSON controls settings.
The existing `gesture_rearm` timing includes the shared validator when used for
manual cursor resume; `controller_processing` includes total profile work.

For matched hardware comparisons use the existing visible benchmark options
`--benchmark --warmup 3 --duration 30 --report <new-json-path>` on the chosen
simulation command, diagnostics off, with the same gestures and arming sequence.
Repeat and reverse profile order. Do not use headless controls or interpret
disarmed timings as the cost of armed movement. No physical benchmark was run.

## Automated evidence and remaining validation

Initial working tree was clean on `main`, revision `138925f`. The measured
baseline was **531 tests** (515 root-discovered + 16 camera), rather than the
reported 530. All previous tests remain intact.

Final suites: **590 passing tests**: 16 camera, 154 gestures, 170 hand tracking,
250 controls. The 59 added regressions cover palm geometry, invalid sources,
mapping corners/inversion, unchanged legacy defaults, cursor/drag transitions,
pinch approach expiration, both POINTING swipe directions, return/cooldown/reset,
conflict suppression, automatic stability, manual sequence refusal/consumption,
real EMA/event integration, CLI/report/preview behavior and safety-stop races.
Live-policy tests use virtual/fake backends, never real SendInput.

The reproducible isolated benchmark warms up 200 frames and measures 2,000 per
variant, alternating order. Inputs/features are cached; camera, inference,
extraction, smoothing and GUI are excluded. Recorded host results in ms/frame:

| Controller workload | Mean | p95 |
| --- | ---: | ---: |
| Legacy | 0.0310 | 0.0454 |
| Palm automatic | 0.0470 | 0.0696 |
| Palm manual, active | 0.0478 | 0.0715 |
| Palm manual, paused validator | 0.0703 | 0.1068 |

The active palm overhead in this run was about 0.016 ms/frame relative to legacy;
shared manual validation added about 0.039 ms while paused. These measurements
do not establish hardware FPS or end-to-end latency.

Manual acceptance, simulation first:

1. Compare legacy behavior and both palm resume modes. A arms; OPEN_PALM should
   acquire without a jump and move using the palm, not fingertip motion.
2. Test all four screen corners and adjust the region if necessary. Check X
   inversion, vertical direction, clamping, selected monitor/DPI and relative mode.
3. Click and drag a disposable object. Check gradual pinch closure, one DOWN/UP,
   no activation jump, continuous HELD movement and safe release/reacquisition.
4. POINTING should freeze the cursor immediately, then allow deliberate left/right
   swipes after stationary rearm. Test incomplete swipes, return motion, repeated
   swipes, cooldown and two-hand opposing motions; each completion switches once.
5. Automatic mode should resume only on stable OPEN_PALM. Manual mode must wait
   for fresh Left OPEN, stable association, the full hold, and RELEASED. Test short,
   missing-release, wrong-hand and already-held sequences. Confirmation must not
   move/click/switch tabs. Test A fallback separately while armed and paused.
6. While paused, lose the Right hand; confirm system DISARMED, then test eligible
   Left system rearm as a separate operation. Test Left loss, overlap, duplicate
   labels, crossings and reacquisition with no stale resume.
7. Test D, the configured global emergency shortcut outside preview focus, and
   loss during drag. Verify UP/cleanup, no further input and required manual
   recovery. Verify the shortcut before proceeding to live click/drag or tabs.
8. Record profile, resume mode, region, monitor/DPI, misfires, FPS and responsiveness
   under matched conditions. Validate long sessions and remote-desktop behavior.

POINTING uncertainty can still cancel swipes; UNKNOWN is never promoted to make
them work. The existing conservative association can reject overlap or mislabeled
hands and cannot prove identity. Palm rotation, occlusion and landmark noise still
affect tracking. A slow pinch approach beyond the admission window must reacquire
OPEN_PALM; a moving absolute target can prolong RESUMING. Comfortable corner reach,
physical accuracy, emergency delivery and webcam performance remain owner tests.

Implementation files: `controls/{profiles,interaction,models,cli,controller}.py`,
`gestures/{arbitration,swipe}.py`, `hand_tracking/hand_tracker.py`; focused tests and
benchmark in `controls/tests/{profile_fixtures,test_profiles,benchmark_profiles}.py`
and `hand_tracking/test_control_profiles.py`. Existing cursor/region, rearm
validator, hotkey/safety/backend, static classifier and feature extraction files
are unchanged. Documentation links are updated in the relevant READMEs/SWIPES.

Stop after this enhancement. No Phase 3.8/4 work, staging, commit or push.
Suggested future commit after owner approval:
`feat(controls): add palm cursor profile and selectable resume modes`.
