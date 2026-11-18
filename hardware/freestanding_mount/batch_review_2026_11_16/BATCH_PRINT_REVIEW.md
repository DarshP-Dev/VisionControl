# Suggested batch review — 2026-11-16

Recommendation: **Base + BallastCover + corrected PanHornCoupon + corrected
TiltHornAdapter**, one each. The two larger additions are independent of the
unresolved servo axial measurement and horn-hole adjustment. This is a candidate
one-batch selection, subject to actual slicer support and drainage checks.
No CAD/STL geometry was altered; no printer was run and no commit/push occurred.

## Scope and evidence

Reviewed FIT_OFFSET_REVIEW.md, SERVO_MEASUREMENTS.md, BOM.csv, current generator,
parameters and geometry reports. Read all12 current STLs using FreeCAD/Mesh:
all are closed; dimensions, mesh volumes and SHA256 are in inspection.json.
All selection files come from output_fit_offset_2026_11_16. The BOM's printed-parts
row still names output_measured_fit; that is historical and should not be used
for the two corrected horn parts. The source BOM was not modified by this review.

Executed temporary in-memory parameter sensitivity checks, without saving design
changes: shaft projection5 ->3.5 and washer thickness2 ->3 changed Pedestal;
pan offset0.1 ->0 changed PanRotor/PanHornCoupon; tilt offset0.1 ->0 changed only
TiltHornAdapter; bushingOD8 ->8.5 changed LeftFork; pivot5 ->5.5 changed Cradle.
These probes demonstrate direct dependencies, not proposed new dimensions.
Physical mating dependencies are assessed separately, especially the right flange
which is not controlled by ServoShaftProjection in the current script.

SAFE TO PRINT NOW means no expected rework from the two open servo issues under
the retained architecture. It does not certify cured-resin strength, actual screws,
standard hardware fit or printing success. PRINT AT RISK means another known
provisional interface can waste the print. WAIT means direct unresolved servo
interfaces warrant deferral. The required test copies are explicitly distinguished
from production release.

| Component | Classification | Solid resin ml | Concrete dependency / reason |
|---|---|---:|---|
|Base|SAFE TO PRINT NOW|79.25|Independent110x100x14 base: pedestal boltsX±31/Y±8, M3 nut seatsAF5.8/depth2.6, open ballast pockets, foot recesses and cover holes. No servo shaft, horn or axial mating features. Verify standard hardware/feet fit after cure.|
|BallastCover|SAFE TO PRINT NOW|23.68|92x88x3 plate matches unchanged base holesY±40 and foot corner reliefs. Flush underside countersinks and cover flatness matter; no servo/horn interfaces.|
|CameraPlate|SAFE TO PRINT NOW|18.50|90x52x4 blank camera region, four M3 holesX±34/Y±18 and countersinks. Owner drills camera hole later. No dependence on either horn bore or servo mating-face height; verify eventual washer access through cradle.|
|CableSaddle|SAFE TO PRINT NOW|1.61|24x10x8 saddle with open nominal6.5mm cable groove and two M3 holes16mm apart. Ties to the retained rotor mounting pattern; not the central horn or journal stack. Actual cable/strap fit remains a routine check.|
|LeftFork|PRINT AT RISK|11.88|Passive support contains8.2mm bushing seat,16mm boss and8mm bushing length. Actual bushingOD/shoulder/washer/end-play stack remains unverified. No direct horn-offset dependency, but final transverse spacing and passive pivot must agree with corrected tilt stack.|
|Cradle|PRINT AT RISK|27.34|Carries5.3mm passive-pivot hole, right7mm centre access and M3 adapter holesY±9, with90mm inside width. None uses corrected horn bore coordinates; however actual pivot diameter/end play and adapter-to-cradle axial fit remain provisional. Do not assume it is independent just because it has no servo pocket.|
|Pedestal|WAIT FOR FIT VALIDATION|47.52|Servo shelf height explicitly equals deck minus shaft projection minus wing thickness minus pan hub thickness. Bearing plane also uses washer thickness. Passed body coupon does not validate this axial load path, case clearance or the35.5/34mm datum discrepancy.|
|PanRotor|WAIT FOR FIT VALIDATION|30.31|Contains the corrected horn holes,3mm hub and5.5mm supported journal. Failed offset or revised axial seating can require reprinting this30.31ml part. Coupon reproduces its central interface; wait for that result and axial stack.|
|RightFork|WAIT FOR FIT VALIDATION|12.41|Contains servo flange/contact face, tab holes,38mm horn opening and22x1mm tail relief. Servo axial position relative to adapter/cradle is unresolved. The script does not automatically move this flange when ServoShaftProjection changes, so zero sensitivity to that parameter is NOT evidence of mechanical independence.|
|TiltHornAdapter|PRINT AT RISK|6.59|REQUIRED TEST COPY in this batch. It is already the real full-assembly adapter, with corrected bores and fixed eccentric head recesses. Reusable only if alignment, head seating and final axial stack pass; do not print a second production copy yet.|
|PanHornCoupon|SAFE TO PRINT NOW|11.10|REQUIRED DIAGNOSTIC COPY. Its purpose is to validate the unverified correction; this classification does not imply production fit is approved. It is not a structural assembly component.|
|ServoFitCoupon|SAFE TO PRINT NOW|3.38|Already passed; omit from this and future batches unless the body/tab interface changes. No benefit from another copy now.|

## Why this selection

Prioritize the79.25ml base and23.68ml cover. Together they finish the desk/base
subassembly and are the largest independent pair. CameraPlate18.50ml and
CableSaddle1.61ml are also acceptable early prints, but no clear supported envelope
for them remains in the conservative four-part plan. They are first choices if
the slicer demonstrates usable extra space; do not fill drainage/support corridors.
Do not nest a part in a ballast pocket or coupon cavity to squeeze it in.

If steep cover supports cannot fit, remove BallastCover first, keep Base plus the
two tests, and reconsider a shallower base orientation. A base tilted30 degrees
about its100mm direction has a conservative110.26 x108mm reserved footprint;
the two test envelopes can then stack in the right-hand column with5mm gap.
That three-piece fallback is96.94ml solid, about131–155ml with the same generous
support allowance. This is also a geometric plan, not a validated slicer layout.

## Resin estimate

The recommended four parts total **120.61ml solid BRep volume**. Allow **42–72ml**
for supports/rafts (35–60%, deliberately broad for the tall structural orientations):
**163–193ml supported print volume**. A separate5–10ml handling allowance gives
roughly **170–205ml practical consumption planning**. This is not a vat-fill amount;
resin left in the vat is not consumed. Replace these estimates with slicer volumes.
No exposure times, support count or duration were calculated. CameraPlate adds
18.50ml solid; CableSaddle adds1.61ml, plus their actual supports if included.

## Plate-space assessment — NOT SLICER VALIDATED

Assumes the192 x120mm plate is available for these four objects. If other models
are already on the plate, subtract their complete support/raft envelopes first.
The calculation reserves5mm from plate edges,5mm between reserved rectangles,
and4mm extra around each bare part footprint for lateral support/raft spread.
The4mm is only a placeholder; bracing may need more. Assumed lowest-part lift8mm.

Base:65 degrees from flat, about its100mm direction (localY). Cover:65 degrees
from flat, about its92mm direction (localX). This steep packing reduces plate
footprint but produces tall builds needing braced supports; it is a proposed
orientation change for these unprinted structural parts, not a proven recipe.
Choose rotation signs to keep underside pockets open to resin flow and washing.

**Keep both horn test parts at their previous successful orientations**, exposure,
layer height and cure, to isolate the0.1mm CAD change. Their reserved boxes use an
all-orientation bound of the enclosing cylinders: sqrt(diameter²+thickness²).
Thus the52.53mm and48.45mm reserved squares already include4mm per-side allowance
and do not require a new coupon orientation. Actual supports may exceed these.

Origins below are lower-left corners of reserved rectangles, in plate millimetres,
not STL origins or slicer transform values. Plate origin=(0,0), opposite=(192,120).

| Object | Reserved origin X,Y | Reserved width x depth | Maximum/planned height with8mm lift |
|---|---|---|---|
|Base|5.00, 5.00|67.18 x 108.00|113.61|
|BallastCover|77.18, 5.00|100.00 x 47.91|89.02|
|PanHornCoupon|77.18, 57.91|52.53 x 52.53|52.53|
|TiltHornAdapter|134.70, 57.91|48.45 x 48.45|48.45|

Rectangles were numerically checked for overlap and margins. All remain inside
x5..187/y5..115; tallest planned object is about114mm, below245mm. Available
plate area alone does not establish support feasibility, resin flow or print
success. See plate_envelopes.svg for a diagram of these reservations. No actual
supports, slice layers, peel-force estimate or printer file were generated.

## Supports, drain access and peel review

- Base: two open underside ballast pockets, nut bosses and foot recesses are real
  geometry. Open pockets can still create suction during intermediate layers.
  Orient and inspect them so no sealed pocket grows against the release film;
  retain access for wash/cure and cutters. Brace the tall support structure and
  carry the leading edges, pocket roof islands and bosses. Keep support scars off
  pedestal seating, nut seats and feet. The79ml base is the main peel
  and support load; do not use the small coupon support recipe unchanged.
- Cover:3mm broad plate is prone to warping and support damage. Use distributed
  edge/back support and cross-bracing for the tall lean; protect the countersinks,
  flush desk-facing head seats and mating perimeter. Avoid printing it flat on
  the plate or relying on a few corner supports.
- Pan coupon: open journal cavity and7mm through-access must remain unobstructed.
  Do not assume a small central hole guarantees a vent at every layer. Preserve
  the previous support layout where successful and inspect any cup warning.
- Tilt adapter: protect mating faces,2.3mm corrected bores, central opening and
  fixed head recesses from support tips. Verify islands around recesses. Reuse the
  successful orientation; compare both corrected holes with the horn centred.
- Separate rafts and a5mm gap are starting allowances for access/flow, not measured
  removal-tool clearance. Confirm cutters reach support contacts; remove pieces
  individually for washing rather than burying them in a single support forest.
- A crowded plate increases total cross-sectional area and can change peel behaviour
  relative to the successful coupon-only run. Keep the calibrated resin exposure;
  inspect all layers for unsupported islands, sudden area changes and sealed cups.
  If adequate supports or ventilation need more space, drop the cover. Do not
  under-support or add drainage holes to the CAD without a separate design decision.

General process references: [Anycubic support guidance](https://wiki.anycubic.com/en/filament-and-resin/only-print-support-without-printing-the-model)
emphasizes supporting initial overhangs and avoiding large unsupported areas.
[Formlabs suction-cup guidance](https://formlabs.com/support/Preventing-suction-cups-in-PreForm/)
explains how cavity orientation can cause suction and failures. These support
principles inform this review; they do not validate Photon Mono X settings or the
proposed orientations.

## Remaining parts after this candidate batch

- SAFE, deferred for plate space: CameraPlate, CableSaddle.
- PRINT AT RISK: LeftFork, Cradle; measure actual bushing/pivot/end-play and confirm
  final side spacing before spending resin if you want to avoid reprints.
- WAIT: Pedestal, PanRotor, RightFork; resolve axial stack and corrected horn fit.
- TiltHornAdapter from this batch becomes a production part only after passing
  fit and final stack checks. If it fails, another revised adapter is required.
- ServoFitCoupon is already complete. PanHornCoupon is a diagnostic and never an
  installed structural part.

The supplied one_batch_selection.zip contains exactly the four original STL
files plus this review, manifest and planning diagram. Mesh hashes match the
source exports. It contains no supports or printer-ready sliced file.
