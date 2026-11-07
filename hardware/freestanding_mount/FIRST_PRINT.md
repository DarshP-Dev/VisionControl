# First physical fit print

Use **output_measured_fit/stl/**. Print one of each of these three parts, then test
both servos and both selected horns sequentially. Do not print the full mount yet.

| File | What it tests | Solid resin |
|---|---|---|
| ServoFitCoupon.stl | Body aperture23.4 x12.8;4 mm plate; provisional28 mm tab pitch and2.3 mm holes |3.38 ml|
| PanHornCoupon.stl | Actual central rotor section: cavityID37, outside43.5, outer-hole radius14.5, centre access7, printed screw grip7 mm |11.10 ml|
| TiltHornAdapter.stl | Actual reusable adapter:OD40 rear/36 nose, thickness6, outer-hole radius14.5, rear head recesses5.5 x2.2; remaining grip3.8 mm |6.59 ml|

Total **21.07 ml solid**, approximately **26–31 ml** with a25–45% support/waste
allowance. This is not a slicer prediction. The adapter's other two holes at
radius9 are M3 cradle fasteners, not horn attachments.

## Slicer and preparation procedure

1. Import in **millimetres**, with no automatic scaling. Check aperture and outer
   diameters. Use the original Photon Mono X192 x120 x245 profile and calibrated
   ABS-Like Resin3.0 exposure. Do not borrow untested exposure values.
2. Start with20–30 degree tilt for the body coupon and pan core, about30 degrees
   for the adapter. Keep the core's open cavity tilted to drain; avoid a closed
   cup or broad unsupported horizontal roof.
3. Support outside edges/non-contact faces; keep supports out of the aperture,
   horn contact lands, journal cavity, bores, centre access and head seats. Review
   every slice for islands at recesses/overhangs. Do not hollow these parts.
4. Verify the **supported** build envelope fits. Record layer height, temperature,
   exposure, orientation and supports. The CAD fit flag covers bare parts only.
5. Wash, dry and fully cure according to the resin guidance before measuring.
   Remove nubs without altering test surfaces. Reject cracks, soft areas, trapped
   resin or rocking contact lands. Measure cured dimensions before fitting hardware.

## Pass/fail sequence — servo power disconnected

| Test | Pass condition | Failure response |
|---|---|---|
| Body A and B | Slides through aperture with light finger force; no bending tabs/case or pinching lead | Record actual/cured dimensions; adjust clearance locally |
| Tabs | Both actual holes align simultaneously; contact faces sit flat | Measure each centre/contact face; revise interface |
| Tab mounting | Verified fasteners retain tabs without resin threads, cracks, bottoming or dangerous protrusion | Identify screw/joint type; do not force coarse screws into resin |
| Stock horn seating | Matching horn seats squarely; supplied centre screw retains it without bottoming | Measure hub/shaft/head stack; never force generic spline fit |
| Outer pair | Two locating pins or suitable loose screws align simultaneously at29 mm candidate span without bending horn | Measure signed coordinates and bores; revise coupon |
| Pan outline/hub | Entire horn entersID37 cavity with all-around clearance; wing contact lands lie flat; hub does not prop up the print | Measure full outline and both boss projections |
| Tilt outline/hub | Wing sits flat; localZ outer pair aligns; localY M3 holes and nut/washer footprints remain accessible | Measure and revise; do not trim stock arms |
| Recessed attachment heads | Actual heads fit5.5 x2.2 pockets fully below cradle-facing surface; remaining grip undamaged | Measure heads/driver; revise recess and recheck remaining material |
| Horn attachment | Two verified screws retain each print without pilot stripping, pull-through, split horn or excess tips | Select type/length from actual bore, grip and usable engagement |
| Centre access | Actual driver reaches and turns the supplied centre screw while horn/coupon is seated | Measure head/driver; recheck surrounding material before enlargement |
| Shaft clearance | Installed horn square, core/adapter clear of case and shaft boss; no lead trapped | Measure shaft offsets and axial stack |
| Axial datum | Record B-to-C, B-to-M, T-to-M, B-to-H and resolve34 mm highest point vs35.5 mm CAD mating face | **Hold full assembly print** until CAD axial stack is corrected/verified |

Datums: B=measured body bottom, C=case top excluding shaft, M=flat horn wing face
contacting print, T=tab mounting-contact face, H=highest installed point. Record H
with and without the centre screw. Definitions and remaining dimensions are in
SERVO_MEASUREMENTS.md. Log both units in FIRST_PRINT_RESULTS.md.

If screw selection is unresolved, use locating pins for an alignment-only trial.
That can establish pattern/outline fit while retention remains unverified. The
pan core is not a complete pedestal fixture, and the body coupon does not locate
the entire axial shaft stack. Use calipers/depth gauge for those datums. A loose
fit does not validate the final load path, tab-head clearance or screw engagement.

Do not back-drive a powered servo or use a coupon for stall testing. If body
clearance needs tuning, regenerate just the coupon with revised ServoFitClearance;
do not apply a guessed global shrink scale to the complete assembly.

## Gate to the next print

Resolve the installed mating-face/tab datums, tab retention and horn attachment
screws before releasing the complete pedestal, rotor and right fork. Any resulting
geometry change needs CAD/export/motion revalidation. The first-fit adapter may
be reused only if its dimensions remain correct and it is undamaged.

Then bench-fit the supported journal and passive pivot before attaching a camera.
Follow MEASURE_AND_BUILD.md for assembly, unpowered travel, dummy load and slow,
limited-range powered testing. Coupon success is not strength, endurance, thermal
or complete motion validation. Preserve the base,140 mm target,250 g ballast plan
and owner-drilled blank4 mm camera plate.
