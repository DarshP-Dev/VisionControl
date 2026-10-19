# Phase 3.6: Windows desktop controls

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
- `cursor.py`: relative index-tip mapping and screen-space EMA.
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

This is consistently **relative hand-displacement mapping**. Win32 normalized
absolute packets only deliver the computed physical-pixel target without Windows
relative acceleration; they are not an absolute camera mapping. Right/down in
the unmirrored image moves right/down. No optical FOV/pointing-angle calibration.

Live startup establishes per-monitor DPI awareness before OpenCV creates a window;
physical cursor/monitor coordinates receive no second scaling multiplier.
`--control-monitor 0` is primary; others sort by left/top desktop origin, including
negative origins. Movement stays on that one monitor. Place the cursor there
before arming, avoiding a cross-monitor activation jump. Restart after display,
desktop or DPI reconfiguration. Simulation never queries Windows and uses its
own virtual monitor (1920x1080 by default).

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

**335 tests passed**: 16 camera, 135 gestures, 115 tracking (13 new controls
integration tests), 69 new controls/backend/safety tests. The prior 253 tests are
retained. Syntax compilation, CLI help, all ten tracker commands above, dependency
consistency and diff whitespace checks passed. The 69 controls tests also pass
with Python `-S` (no third-party site packages). Required Win32 DLL entry points
resolved on this Windows host and the INPUT ABI size was 40 bytes; this read-only
check performed no input, DPI changes or actual hotkey registration. A synthetic
preview was visually inspected for compact white text on black and both skeletons.
Physical input and emergency shortcut delivery remain manual acceptance checks.

Suggested commit after local validation:
`feat(controls): add safe gesture-based Windows desktop controls`.
