# CAD validation — measured-horn fit revision, 2026-11-07

Current output: **output_measured_fit/**. FreeCAD1.1.4 executed the generation,
exports, read-back checks, recomputation and GUI rendering. This establishes
CAD integrity within the modeled assumptions, **not physical fit or print release
of the complete mount**. Start with FIRST_PRINT.md.

## Preserved starting state and scope

Git began with only the existing untracked hardware/freestanding_mount/ tree and
hardware/freestanding_mount_package.zip. No app files, staging, commit or push
were involved. Previous sources/docs are in history/pre_measured_horn; previous
output_verified and ZIPs were preserved. This revision changes four assembly
parts (Pedestal, PanRotor, RightFork, TiltHornAdapter), adds a pan-interface coupon,
and updates parameter provenance, verification and documentation.

Base110 x100, height target140, pan±60/tilt±35, passive tilt pivot and supported
pan journal remain. Boolean symmetric differences are zero for Base, BallastCover,
LeftFork, Cradle, CameraPlate, CableSaddle and ServoFitCoupon. A material probe
confirms the camera plate's central area remains solid and its thickness is4 mm.
No new resin optimization was attempted.

## Measurements and unresolved axial fit

Owner approximate measurements incorporated: body22.8 x12.2 x28.5, wing2, hubOD6,
inner-hole radius4.5, outer-hole radius14.5, installed body-bottom-to-highest-point
height34 mm. Parameter changes and rationale are in SERVO_ACCESSORY_REVIEW.md;
measurement_status.json classifies every parameter.

The outer pair requires local interface enlargement; the4.5 mm pair would overlap
the existing7 mm centre access with a2.3 mm printed hole. The full horn outline,
small pilot diameters, tab geometry, shaft offsets and screw dimensions remain
unmeasured. Radius18 mm is a clearance budget, not measured horn radius.

**Axial HOLD:** the legacy model places the flat wing mating face35.5 mm above
body bottom, while34 mm is the reported highest point. The latter is not a tab
datum, not necessarily the mating plane, and never34 mm above the case. Even if
28.5 mm is a matching case datum, the resulting5.5 mm describes height to the
highest point only. Measure B-to-M and T-to-M before finalizing the full assembly.

## Executed checks

| Check | Actual result |
|---|---|
| Printed shapes |12 valid, connected single solids;10 assembly parts plus2 coupons|
| STL exports/read-back |12 closed meshes; maximum volume difference0.252885%|
| STEP exports/read-back |12 valid single solids; maximum volume error1.75e-9 mm³|
| FCStd reopen/recompute |Assembly19 valid geometry objects; exploded10; tilt10-degree change and neutral roundtrip passed|
| Selected hole material probes |Four independent2.2 mm probes at measured±14.5 centres found zero blocking material|
| Camera plate probe |Central solid material and4 mm thickness confirmed|
| Assembly motion |375 poses: pan-60..60 and tilt-35..35 in5-degree increments; zero intersections above0.01 mm³|
| Assumed hardware budgets |No neutral intersections; full360-degree tilt sweeps of attachment heads and M3 heads/nuts/shafts clear fixed fork/servo/rotor geometry|
| Driver paths |4 mm straight-tool budgets clear before camera installation; pan also requires plate removal|
| Existing engineering checks |7 unittest checks passed, including source syntax and arithmetic|
| Drawings |12 kernel-projected SVG/PNG sheets, zero generation errors; pre-mesh BRep bounds used for dimension text|
| GUI renders |7 views generated; neutral, combined extreme, exploded, first-print set and representative updated drawings visually inspected|

Main combined-motion testing is sampled, not a proof of every intermediate pose.
Continuous hardware sweeps are conservative full-circle annular volumes relative
to the tilt supports, not a claim that the servo can rotate360 degrees. The horn
discs already bound all in-plane orientations within the assumed18 mm radius.

### Executed clearance results (mm)

- Pedestal/rotor radial clearance0.25; journal wall3.25; axial bearing engagement3.5.
- Pan rotor/cradle minimum6.874; either fork/cradle minimum2.874 across the sampled sweep.
- Pan tab-head budget to journal0.5 after shortening the journal7 ->5.5.
- Tilt M3x14 tail sweep to relieved right flange0.5; nut budget to right fork0.6.
- Horn radius18 budget to pan cavity0.5; to tilt opening1.0 (radial).
- Measured6 mm hub OD to7 mm centre access0.5 radial; actual axial hub projection unknown.
- Tilt attachment grip3.8 after5.5 diameter x2.2 deep rear recesses.

The head budget is4.5 diameter x2 mm high for supplied tab/horn-attachment screws;
centre-head budget5.5 diameter with2 mm projection. These are accommodation targets,
not measurements. M3 check uses14 mm under-head length,0.5 washer thickness,
headOD6 x3 and nut envelopeOD6.4 x2.4. Supplied screw tips/threads, actual hub
projection and real washers are not geometrically verified. Recheck changed hardware.

Diagnostic iteration output_measured_fit_v1 recorded11.637 mm³ pan tab-head/journal
intersection and blocked pan tool access with the camera plate installed. The
journal was locally shortened and the assembly sequence corrected. Iteration_v2
then recorded7.069 mm³ neutral M3-tail/right-fork interference. The final1 mm-deep,
22 mm diameter flange relief resolves that budget conflict while leaving3 mm
flange thickness. Both failed iterations remain for traceability; do not print them.

## Resin, loads and stability

Actual assembly BRep volume is259.071 ml versus258.563 ml previously: +0.509 ml
(+0.197%). ServoFitCoupon3.380 ml; PanHornCoupon11.103 ml; TiltHornAdapter6.586 ml
(the adapter is already counted in assembly volume). First three-part print totals
21.069 ml, roughly26–31 ml including25–45% supports/waste. Assembly plus both
standalone coupons totals273.554 ml, roughly342–397 ml. Reprinting an unusable
adapter adds6.586 ml plus supports. No slicer support estimate or cured mass was
measured; the1-litre purchase does not require further optimization.

At assumed resin density1.15 g/ml, current printed tilt mass is60.291 g. Updated
CAD-mass/COM tilt screen gives nominal gravity0.007635 N·m, added15 mm COM-uncertainty
moment0.023034, startup inertia0.000270 at the existing assumed acceleration,
and cable0.008 at assumed0.2 N x40 mm: total approximately0.03894 N·m.
The0.04903 N·m planning screen is25% of advertised stall torque, NOT a continuous
rating. Fastener mass, joint friction, actual cable resistance and thermal duty
remain unmeasured; sudden reversals or larger cable pull can dominate this margin.

With250 g restrained ballast, assumed25 mm moving-group COM offset and0.5 N
horizontal load at140 mm, current tipping ratio is2.168; about198 g ballast would
meet a2.0 ratio in that model. This is not a sliding, shock or actual desk test.
The camera COM, optical height, resin creep, fatigue, screw pull-out and structural
stress concentrations require physical testing. No FEA/strength certification.
Existing ribs/walls are retained; edge treatments are not automatically proof of
sufficient fatigue strength. Do not force or over-tighten resin joints.

## Reproduction, deliverables and next gate

README.md gives exact FreeCAD PowerShell commands. generate_freecad.py refuses to
overwrite output folders. verify_exports.py reads actual files; verify_interfaces.py
checks this measured revision and exits on hardware-budget failures. Its comparison
uses history/pre_measured_horn/parameters.json. render_cad.FCMacro renders actual
CAD; it does not send servo signals.

Reports: geometry_audit.json, export_verification.json, interface_verification.json,
render_status.json and gui_pose_debug.json in output_measured_fit. Root validation.json
records current source/output hashes and the physical-validation hold. Drawings
are projected dimension/schedule sheets, not fully toleranced manufacturing drawings.

Print only the three first-fit parts, use FIRST_PRINT.md pass/fail checks, and
record FIRST_PRINT_RESULTS.md. Resolve mating-face/tab datums, attachment bores,
screw type/engagement and full outlines before complete printing. Then validate
journal load path, bushing end play, dummy load, cable loop, limited powered motion
and final desk stability. No actual motor operation or physical test occurred here.
