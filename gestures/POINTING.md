# Targeted POINTING reliability follow-up

This is the bounded recognition fix before Phase 3.7. Physical webcam validation
is pending. No desktop-control behavior or state
timing has been changed. Synthetic results below establish specific failure paths
and regressions, not physical accuracy or webcam FPS.

## Findings and rule changes

The starting classifier was already calibrated: POINTING required index PIP
≥150°, DIP ≥145°, straightness ≥0.88 and tip/wrist ≥1.15. Each other long finger
independently needed PIP ≤110°, DIP ≤160°, straightness ≤0.75, tip/wrist ≤1.65,
and an index-minus-other tip/wrist difference ≥0.25. The earlier 1.25 FIST distance
limit was already relaxed for POINTING; repeating that calibration would not
address the remaining failures.

Two concrete synthetic false-negative paths were reproduced:

* A mostly straight index with PIP 148°, DIP 164° and a long, straight chain
  fails only the old 150° PIP test. The new POINTING PIP minimum is **145°**.
  DIP ≥145°, straightness ≥0.88 and tip/wrist ≥1.15 still apply together.
* A finger folded at the PIP with a relaxed straight distal segment measures
  PIP 65°, DIP 180°, straightness about 0.54 and tip/wrist about 1.45–1.52.
  It failed only the old independent DIP curl veto. **POINTING no longer
  requires curled-finger DIP ≤160°**. PIP ≤110°, straightness ≤0.75, tip/wrist
  ≤1.65 and separation ≥0.25 remain mandatory for each middle/ring/pinky finger.

All four long fingers still need complete, finite, in-range geometry, including
valid DIP angles. Relaxing a curl condition does not authorize missing DIP data.
Diagnostics label those angles `DIP_degrees_valid`; ≤180° is a validity bound,
not a demand for distal flexion. Out-of-range angles display INVALID.

These are supported explanations for possible camera failures. No captured
landmark fixtures were found, and real failing webcam measurements were not
available. Additional failures can come from PIP, straightness, wrist distance
or separation; those bounds have deliberately not been loosened here.

## Safety and rotation

OPEN_PALM and FIST retain their existing thresholds, including FIST's DIP ≤160°
and tip/wrist ≤1.25. The existing clear-thumb-only FIST exclusion is unchanged.
Thumb posture does not gate POINTING. The index extension and curl PIP ranges
remain separate. Peace signs, three-finger poses, thumbs-up, ambiguous index and
middle extension, invalid geometry and rule conflicts retain UNKNOWN. A folded
PIP alone cannot establish curl: the chord, wrist distance and relative index
separation must also agree. There is no nearest-class fallback or rule priority.

Features already use relative segment angles, chord/chain ratios and palm scale
in aspect-correct 2D coordinates. They do not depend on a fingertip being above
a knuckle. Translation, uniform scale, mirroring and image-plane rotation need
no new coordinate system. This fix removes one redundant projected-angle veto;
it does not add depth-based inference or estimate wrist orientation.

Rigid 3D rotation followed by orthographic projection tests modest ±30° yaw,
30° pitch, a 90° image-plane sideways pose and observable back views at 150°/180°
yaw. These ideal articulated fixtures are planar; they do not reproduce real
hand depth, perspective, landmark estimation errors or occlusion. A back view
with correct visible geometry is recognizable; this is not a guarantee that the
camera can recover hidden fingers.

Known uncertainty remains explicit. In a relaxed pointing fixture, 35° image
rotation plus 45° yaw exceeds the other-finger wrist-distance limits; 90° image
rotation plus 45° yaw fails ring/pinky index separation. Both stay UNKNOWN.
Some projected fists at ±30°/150° yaw also exceed the pre-existing strict FIST
distance limit and stay UNKNOWN, never POINTING. Face-on and full back-view
fists retain FIST in the tested fixtures. No FIST threshold was widened to hide
these limitations.

Near edge-on hands, an index aimed into the lens, overlapping/hidden fingers or
collapsed projected segments may not be distinguishable safely. UNKNOWN is
appropriate. Finite, plausible but incorrect MediaPipe estimates cannot always
be detected from these features. There is no reliable occlusion confidence here;
diagnostics explicitly say depth/occlusion is not assessed.

The existing EMA feeds recognition (current-sample weight 0.75). During movement,
blended coordinates may briefly describe an intermediate pose. No label hold,
extra smoothing, debounce or cursor grace period was added. Compare raw input
separately to identify smoothing effects; retain existing loss/cancellation
behavior.

## Diagnostic and physical validation commands

Run these from the repository in PowerShell. The first command enables only
static recognition; desktop controls, pinch, swipes and event management remain
off because their flags are absent. CLI behavior is covered by automated tests;
the physical webcam session has not been run for this fix.

```powershell
Set-Location C:\Users\Darsh\VisionControl
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures

# Same static recognition with sampled console diagnostics:
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug

# Separate comparison when checking whether EMA contributes to an UNKNOWN:
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug --no-smoothing
```

Debug is optional, off by default and sampled at most once per two seconds.
It reuses classification checks, reports final class, matched rules, reason,
index extension and each other finger's curl, numeric values/bounds, and failed
conditions. Assessments distinguish index extension failure, other-finger curl
failure, unsupported thumb-only configuration, invalid/unreliable measurements
and conflicting rules. A valid unsupported pose also has
`reason=ambiguous_or_unsupported_pose`; the individual checks show why it fails
POINTING. Frame slots are not persistent identities. No images or raw x/y/z
coordinates are saved or logged.

To collect numeric samples locally in the existing Git-ignored directory:

```powershell
New-Item -ItemType Directory -Force -Path .\hand_tracking\benchmarks | Out-Null
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --gesture-debug 2>&1 | Tee-Object -FilePath "hand_tracking\benchmarks\pointing-debug_${runStamp}.txt"
```

1. Hold natural right-hand pointing for 4–6 seconds, then repeat with the left.
   Repeat with a slightly bent index, individually relaxed curled fingers and
   a relaxed thumb. Vary distance while keeping landmarks visible.
2. Hold palm-facing, sideways and back-facing poses. Rotate slowly between them;
   record which pose corresponds to each two-second sample. Note any UNKNOWN or
   unexpected FIST while pointing and the exact failed checks.
3. Hold fully closed fists from the same orientations, then peace signs,
   thumbs-up, three-finger and partially extended index/middle poses. Confirm
   they never produce POINTING. Switch between POINTING and FIST repeatedly.
4. Test both hands simultaneously, detection order changes and leaving/reentering
   the frame. Compare a separate `--no-smoothing` run if failures occur mainly
   during rotation. Q exits; H toggles the existing preview mode.
5. Share a few passing/failing numeric blocks with handedness, intended posture
   and orientation notes. Hold poses long enough for multiple samples. Do not
   infer a frame-level failure rate from the sparse log samples.
6. Only after static recognition passes physically, test the existing cursor
   activation. Start with simulation, then use your existing validated live
   configuration and arming procedure from [controls documentation](../controls/README.md).

```powershell
# Optional later cursor smoke test; simulation sends no OS input:
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --gestures --pinch --gesture-states --controls --control-mode simulate --control-mapping absolute
```

Use diagnostics off for a matched preview/FPS comparison. Cursor mapping, active
region, inversion, clicking/dragging, tabs, arming and emergency stop are unchanged.
No controls files were edited. No additional model, dependency, inference pass,
thread, event system or per-frame log was introduced.

## Automated evidence and performance

Starting revision: `a1c0231`. Root unittest discovery initially passed **383**
tests. It omits `camera/` because that directory is not a package; the unchanged
camera suite has **16** passing tests, giving a combined starting baseline of
**399**, rather than the previously reported 388.

The focused comparison pins the committed classifier at starting revision
`a1c02314631cc0e394956aaf99dc14681d591c7d` and uses exactly the
same 272 cached-feature inputs for both implementations. It intentionally targets
the reproduced failures, and is not an unbiased accuracy dataset:

| Synthetic group | Cases | Before | After |
| --- | ---: | --- | --- |
| Individually/all relaxed distal curls | 8 | 8 UNKNOWN | 8 POINTING |
| Mostly straight, bent index | 4 | 4 UNKNOWN | 4 POINTING |
| Natural pointing, sides/scales/projected orientations | 180 | 180 UNKNOWN | 180 POINTING |
| Fists/open palms/unsupported configurations | 80 | 8 FIST, 10 OPEN_PALM, 62 UNKNOWN | Identical for every case |

Separate regressions preserve UNKNOWN for combined foreshortening, collapsed or
missing geometry, invalid distal angles and shallow/extended other fingers.
Existing open-palm/fist/pointing cases remain intact. Integration exercises new
natural poses through EMA, two-hand order/handedness association and the existing
event manager, including immediate UNKNOWN cancellation, loss and reacquisition.
The full pinch/swipe and desktop-contract suites still pass.

Final results: **410 tests passed** (144 gestures, 137 hand tracking, 113 controls,
16 camera). Root discovery alone reports 394. Reproduce all suites explicitly:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m gestures.tests.benchmark_pointing
```

The benchmark alternates before/after order, warms up 200 two-hand iterations,
then measures 2,000 per version with diagnostics off. On this host the cached
two-hand rule mean/p95 was **0.0597/0.1030 ms before** and **0.0560/0.0923 ms
after**. This small difference is not evidence of improved camera FPS; extraction,
inference, smoothing, rendering and logs are excluded. Default classification
removes three DIP comparisons and adds no geometry or diagnostic records.

## Files and review boundary

* `gestures/static_gestures.py`: two POINTING-only rule adjustments and sampled
  angle/range validity reporting.
* `hand_tracking/gesture_debug.py`: grouped explanations from the same checks.
* `gestures/tests/static_fixtures.py`: explicit projected-rotation helper.
* `gestures/tests/test_pointing_reliability.py`: focused natural/rotation/safety regressions.
* `gestures/tests/benchmark_pointing.py`: reproducible starting-revision comparison and timing.
* `hand_tracking/test_gesture_debug.py`: assessment coverage.
* `hand_tracking/test_gestures.py`: natural-pose EMA/event integration.
* `gestures/README.md` and this document: current rules, evidence and manual procedure.

Further threshold tuning requires actual webcam samples, especially failed curl
distance/separation, nearly edge-on poses and POINTING/FIST confusions. Nothing
in this change claims those physical failures are fully resolved. Stop here for
owner testing; no Phase 3.7 work. Stage, commit or push only on explicit owner request.

Suggested future commit:

```text
fix(gestures): improve pointing recognition across natural hand poses
```
