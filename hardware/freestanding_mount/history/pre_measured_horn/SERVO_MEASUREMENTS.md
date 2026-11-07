# Exact measurement worksheet — supplied MG90S accessories

Label selected horns P (pan) and T (tilt); measure both servos and both horns.
Record values in mm at the instrument's readable precision. Do not read exact
dimensions from the bag photograph. Leave unknown fields unfilled in CAD.

## Horns P and T

Define U along one selected arm, V perpendicular in the horn plane, with origin
at the spline/shaft centre. Record signs. Pan U maps to rotor X; tilt U maps to
local Z. These orientations refer to the neutral assembly.

| Measurement to record | Method / purpose | Current provisional CAD |
|---|---|---|
| Intended hole centres (U,V), each hole | Measure from the shaft centre, not from an adjacent hole; record at least two usable points | (+8,0), (-8,0) |
| Each intended hole diameter | Bore diameter; distinguish a tapered pilot from a clearance hole | 2.3 mm printed clearance; stock hole unknown |
| Full outline | Centre-to-tip distance for every arm; arm widths and any offset; include transverse arms | Circular reference envelope radius 11 mm |
| Thickness at each attachment hole | Both fastening lands, not just tallest hub | 2 mm assumed horn thickness |
| Hub diameter on both faces | Record spline-side and outer bosses separately | No fitted hub recess specified |
| Hub projection/recess on both faces | Relative to flat arm mating plane | Flat printed mating surface; 7 mm centre access |
| Installed mating-face height | Seat matching horn on unpowered servo; measure from tab's actual mounting-contact face to the face that meets the printed part | Must agree with full axial stack, not just nominal shaft projection |

Pan outline must fit the 30 mm inside journal diameter with clearance. Tilt outline
must clear the fork and fasteners throughout travel; the nominal opening is 28 mm.
Check the actual fastener-head/washer footprints as well as the plastic outline.
Do not shorten or re-drill a supplied horn to satisfy an unverified CAD dimension.

## Servo A and servo B

Choose one body corner and the tab's mounting-contact face as datums. State which
faces were used; the shaft is not presumed centred on the body.

| Measurement to record | Purpose / current assumption |
|---|---|
| Body long dimension, width and height, including protrusions | Coupon aperture currently 23.4 x12.8 mm; seller body 22.8 x12.2 x28.5 mm |
| Tab-hole centre spacing and each centre's two in-plane offsets | Current 28 mm pitch and symmetry are assumptions |
| Each tab hole diameter; tab thickness, width, length and corner shape | Current 2.3 mm hole, 2 mm thickness and 6 mm end-tab envelope are provisional |
| Shaft centre from chosen corner in both in-plane directions | Also record body dimensions to calculate signed centre offsets |
| Signed shaft-to-body-centre offsets | CAD shaft is -5.3 mm along body long direction and zero across; do not lose the sign |
| Mounting-contact face to case top, shaft end and seated horn mating plane | Checks pan shelf/journal clearance, washer stack and tilt alignment |
| Cable exit position and connector clearance | Ensures insertion/removal without trapping the lead |

## Every screw type, kept separate

Record **count; under-head length; major thread diameter; pitch if measurable;
head diameter and height; drive type; pointed/blunt tip; machine/coarse thread**.
For countersunk screws also record head angle if known and state whether the
reported length includes the head. Do not identify a thread by forcing a nut on it.

Allocate each type only after confirming its function:

- Servo-centre retention: matching supplied screw; confirm head seating and usable
  engagement without bottoming in the shaft.
- Tab mounting: verify intended fastening method. A supplied coarse screw does
  not establish that an M2 nut or a printed clearance hole will work with it.
- Horn-to-print attachment: required grip is 7 mm pan / 6 mm tilt plus actual
  horn, washers and nut or plastic engagement. Measure engagement and exposed tip;
  confirm clearance to the servo case, journal, centre screw and adjacent fasteners.

## Blank camera plate

Keep `CameraHoleEnabled=false` and the 4 mm plate thickness. Before drilling, record
the actual insert X/Y relative to plate centre, thread diameter/pitch/usable depth,
and underside screw-head/washer footprint. Verify it fits the centred 24 x20 mm
cradle opening; detailed inequalities and drilling instructions are in
SERVO_ACCESSORY_REVIEW.md. The 1/4-20 parameter is not a confirmed thread.

## Decision after measurement

If pattern, seating, grip, outline and axial stack match, retain the current CAD.
If a mismatch is found, change only the relevant horn/servo interface; retain the
base, architecture and camera-height target. Generate an appropriate interface
coupon and rerun CAD/export/motion validation for geometry changes. The existing
servo-body coupon alone cannot validate a horn or fastener stack.
