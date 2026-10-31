# Phase 4.2 — Persistent face tracking, target locking and temporal smoothing

Implementation and automated validation are complete. Physical acceptance is
pending owner testing. No camera, live input, identity recognition or future
camera-control features were exercised or added for this phase. The initial
delivery left changes unstaged for review. The owner authorized committing and
pushing Phase 4.2 on 2026-10-30; physical acceptance remains pending.

## Starting state and baseline

Repository: `C:\Users\Darsh\VisionControl`; branch `main`, clean working tree.
HEAD: `daff60c87312fb6e0b0ef83ba8bcf4360d90bec8`,
`feat(visioncontrol): add real-time face detection and positioning`.
The actual pre-change baseline was **806 passing tests**: camera 75, gestures
165, hand tracking 259, controls 267, faces 40. Existing Phase 3 and Phase 4.1
documentation and evidence remain intact.

## Architecture and ownership

The shared capture owner (default MSMF synchronous capture, optional one-slot
`latest-thread`) still produces one frame for both models. Existing hand
preprocessing, inference, association/EMA, gestures and safety-controller dispatch
run first. CPU IMAGE face inference and the stateless geometry adapter follow.
An optional `FaceTracker` then consumes the current immutable `FaceFrame`.
Preview rendering consumes the resulting immutable `TrackedFaces` snapshot.

The tracker is created once per `process_frames` session, on the main thread. It
does not import camera/input APIs, open a camera, initialize a neural model,
dispatch input, alter controller state or create a worker. There is no additional
image copy. Detection cadence, RGB reuse, models and inference resolutions remain
unchanged. Detection-only and disabled-face paths retain their existing behavior.
The existing hand EMA is hand-specific; faces have independent time-based state.
Geometry conversion and bounded `Profile` summaries are reused.

## Association and IDs

Each current box is validated/canonicalized in normalized image coordinates.
Birth ordering uses box geometry, independently of detector ordering/confidence.
IDs increment from 1 for this tracker session; expiration, resolution changes
and `reset()` never recycle them. No identity data or IDs persist between runs.

Association uses deterministic global assignment, maximizing the number of valid
matches, then minimizing total geometric cost. Bitmask dynamic programming is
bounded to **eight active/lost tracks and eight detections**; no new dependency.
The assignment cost is:

`0.55 * (1 - IoU) + 0.35 * center_distance / gate + 0.10 * log(scale_ratio) / log(2)`

The distance gate is `min(0.18, 0.035 + 1.5*dt)` in normalized image units for
continuously visible tracks. Lost tracks and observation gaps above 250 ms use
a stricter maximum of 0.08. Width and height may each change by at most a factor
of two per accepted observation. No positions are predicted or emitted without
a current detection. These initial limits pass controlled separated-motion,
scale-change and rejection tests; they are not calibrated physical accuracy claims.

Near-equivalent global assignments (same match count, cost difference below
0.10) signal uncertainty. Detection boxes with IoU above 0.35, or very close
centers relative to their widths/heights, also signal collision/duplicates.
The whole competing track/detection component is withheld. Involved IDs become
uncertain LOST tracks, quarantined until their original detection timeout;
nearby observations cannot silently replace them under new IDs. Far, independent
observations can still establish new tracks. Detection-capacity overflow rejects
the whole current set explicitly rather than selecting an arbitrary subset.

This policy favors honest loss over a confident spatial identity swap. It can
lose continuity during genuine close encounters or duplicate detector boxes.
Two people exchanging positions between frames can still defeat geometric gates;
temporary IDs never prove real-world identity. Real identity-switch counts are
unavailable without labeled ground truth and are reported as JSON `null`.

## Lifecycle and primary lock

| State | Current coordinates | Behavior |
|---|---|---|
| TENTATIVE | Raw and smoothed | Needs consecutive confirmation |
| TRACKED | Raw and smoothed | Confirmed and currently detected |
| LOST | Absent | Historical geometry kept privately for bounded recovery |
| EXPIRED | Absent | Removed; one expiration snapshot, never revived |

Defaults require **three consecutive matches spanning at least 60 ms**. This
rejects isolated detections and avoids trusting a very fast short burst. A miss
or update gap above 250 ms restarts tentative confirmation. Already confirmed
tracks retain confirmation through plausible short loss. Expiration occurs when
time since the last actual observation exceeds **800 ms**, independently of
processed FPS or miss count. This gives brief occlusions a bounded recovery window.
Changing frame dimensions expires histories; no smoothing crosses resolutions.

Initial primary selection considers only confirmed visible certain tracks:
highest known confidence, then largest area, then ascending geometry and ID.
Once locked, another face cannot steal it because of size or confidence. A
missing primary keeps its lock through the retention window and has no current
position. Plausible spatial reacquisition preserves that ID, resets EMA and
increments explicit recovery counters. It does not establish personal identity.

On primary expiration, clear the lock. Thereafter (also after explicit reset)
automatic acquisition requires exactly one current detection, one confirmed
visible candidate and no unassigned observations. Multi-face scenes remain
unlocked. The conservative single-candidate rule remains in force for subsequent
automatic acquisitions. Manual selection is deferred; no shortcut was added.

## Smoothing, timestamps and freshness

Normalized box edges use EMA with `alpha = -expm1(-dt/tau)`, equivalent to
`1-exp(-dt/tau)`. This smooths both center and size without overshoot; valid input
and convex updates keep coordinates in bounds. The default **70 ms tau** balances
jitter reduction against response delay. Tau zero passes through raw geometry.
Each ID owns its own state. Reacquisition or a gap above 250 ms resets to raw;
unrelated tracks never blend. Confirmation duration remains independent of tau.

Snapshots expose ID/state, current availability, separate raw/smoothed detections,
last actual confidence, first-seen and last-detected times, age, consecutive
matches/misses, primary and uncertainty. Missing coordinates are `None` rather
than `(0,0)`. Historical coordinates are private and never drawn as fresh boxes.

Production passes `perf_counter()` camera read-completion time and current
post-inference host time. Source milliseconds independently fence replay or
backward frames. Nonfinite, negative, future-host, repeated or backward clocks
never ingest current detections. Source timestamps are nonnegative integer
milliseconds bounded to signed 64-bit range. Offline defaults derive seconds
from source milliseconds for repeatable fixtures. `reset()` retains clock fences.

Observation age starts at host read completion, **not sensor exposure**. Smoothing
and missing-frame updates never advance last-detected time. Frames older than
250 ms cannot refresh a track. The overlay rechecks that limit after preview
work, so slow restore/rendering cannot expose a stale fresh box. All lifecycle
updates happen when the consumer receives a frame; an application blocked in
native work cannot display intermediate states. Existing input watchdog and
capture-health fencing continue independently.

## CLI, preview and background behavior

| Option | Default / meaning |
|---|---|
| `--face-tracking` | Off; implies `--face-detection` |
| `--face-only --face-tracking` | Camera + face detector/tracker; no hand model/controls |
| `--face-confirmation-hits N` | 3; integer 1–100, plus fixed 60 ms minimum span |
| `--face-lost-timeout SECONDS` | 0.8, finite positive |
| `--face-smoothing-tau SECONDS` | 0.07, finite nonnegative; zero disables EMA |
| `--face-tracking-debug` | Off; requires tracking; raw magenta and smoothed dots |
| `--no-face-overlay` | Existing option; skips all face drawing |

`--face-only` alone and `--face-detection` alone remain stateless. Hand-only
execution does not import the face subsystem. Face-only still rejects hand
gestures, controls and hand-ID options. Headless tracking requires the existing
timed `--benchmark --headless` combination.

The compact existing face overlay now labels IDs and lifecycle states. Primary
boxes are yellow/thicker, other confirmed boxes cyan, tentative boxes gray.
Lost primary status remains visible without a historical box; uncertainty is
explicit. Existing hand overlays and Q/H/A/D semantics remain intact.
Focused/unfocused previews render; minimized previews keep tracking and skip
drawing. Restore consumes the latest observation without tracker/model reset.
X keeps the existing stop/disarm/release and resource cleanup behavior.
Default capture remains `sync`; `--windows-timer-policy honor-requests` remains
an explicit opt-in, with its existing restoration behavior.

## Diagnostics and measured performance

Existing `--benchmark`, `--performance-profile` and `--report PATH` now include
`face_association`, `face_smoothing`, total `face_tracking` and current
`face_observation_age` timings. They retain inference, controller age, frame
P95/P99, preview-state, CPU and memory summaries. `face_tracking` metadata records
configuration, active count, allocated IDs, primary ID and session transition
counters (including warmup). Timing summaries exclude benchmark warmup. ID
switches remain unavailable for unlabeled hardware scenes; synthetic trajectories
provide separate ground truth. No images, coordinates or application content are
written. Profiling is bounded, opt-in and avoids new timing calls when disabled.

Final evidence: [phase4_2_synthetic_final.json](performance_reports/phase4_2_synthetic_final.json),
with source hashes, Python/platform, raw repeat summaries, CPU and memory samples.
The earlier [phase4_2_synthetic.json](performance_reports/phase4_2_synthetic.json)
is preserved as an initial implementation measurement. Final paired runs use
2,000 measured + 200 warmup iterations, three repeats and alternating order.
The before path is the unchanged Phase 4.1 detector-output geometry adapter;
the after path adds temporal tracking. The optional two-hand workload adds the
existing EMA/static recognition fixtures, with no hand model or desktop input.

**These are synthetic host costs, excluding capture, neural inference and GUI.
They are not webcam FPS, real cursor smoothness or hardware tracking acceptance.**

| Faces | Hand host | Before mean ms | After mean ms | Added ms | Host change |
|---|---|---:|---:|---:|---:|
| 1 | None | 0.0132 | 0.0757 | 0.0625 | +473.0% |
| 1 | Two hands | 0.6232 | 0.6951 | 0.0718 | +11.5% |
| 2 | None | 0.0228 | 0.1345 | 0.1117 | +490.7% |
| 2 | Two hands | 0.6190 | 0.7459 | 0.1269 | +20.5% |
| 4 | None | 0.0406 | 0.3023 | 0.2617 | +644.3% |
| 4 | Two hands | 0.6405 | 0.9130 | 0.2725 | +42.5% |

Values are medians of per-repeat means. Percentages are large against a tiny
geometry-only denominator; they cannot be applied to full application FPS.

| Faces (no hands) | Tracker mean ms | Tracker P95 ms | Tracker P99 ms | Association mean ms | EMA mean ms |
|---|---:|---:|---:|---:|---:|
| 1 | 0.0556 | 0.0611 | 0.1925 | 0.0152 | 0.0139 |
| 2 | 0.1033 | 0.1156 | 0.2630 | 0.0299 | 0.0298 |
| 4 | 0.2476 | 0.6343 | 0.7016 | 0.1277 | 0.0502 |

Columns are separately median run statistics, not pooled distributions. A total
includes validation, lifecycle and snapshot work. Ordinary one-to-four-face costs
meet the sub-millisecond mean target; this does not guarantee every frame is
under 1 ms. Host stalls and larger/dense scenes still need hardware assessment.

Process CPU milliseconds per iteration (before → after) were 0.0156 → 0.0781,
0.0234 → 0.1406 and 0.0469 → 0.3047 for one/two/four faces alone; with two-hand
host work, 0.6250 → 0.6953, 0.6172 → 0.7500 and 0.6406 → 0.9141. CPU clocks
are coarse for very short cases. Per-case working-set snapshots share a process
and allocator, so do not establish isolated working-set overhead. A separate
10,000-frame, four-track Python allocation probe retained **4,816 additional
bytes** after collection, with **875,470 peak traced bytes** and four active
tracks. This includes adapter/tracker allocations and excludes native memory.

Ordinary separated trajectories had **zero synthetic ID switches**. A scripted
short loss reacquired primary ID 1; a crossing withheld both tracks and signaled
uncertainty. Actual inference latency, capture/delivery FPS, 30 FPS combined and
60 FPS face-only goals, focus/minimize timing and physical lock stability remain
unmeasured for Phase 4.2. Phase 4.1 historical results are not substituted for them.

## Automated validation and files

Final suites: camera **75**, gestures **165**, hand tracking **259**, controls
**267**, faces **106**: **872 passing tests**, up from 806. Tests use synthetic
detections/frames, fake tasks/cameras and simulation input. No physical webcam or
real mouse/keyboard dispatch is required or performed.

New tests cover confirmation/time gaps, reordered output/confidence, independent
IDs/EMA, matching gates/global assignment, duplicate competition, ambiguity
propagation/quarantine, lock retention/expiry/reacquisition, missing geometry,
invalid clocks/geometry, variable-dt EMA and no overshoot, reset and replay fences,
capacity, bounded long sessions, immutable snapshots, opt-in profiling and JSON.
Integration covers face-only/combined, disabled tracking, sync/latest-thread,
focused/unfocused/minimized/restored/closed preview, stale rendering, headless
reports, one camera owner, model/camera cleanup, camera faults, tracker faults,
disarmed startup and simulated mouse-button release.

Added `face_tracking/face_tracker.py`, `track_models.py`, `benchmark_tracking.py`,
three focused test modules, this document and two numeric reports. Modified
`hand_tracking/hand_tracker.py`, `face_tracking/preview.py`, the shared integration
test fixture and root/hand/face READMEs. Camera, control, gesture, dependency,
model provisioning and hand-association implementations are untouched.

## Owner hardware acceptance — exact PowerShell commands

Run from the repository. All report names are fresh; existing reports are refused.
These commands intentionally use the default synchronous MSMF capture, requested
1920×1080/60 FPS and face bounds 640×360. They do not silently enable timer policy.
Match face/hand counts, lighting, pose and other workloads between comparisons;
repeat pairs in reverse order. Timer correction is explicit for window comparisons.

```powershell
Set-Location C:\Users\Darsh\VisionControl
$phase42Tag = Get-Date -Format 'yyyyMMdd_HHmmss_fff'

# A-E: stable movement, raw-vs-smoothed jitter, short loss, expiration, second face.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-only --face-tracking --face-tracking-debug --performance-profile --report "hand_tracking/benchmarks/owner_4_2_visual_${phase42Tag}.json"

# Matched headless detection/tracking pairs. Hold the same two hands + face for combined runs.
foreach ($phase42Mode in 'faces_detect','faces_track','combined_detect','combined_track') {
  $phase42Flags = @('--face-detection')
  if ($phase42Mode.StartsWith('faces')) { $phase42Flags += '--face-only' }
  if ($phase42Mode.EndsWith('track')) { $phase42Flags += '--face-tracking' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase42Flags --headless --benchmark --warmup 5 --duration 30 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --report "hand_tracking/benchmarks/owner_4_2_${phase42Mode}_${phase42Tag}.json"
}

# G: for EACH run, after warmup: 0-30 focused, 30-60 unfocused but visible,
# 60-90 minimized, 90-120 restored and focused. Keep two hands + face steady.
foreach ($phase42Mode in 'detect','track') {
  $phase42Flags = @('--face-detection')
  if ($phase42Mode -eq 'track') { $phase42Flags += '--face-tracking' }
  .\.venv\Scripts\python.exe -m hand_tracking.hand_tracker @phase42Flags --benchmark --warmup 5 --duration 120 --width 1920 --height 1080 --fps 60 --backend msmf --capture-pipeline sync --inference-resolution full --face-inference-resolution 640x360 --windows-timer-policy honor-requests --report "hand_tracking/benchmarks/owner_4_2_window_${phase42Mode}_${phase42Tag}.json"
}

# F: gesture compatibility, SIMULATION only. Starts DISARMED; manually A/D.
.\.venv\Scripts\python.exe -m hand_tracking.hand_tracker --face-tracking --gestures --pinch --gesture-states --swipes --controls --control-mode simulate --control-gesture-profile palm-cursor --control-mapping absolute --control-mouse --control-tabs --control-gesture-rearm --control-emergency-hotkey ctrl+shift+f10 --windows-timer-policy honor-requests --performance-profile --report "hand_tracking/benchmarks/owner_4_2_sim_${phase42Tag}.json"

# Offline repeat of the numeric benchmark, no camera/GUI/input.
.\.venv\Scripts\python.exe -m face_tracking.benchmark_tracking --frames 2000 --warmup 200 --repeats 3 --report "hand_tracking/benchmarks/owner_4_2_synthetic_${phase42Tag}.json"

.\.venv\Scripts\python.exe -m unittest discover -s camera -q
.\.venv\Scripts\python.exe -m unittest discover -s gestures/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s hand_tracking -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s controls/tests -t . -q
.\.venv\Scripts\python.exe -m unittest discover -s face_tracking/tests -t . -q
```

For A/B, move in all directions and depth, then hold still; compare raw magenta
and smoothed centers for jitter and delay. For C, briefly occlude/leave and return
within 800 ms, close to the previous location. Very brief absence without a
missed detector result cannot test loss handling. For D, leave for more than
800 ms; verify a new ID on return. For E, start alone, then introduce a second
person who approaches/moves closer: the original primary must keep its lock.
When trajectories overlap, expect explicit uncertainty and possible ID retirement,
not a promise of recognition. If no second person is available, report E as
synthetic-only rather than implying physical verification.

For F, arm simulation yourself and test palm cursor, pointing swipes, pinch
click/drag/release, loss/rearming and left-pinch resume; use D, Q and X during
virtual drag and confirm safe release. Face appearance/loss must not arm controls
or generate actions. Simulation does not register the live global hotkey, so
automated tests and this command do not constitute live-hotkey acceptance.
For G, verify IDs do not reset merely on focus/minimize/restore and X closes
cleanly. Repeat with `--capture-pipeline latest-thread` to assess the optional
one-slot worker; compare its producer FPS/overwrites/host age separately from
sync consumer throughput. Do not run simultaneous camera consumers.

Inspect actual preview-state residency and hand/face distributions, not only the
intended schedule. Compare `timings` inference/association/smoothing/tracker/age,
`pacing.by_preview_state` FPS and P95/P99 completion intervals, `resources`,
`memory`, `face_tracking.counters` and worker `capture_pipeline` where applicable.
Transition samples mix states; steady-state statistics are more informative.

## Safety, limitations and next steps

No controller/camera scheduling/safety code was changed. Disarmed startup,
explicit live opt-in, A/D, Ctrl+Shift+F10 support, watchdog, generation cancellation,
observation freshness, capture fencing, mouse release, gesture rearming and the
3/4-hand observation-only restriction retain their regression coverage. Face
observations have no input path. A tracker failure propagates through the existing
fail-closed cleanup, disarms controls and releases virtual drag in focused tests;
the application exits instead of continuing with a compromised subsystem.

Physical jitter, delay, gate suitability, multiple-person continuity and background
FPS are pending owner acceptance. EMA can lag motion; tau is explicit. No
appearance cues resolve crossings; quarantining can cause deliberate ID loss.
No detector-free bridging, optical flow, Kalman filter or output extrapolation
was added. Eight tracks bound storage and matching work, not a claim of eight-face
model reliability. Python allocation probes do not establish native memory leaks
or an isolated application working-set budget. No inference/OS performance target
is promised from synthetic geometry costs.

After owner review, Phase 4.3 can separately design a consumer of fresh, confirmed,
certain primary snapshots, with explicit behavior for absent/uncertain locks.
Camera-centering decisions and downstream control are not implemented here.
Suggested eventual commit:
`feat(visioncontrol): add persistent face tracking and target locking`.
