# Horn-hole positional correction — 2026-11-16

Current output: **output_fit_offset_2026_11_16/**. Previous output_measured_fit and
all earlier exports are preserved. No commit or push.

## Physical evidence and direction

Owner confirms ServoFitCoupon passed, with acceptable minor play once fastened.
Both horns fit; BOTH PRINTED holes on each horn part are approximately0.1 mm too
high when the hub is centred and the two holes are held horizontally with the
horn-contact face toward the observer. This establishes a common translation
perpendicular to the line between the holes, preserving spacing.

The horn-contact side of PanRotor/PanHornCoupon is the underside (outward normal
-Z); put the +X hole on the right. Screen right=+X, screen down=+Y.
In the full pan rotor this puts the cable saddle (negativeY) toward screen TOP.
The tilt horn-contact side is the nose (outward normal+X); put the +Z hole on the
right. Screen right=+Z, screen down=+Y. The cradle-facing screw recesses are on the
opposite face. This is a rotated contact-face view, not installed world-down-Z.

Both frames satisfy right cross up = outward normal. Consequently **+0.1 mm Y**
is downward in the documented contact views for both parts. Moving tilt holes
alongZ would move them along their horizontal pair in this view and is incorrect.

**Physical orientation assumption:** an unmarked coupon can be turned180 degrees;
the owner did not identify which arm tip was on the right. The coordinate mapping
above is defined and mathematically checked, but its absolute sign relative to
the owner's original handling is not independently measured. Test with these
orientations. If error doubles, check orientation/sign before changing diameters
or spacing. No automatic claim of corrected physical alignment is made.

## Before and after — mm, neutral assembly coordinates

| Component / hole | Before | After |
|---|---|---|
| PanRotor and PanHornCoupon, -X hole |(X,Y)=(-14.5,0)|(-14.5,+0.1)|
| PanRotor and PanHornCoupon, +X hole |(X,Y)=(+14.5,0)|(+14.5,+0.1)|
| TiltHornAdapter, -Z hole |(Y,Z)=(0,113.5)|(+0.1,113.5)|
| TiltHornAdapter, +Z hole |(Y,Z)=(0,142.5)|(+0.1,142.5)|

All four bores remain diameter2.3 mm; each pair remains29.0 mm apart.
Pan bores run alongZ; tilt bores run alongX. Through-axis depth coordinates do not
set the in-plane alignment. STL/STEP exports translate each neutral part to a
positive-coordinate bounding box without rotating it:

| Export | Previous centres | Corrected centres |
|---|---|---|
| PanHornCoupon XY |(7.25,21.75),(36.25,21.75)|(7.25,21.85),(36.25,21.85)|
| PanRotor XY |(43.5,58),(72.5,58)|(43.5,58.1),(72.5,58.1)|
| TiltHornAdapter YZ |(20,5.5),(20,34.5)|(20.1,5.5),(20.1,34.5)|

PanHornOffsetY=0.1 and TiltHornOffsetY=0.1 are separate editable parameters, default
zero for old documents that lack them. HornHoleRadius stays14.5. Tilt bore offsets
are applied separately from recess coordinates, so both5.5 mm diameter x2.2 mm
deep recesses stay at(Y,Z)=(0,113.5),(0,142.5). Their axes are now0.1 mm eccentric
to the bores, deliberately matching the request to keep recesses unchanged.

## Executed validation and limits

FreeCAD1.1.4 generated the full editable assembly and STL/STEP exports. The new
verify_fit_offset.py checks actual cylindrical faces and Boolean differences:
only PanRotor, PanHornCoupon and TiltHornAdapter change; zero changed material
exists outside the union of the old/new bore volumes. All other printed and
reference shapes are unchanged. Changed solids retain their volumes within
numerical tolerance. Bore diameter/centres/spacing and fixed recess centres pass.

The main375-pose sweep across pan±60/tilt±35 found zero modeled intersections.
verify_exports.py checks all12 STL/STEP pairs and reopens/recomputes both FCStd
files. verify_interfaces.py uses shifted screw-head centres and the corrected
hypotenuse radius for continuous tilt head sweeps, with original recesses.
See the JSON reports in the new output directory for actual results.

The pan hub outer-edge ligament changes3.350000 ->3.349655 mm; tilt nose ligament
2.350000 ->2.349655 mm. This0.000345 mm reduction follows from the perpendicular
translation. The2.75 mm recess-to-outer-edge ligament and3.8 mm axial grip stay
unchanged. Assumed4.5 mm head clearance inside the fixed5.5 mm recess reduces
from0.5 to0.4 mm on the tight side. No new interference was detected for that
hardware budget. Actual screw-head seating, resin strength and alignment require
physical checking; these geometric results are not a strength certification.

## Repeat fit procedure

Print ONLY the revised PanHornCoupon and TiltHornAdapter at100% scale in mm,
using the same calibrated exposure/orientation/cure as the successful tests.
The passed ServoFitCoupon needs no reprint. Keep old/new coupons distinguishable
with a removable label after cure; no labels or fiducials were added to geometry.
Use the contact-face orientation above, centre the horn without forcing it, and
check both holes simultaneously with locating pins/appropriate screws. Confirm
flat horn seating, free centre access and below-flush tilt attachment heads.
Try the actual heads in the now-eccentric recesses; reject rocking or edge contact.
Record whether the0.1 mm discrepancy disappears. If it persists, record each hole's
signed error in this view and verify print dimensions before further correction.

Only after this repeat fit should full PanRotor/TiltHornAdapter production copies
be used. Earlier unresolved installed horn/tab axial datums remain a separate
full-assembly condition. This feedback does not supply those measurements.

## Reproduce

Use README.md generation commands with a fresh directory, then run:

```powershell
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' hardware/freestanding_mount/verify_fit_offset.py hardware/freestanding_mount/output_fit_offset_2026_11_16
```

This verifier needs history/pre_fit_offset/parameters.json, included in the package.
