# Phase 3.6: Windows desktop controls

Phase 3.7 latches pending cancellation before waiting on the frame lock, prepares
absolute drag before DOWN, retries failed owned-input cleanup at most three times
(100 ms spacing), and preserves relative subpixel targets. Existing mapping
defaults, pinch/swipe rules and manual arming remain. See the [Phase 3.7 audit,
limitations and staged acceptance plan](../PHASE_3_7.md); hardware acceptance is pending.
Normal input is guarded again after backend preflight; owned-input release remains
permitted while disarmed or canceled.

Controls are **off by default**. `--controls` defaults to **simulation**; both
simulation and live start **DISARMED**. Click/drag and tab shortcuts require
separate flags. Recognition flags alone never send desktop input. Webcam accuracy,
cursor feel, physical off-focus emergency shortcut delivery, monitor/DPI behavior
and live performance await local testing. Implementation/tests sent no real input.

## Architecture and dependencies

Camera → current EMA landmarks → shared cached features → existing recognition
and Phase 3.4/3.5 `StateFrame`/`GestureEvent` → `DesktopController` → `InputBackend`.
Recognition never imports controls; raw observations/events and thresholds are
unchanged. The mapper is not another gesture state machine.

- `models.py`: settings, physical screen bounds, backend protocol, status.
- `cursor.py`: independent relative/absolute index-tip mapping and screen-space EMA.
- `region.py`: validated centered camera region shared by absolute mapping/preview.
- `controller.py`: selected-hand event mapping, ownership and safety gates.
- `backends.py`: entirely virtual cursor/buttons/keys and foreground app.
- `windows.py`: lazy stdlib `ctypes` Win32 adapter, `SendInput`, DPI/monitors,
  foreground executable queries. Importing it sends no input.
- `safety.py`: one **live-only** global-hotkey and stall-watchdog thread.
- `cli.py`: explicit dependencies and scoped cleanup.

**No new dependencies.** Capture/inference/recognition/GUI remain synchronous.
One safety thread is necessary for off-focus emergency input and releasing a
button while the camera/model blocks. It does not process frames or ordinary
gesture actions. No extra inference, screen capture, frame dropping or frame-loop
filesystem writes. Tests use virtual/fake backends exclusively.

## Arming and emergency stop

Show the selected hand with thumb/index separated for pinch rearming. Keep the
real cursor on the selected monitor. Focus the preview: **A arms**, **D disarms**,
**Q exits**, **H toggles help**. Arming itself sends no input and requires a valid
hand seen within 250 ms. There is no automatic-arm option. White-on-black status
shows mode, arm state, selected hand, gesture, button, last action and safety reason.

**Live global emergency stop: Ctrl+Alt+Esc**, including when another app has focus.
It disarms and releases owned inputs. Explicit A in the preview is required to
rearm. Q/H/A/D need preview focus; the emergency shortcut does not.

The safety thread uses `RegisterHotKey` with `MOD_NOREPEAT` and drains its
`WM_HOTKEY` queue approximately every 10 ms. Registration failure (including a
shortcut already occupied) fails closed **before camera/model startup**. Runtime
monitor failure also disables arming. Mock Win32 tests cover registration,
dispatch, failures and cleanup; verify actual off-focus delivery in Stage B.
The monitor disarms after a **500 ms** controller heartbeat stall.

Received tracking gaps over **250 ms**, unavailable pinch data, lost/ambiguous
handedness, overlap/crossing, wrist discontinuity, changed capture geometry or
tracking cancellation disarm and reset pointer mapping. No auto switching to the
other hand, auto rearming or speculative identity matching. UNKNOWN/FIST stop
ordinary pointer movement. Backend errors latch controls unavailable until restart.

Owned input is released on cancellation, disarm, emergency, stall, normal exit,
window close, Ctrl+C and exceptions. A partial shortcut attempts UP for every
potentially pressed key, retaining failed ownership for cleanup retry. Releases
are best effort if Windows blocks input (e.g. UIPI); process termination/system
crashes cannot be recovered. Tracking-loss safety UP never fabricates a
recognizer PINCH RELEASED event. Concurrent physical mouse use should follow D;
an already physically held left button blocks a new gesture press.

## Relative cursor, monitor and DPI mapping

Use **EMA-smoothed index tip 8**, also during a valid held pinch. POINTING
activation anchors at the existing cursor/current tip and sends **no move**.
Subsequent hand displacement moves the pointer. Ending POINTING, loss and disarm
reset mapping; reacquisition anchors again. Pinch start reanchors to avoid a
finger-curl jump. Motion is allowed only for confirmed POINTING (no pending
replacement) or a valid active pinch with an owned left button.

Positions clamp to an active camera region (default **10%** margin per edge),
then use common image-width units `(x, y * height/width)`. One isotropic gain fits
that region within the selected screen and multiplies by sensitivity, default
**1.5**. Accumulated targets clamp to monitor edges without windup; screen-space
EMA current weight **0.6** reduces jitter. Higher alpha reduces lag. These are
initial interaction settings, not physically calibrated values. Controls reject
`--no-smoothing`. Distance from camera still affects relative sensitivity.

This default strategy is **relative hand-displacement mapping**. Win32 normalized
absolute packets only deliver the computed physical-pixel target without Windows
relative acceleration; they are not an absolute camera mapping. Right/down in
the unmirrored image moves right/down. No optical FOV/pointing-angle calibration.

### Horizontal cursor calibration

Some users prefer mirrored horizontal cursor motion: a left/right hand movement
can feel reversed with an unmirrored camera view. Add **`--control-invert-x`** to
reverse only the relative horizontal cursor delta in simulation or live mode.
In relative mode it defaults **off**, preserving existing commands. Vertical motion stays unchanged.
The sign changes after active-region/aspect correction, before target accumulation,
clamping and screen-space EMA; acquisition/reacquisition still anchors without a
jump. The same cursor mapping is used during an already valid drag, without
changing pinch/drag lifecycle rules. Preview, handedness, gesture coordinates,
static classification, swipe directions and tab actions are unaffected.

```powershell
# Simulation: horizontal inversion with pinch click/drag enabled
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode simulate --control-hand right --control-mouse --control-invert-x

# Live: same mapping, starts DISARMED; A arms, D disarms, Ctrl+Alt+Esc stops globally
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-hand right --control-mouse --control-invert-x
```

Omit `--control-mouse` for cursor-only testing. Remove `--control-invert-x` to
restore the original horizontal mapping. No vertical inversion option is added.

Live startup establishes per-monitor DPI awareness before OpenCV creates a window;
physical cursor/monitor coordinates receive no second scaling multiplier.
`--control-monitor 0` is primary; others sort by left/top desktop origin, including
negative origins. Movement stays on that one monitor. Place the cursor there
before arming, avoiding a cross-monitor activation jump. Restart after display,
desktop or DPI reconfiguration. Simulation never queries Windows and uses its
own virtual monitor (1920x1080 by default).

## Phase 3.6 enhancement: absolute cursor and active region

`--control-mapping relative|absolute` defaults to **relative**. Existing relative
gain, aspect correction, sensitivity, edge margin, anchoring and inversion are
unchanged. Select **absolute** to map the position of EMA-smoothed index tip 8 to
one selected display, rather than accumulate fingertip displacement. This is
**2D camera-coordinate mapping**, not a physical touchscreen, pointing-ray model,
or real-world finger-to-screen alignment.

### Region and coordinate calculations

`--control-region-width .80` and `--control-region-height .80` independently set
fractions of the actual camera **width and height**, each finite and in `(0, 1]`.
The region is centered. At 1920x1080 the defaults give **1536x864**, with **192 px
left/right** and **108 px top/bottom** margins. Other resolutions derive their
geometry from the actual capture dimensions. This is not an 80% image-area setting.

For normalized camera coordinates `(x, y)`, let `left=(1-width)/2` and
`top=(1-height)/2`. Compute `u=clamp((x-left)/width, 0, 1)` and
`v=clamp((y-top)/height, 0, 1)`. The physical screen target is
`(screen.left + u*(screen.width-1), screen.top + v*(screen.height-1))`.
Before inversion, corners map to corresponding screen corners and the center maps
to center. The absolute default mirrors X as described below. In-frame points
outside the region clamp to its nearest screen boundary. Invalid/non-finite or
out-of-frame tips are rejected rather than moved. Unlike relative common-axis
geometry, absolute mapping uses independent normalized X/Y axes; there is no
extra camera-aspect multiplier. Aspect-preserving inference downscaling does
not change these normalized positions.

Absolute mode now **inverts X by default**, using the existing `u` to `1-u`
mapping exactly once before screen smoothing. This compensates for the horizontal
direction observed during the UGREEN webcam test: physical finger-left increases
raw camera X, so the mirrored mapping moves the cursor left; finger-right moves
it right. Raw camera coordinates and physical hand direction are distinct.
Relative mode still defaults to **no inversion**, preserving its existing behavior.

Use `--control-invert-x` to explicitly enable inversion in either mode, or
`--control-no-invert-x` to explicitly disable it. These mutually exclusive flags
set a boolean; enabling inversion when it is already the default does not invert
twice. The resolved setting is shared by simulation and live, including dragging.
Neither mode inverts Y, flips the preview or changes recognition.
`--control-sensitivity` and `--control-margin` apply only to relative mode; use
region width/height to change absolute reach.

A thin yellow rectangle marks the active region in the preview. Status shows
RELATIVE or ABSOLUTE and the intended screen position in the last Move action,
including in simulation. The rectangle uses the same normalized pixel convention
as skeleton drawing, follows capture/preview aspect ratios, and is drawn only on
the existing preview buffer. Capture, inference image, autofocus, camera settings,
and full field of view remain unchanged; no crop or additional frame copy occurs.

### Smoothing, activation, pinch and safety

Both modes reuse current EMA landmarks and the existing `--control-alpha .6`
screen EMA. Higher alpha responds faster; lower alpha suppresses jitter but adds
lag. Targets clamp before EMA without accumulating displacement. Fractional EMA
state is retained until integer output. At alpha below 1, reaching an edge takes
several samples to settle; alpha 1 disables screen EMA, but CLI still requires
landmark smoothing. No new model, dependency or thread is introduced.

Controls remain opt-in and start DISARMED in simulation and live. **A** arms after
valid selected-hand association; arming sends no movement. The first actionable
POINTING sample anchors smoothing at the current cursor without moving. Subsequent
valid samples blend toward their absolute targets, including a stationary tip.
After reset, no old fingertip/EMA state is replayed. Selected-hand loss/ambiguity
still forces UP and disarms; hand reentry never switches control or rearms it.

At a fresh accepted PINCH STARTED, absolute mode captures a **constant screen
offset** from the newly closed fingertip's mapped position to the current cursor.
Mouse-down sends no cursor move. HELD samples use mapped positions plus that
offset and remain responsive even without POINTING classification. This prevents
finger closure from jerking the cursor or dragged object. The offset is not
integrated or repeatedly rebased. RELEASED sends one UP and clears the offset;
the next POINTING acquisition is move-free and the existing EMA blends back
toward ordinary absolute positioning. Reset, loss, disarm, emergency and shutdown
also clear drag state and preserve the existing forced-release behavior.

Primary display is the initial target (`--control-monitor 0`). The existing
backend establishes per-monitor DPI awareness and supplies physical-pixel bounds;
mapping adds the selected display origin and leaves Win32 virtual-desktop
normalization to that backend. No logical-pixel/DPI multiplier is added. Existing
explicit monitor selection, including negative origins, is covered by fake tests,
but physical multi-monitor/mixed-DPI setups require manual verification. Movement
stays on one selected display and does not span monitors. Keep the cursor on that
display before arming. **Restart after monitor, desktop or DPI reconfiguration.**

### Exact PowerShell commands

Run from `C:\Users\Darsh\VisionControl`. All examples start DISARMED. Simulation
never sends Windows mouse/keyboard input; `--control-mouse` simulates click/drag.
Tabs remain disabled unless explicitly enabled with the existing swipe flags.

```powershell
# A. Existing relative behavior; inversion remains off unless you add its flag.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode simulate --control-mapping relative --control-hand right --control-mouse

# B. Absolute simulation, 80% width/height, right hand, mouse simulation and diagnostics.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode simulate --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-mouse --control-debug

# C. Same mapping LIVE: focus preview, A to arm, D to disarm, Ctrl+Alt+Esc emergency stop.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-mapping absolute --control-region-width 0.80 --control-region-height 0.80 --control-hand right --control-mouse --control-debug

# D. Vertical calibration in simulation: less vertical hand travel, greater Y gain.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode simulate --control-mapping absolute --control-region-width 0.80 --control-region-height 0.70 --control-hand right --control-mouse --control-debug
```

Absolute examples already enable X inversion by default. Add `--control-no-invert-x`
to compare the old absolute horizontal direction, or `--control-invert-x` to
explicitly keep inversion enabled. Relative examples still default to no inversion.
Remove
`--control-debug` to disable optional sampled logs. Use Q to quit and H for help.
Do not start live until simulation is comfortable and the physical emergency
shortcut has been checked in a safe setting. Existing watchdog, hand-selection,
click/tab flags and release/error policies are preserved.

### Calibration and limitations

Start with `.80/.80`. If top/bottom are difficult to reach, try `.80/.70` before
changing smoothing. Try `.90/.80` for a wider usable region, or `1/1` for the full
frame. Smaller regions amplify camera jitter; these are initial settings, not
permanent calibration. Test corners, edges, center, quick movement and small
stationary fluctuations. Pinch grip changes during HELD still move the index tip;
the constant start offset does not compensate for every later change of grip.
That offset can also reduce reachable edges during a drag; release and repoint
to restore normal absolute reach. Release/repoint convergence depends on alpha.
Webcam accuracy, physical reach, DPI/display behavior and actual FPS require the
owner's UGREEN/laptop tests. No physical webcam or real input was used in automation.

This enhancement stops at Phase 3.6; no Phase 3.7 reliability redesign is included.

Enhancement validation: **388 tests passed** (16 camera, 124 hand tracking,
135 gestures, 113 controls), including 47 new tests. The original RelativeCursor
implementation and all existing test files were retained. No real webcam or
Windows input was used. The starting working tree was clean at `91a651d`;
hardware validation remains with the owner.

## Pinch, drag and tab actions

`--control-mouse` enables click/drag, **off by default**. After manual arming, an
OPEN/RELEASED measurement must precede a fresh, current selected-hand **PINCH
STARTED** event: send one left DOWN. HELD repeats no DOWN. Continue moving the
same index tip during confirmed valid PINCH even when static POINTING becomes
UNKNOWN. Intentional RELEASED plus the manager's PINCH ENDED sends one UP; a
short pinch is a normal click. Unrelated poses, stale/missing STARTED, pre-arm
HELD, non-controlling hands and reacquisition cannot fabricate a click.

`--control-tabs` independently enables shortcuts in either mode, **off by
default**, and requires `--swipes`. Only current selected-hand confirmed
GESTURE_STARTED is consumed, once; candidate/ENDED/cooldown/replayed frames do
nothing. Existing recognition cooldowns/stationary rearming are unchanged.

| Swipe (unmirrored image) | Shortcut |
| --- | --- |
| SWIPE_RIGHT (increasing x) | Ctrl+Tab |
| SWIPE_LEFT (decreasing x) | Ctrl+Shift+Tab |

Foreground executables must match the explicit allowlist, default `chrome.exe`,
`msedge.exe`, `firefox.exe`. Repeat `--control-browser NAME.exe` to **replace** the
defaults. Match case-insensitive basenames, never titles. Unknown/inaccessible
processes block. Live mode rechecks the foreground window just before delivery
and blocks if physical modifiers/Tab are held. Focus validation and SendInput
cannot be atomic; a last-instant focus change remains possible. The allowlist is
not executable authenticity/security proof. No app is launched/focused by controls.
Simulation uses a configurable virtual foreground name and preserves recognition
when unsupported targets block tab actions.

Priority: safety cancellation → held drag → pinch click → confirmed swipe →
POINTING. Pinch/drag blocks tabs, including the release frame. Existing arbitration
and the mapper suppress simultaneous opposite swipe intents. Static/raw labels
remain distinct from action status.

## Exact PowerShell commands

From `C:\Users\Darsh\VisionControl`; none automatically arms controls:

```powershell
# Existing tracking only
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker

# Recognition only; no desktop mapper
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes

# Stage A: simulation, all mappings. A arms, D disarms, Q quits.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-hand right --control-mouse --control-tabs --control-debug

# Simulate another screen and unsupported foreground
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mouse --control-tabs --control-sim-size 2560x1440 --control-sim-app notepad.exe

# Stage B: live cursor ONLY, starts disarmed. Global stop Ctrl+Alt+Esc.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-hand right

# Stage C: live cursor and click/drag; tabs still disabled
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode live --control-hand right --control-mouse

# Stage D: explicitly enable browser tabs, Chrome only
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mode live --control-hand right --control-mouse --control-tabs --control-browser chrome.exe

# Optional tuning, simulation first
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-hand left --control-alpha 0.75 --control-sensitivity 1.2 --control-margin 0.1

# All hardware-independent tests
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m compileall -q camera hand_tracking gestures controls

# Comparable preview benchmarks: same scene, lighting, hand count and motions
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --benchmark --warmup 3 --duration 30 --report hand_tracking/benchmarks/phase36_recognition.json
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --swipes --controls --control-mouse --control-tabs --benchmark --warmup 3 --duration 30 --report hand_tracking/benchmarks/phase36_simulation.json
```

Press A after a valid hand appears in the simulated benchmark and exercise the
same gestures throughout measurement. Choose fresh JSON filenames; existing
reports are protected. `controller_processing` reports mean/p50/p95/p99/max,
overall and by hand count, and is nested inside processing/end-to-end. Controls
settings and final status are recorded; no images, full executable paths or
per-frame action log. Disarmed benchmarks do not measure armed action costs.
`--control-debug` samples logs at most once every 2 seconds. Controls require a
visible preview, rejecting headless runs so safety and arm state stay visible.

## Manual acceptance checklist

Do **A**, B, C, then D separately. Use harmless test surfaces, not production
apps, financial websites, system settings or destructive interfaces.

**A — simulation:** Verify disarmed causes no virtual actions, A/D change state,
POINTING moves only the virtual cursor, quick pinch produces DOWN/UP, held pinch
drags, and both swipe directions produce one intended shortcut. No real mouse or
tabs change. Repeat left/right hand selection, two hands, crossings, overlap and
loss. Unsupported simulated foreground blocks tabs. Q/H/cleanup still work.

**B — live cursor only:** Leave mouse/tab flags absent. Verify startup sends no
move, A arms, POINTING starts without a jump and then moves. Focus another harmless
window and **verify Ctrl+Alt+Esc actually disarms outside preview focus**. Do not
proceed until it works. Re-arm and test loss, UNKNOWN/FIST, overlap, edges,
monitor/DPI setup, D, Q and Ctrl+C. Loss must require manual A and reacquisition.

**C — click/drag:** Enable mouse only. Click harmless test buttons once per quick
pinch. Drag a disposable test object while static POINTING drops out. Release
intentionally, then repeat with emergency, D, tracking loss and exit during drag:
verify immediate UP and no stuck input. Closed/HELD data after rearm must not click.

**D — browser tabs:** Open permitted browser with harmless tabs, explicitly enable
tabs, arm and focus it. Test both directions, one switch per deliberate swipe,
return motion and cooldown. Pinch/drag must block tabs. Unsupported foreground
must receive none. Selected-hand loss/crossing must not switch hands automatically.
Verify the global stop again with the browser focused.

Record screen/DPI/monitor, selected hand, settings, misfires, responsiveness, FPS
and stage timings. Controller-only synthetic timing does not establish webcam FPS
or live responsiveness. Conservative handedness association is not persistent
identity: undetected same-side replacement may be indistinguishable. Overlap
deliberately interrupts controls. EMA adds lag and gain may need tuning. Secure
desktop, elevated apps, remote sessions and display reconfiguration are unvalidated.

Win32 contracts: [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput),
[virtual-desktop mouse packets](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput),
[global hotkeys](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey).

## Implementation validation

The initial Phase 3.6 implementation passed **335 tests**: 16 camera, 135 gestures, 115 tracking (13 new controls
integration tests), 69 new controls/backend/safety tests. The prior 253 tests are
retained. Syntax compilation, CLI help, the original ten tracker commands, dependency
consistency and diff whitespace checks passed. The 69 controls tests also pass
with Python `-S` (no third-party site packages). Required Win32 DLL entry points
resolved on this Windows host and the INPUT ABI size was 40 bytes; this read-only
check performed no input, DPI changes or actual hotkey registration. A synthetic
preview was visually inspected for compact white text on black and both skeletons.
Physical input and emergency shortcut delivery remain manual acceptance checks.

Horizontal-inversion calibration: **341 tests passed** (16 camera, 135 gestures,
116 tracking, 74 controls). Six focused tests cover signed horizontal deltas,
unchanged vertical motion, jump-free anchoring/reset, simulated control, the live
backend path with fake Win32 input, and CLI defaults/options. Syntax, whitespace
and all twelve documented tracker commands passed validation. No real input was
sent; confirm preferred horizontal direction on the webcam locally.

Suggested commit after local validation:
`feat(controls): add safe gesture-based Windows desktop controls`.
