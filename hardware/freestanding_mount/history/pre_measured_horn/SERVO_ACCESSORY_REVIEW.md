# Supplied servo accessories — photo inspected; measured fit pending

User confirmation, 2026-11-07: the two Miuzei MG90S servos have arrived with
**plastic horns and mounting screws**. Use those horns as the spline connections;
adapt the printed interfaces to the selected horns. No replacement horn or printed
spline is specified. The reattached `ChatGPT Image Nov 7, 2026, 03_31_23 PM.jpg`
was inspected. It shows one labelled servo and overlapping accessories in a bag.
Bag glare/overlap prevents an exact inventory; there is no usable measurement scale.
Earlier webcam photographs were not used to infer servo dimensions.

## Photo findings and horn selection

- A **straight double-arm horn** crosses the upper/middle of the bag, with a central
  hub and hole rows extending in opposite directions. This is clearly visible.
- A **cross/four-arm horn** is visible at lower right, with a long opposing pair and
  shorter transverse arms. Part of its outline is obscured; equal arm lengths or
  equal hole radii must not be assumed.
- An **apparent single-arm horn** sits partly behind the others at upper left.
  The hub and extending arm are visible; confirm its complete outline with the
  pieces separated. This is less certain than the double-arm and cross identification.
- Several silver screws show cross-recess heads and pointed/coarse-threaded shanks,
  consistent with mounting/self-tapping screws. A shorter, apparently blunt-ended
  screw in the lower cluster is a candidate centre-retention screw. Exact count,
  thread size and intended function cannot be certified through the overlapping bag.
  Separate nuts/washers are not clearly visible; this does not prove they are absent.

**Preferred for the current CAD: a supplied straight double-arm horn on both axes**,
if each purchased servo's kit includes one. This is an engineering recommendation
based on the existing two opposed fastening points, not dimensional proof of fit.

| Axis | Selection and orientation | Reason / condition |
|---|---|---|
| Pan | Straight double-arm; opposed holes along rotor X at neutral | Fits the intended two-hole layout without unused transverse arms; full outline must clear the journal |
| Tilt | Straight double-arm from the other kit; opposed holes along local Z at neutral | Leaves the separate cradle fasteners along local Y more accessible |

The cross horn is a conditional alternative for pan if its opposed holes and entire
outline fit. It offers no automatic four-fastener benefit: the current rotor has
two horn-attachment holes. If there is only one double-arm across both kits, reserve
it for tilt and assess the cross for pan after measuring. The apparent single-arm
horn is not the first choice for the current opposed-hole pattern. Keep the stock
horns intact; adjust a printed interface if measurements require it.

## Compatibility findings

1. Current horn holes are **two opposed points at radius 8 mm** (16 mm separation),
   diameter 2.3 mm. Visible rows of holes do not prove that a matching pair exists.
2. The **pan journal has a 30 mm inside diameter** at the horn. Every tip/edge needs
   positive clearance inside radius 15 mm, including fit allowance. The reference
   horn disk is only radius 11 mm; it does not validate the visible long arms.
3. The **tilt fork has a nominal 28 mm opening** around the horn. Containing the
   entire horn within radius 14 mm with clearance is a conservative fit check.
   Longer/irregular arms need an explicit outline check through +/-35 degrees.
4. Tilt horn holes lie at local Y0/Z+/-8 mm. The separate M3 cradle holes lie at
   Y+/-9/Z0 mm. A cross horn's unused arms could cover those heads/nuts or the driver
   route. The recommended double-arm orientation reduces this risk; its hub must
   also be checked.
5. The flat printed faces may not seat over a projecting plastic hub. The **7 mm
   centre access opening is not a measured hub recess**. Measure both horn faces.
6. **Pan grip is 7 mm; tilt grip is 6 mm**, before adding horn/washer thickness.
   Supplied short screws may not provide suitable engagement. Pointed coarse
   screws cannot be presumed compatible with M2 nuts or resin clearance holes.
7. Tab pattern, installed-horn height and shaft offsets remain unmeasured. A height
   mismatch can preload the pan servo or bind the opposite tilt support.

The accessory styles support the existing architectural approach. **No specific
dimensional incompatibility is established by the photo**, so the CAD is preserved.
This is not confirmation of exact fit. If the listed checks pass, no redesign is
needed; otherwise change only the measured local interface and rerun validation.

This review changes documentation and the BOM only. The existing architecture,
base, target 140 mm optical height and resin geometry remain unchanged. The camera
mounting hole stays disabled for owner drilling. No new CAD sweep was necessary;
the earlier kernel checks apply to the unchanged provisional model, not a measured
fit with the newly arrived accessories. Physical compatibility remains pending.

## What the current interface requires

| Interface | Existing CAD assumption | Required physical check |
|---|---|---|
| Stock horn selection | One straight double-arm per axis preferred | Confirm the other kit includes one; inspect both faces and measure the selected pair |
| Attachment-hole pattern | Two opposed holes, radius 8 mm from shaft centre (16 mm separation) | Measure X/Y coordinates of each usable hole from the hub centre; do not substitute an adjacent-hole pitch for the radius |
| Hole diameter | 2.3 mm clearance in printed parts | Measure stock-hole diameter and intended screw shank/thread; these are not verified M2 holes |
| Horn outline | Circular reference envelope, radius 11 mm | Measure full arm length, width and asymmetric outline; the reference disk is not a reproduction of the supplied horn |
| Horn axial fit | Nominal 2 mm thickness against a flat printed mating face | Measure thickness at selected holes and hub projection on both faces; check whether the hub needs a printed relief |
| Centre screw access | 7 mm access diameter | Identify the actual supplied centre screw; check head/driver clearance and seating depth |
| Pan attachment | 4 mm rotor + 3 mm hub = 7 mm printed grip | Check supplied screw reach through the printed grip plus actual horn/washer stack; ensure clearance to the servo case and journal |
| Tilt attachment | 6 mm printed adapter | Check supplied screw reach and protrusion; prevent contact with the flange, servo or centre screw |
| Servo tabs | 28 mm hole pitch; 2.3 mm holes; nominal 2 mm thickness | Measure each unit's tab outline, thickness, hole positions and edge distances |
| Servo body coupon | 23.4 × 12.8 mm aperture | Measure actual body where it passes through the mounting plate; confirm connector/wire access |
| Shaft position | 5.3 mm offset in one mounting-plane direction; other offset assumed zero | Measure shaft centre in both directions relative to the body/tab datums |
| Shaft/horn height | Nominal 5 mm shaft projection | Measure the installed horn mating face from the servo mounting datum; verify the thrust-washer and tilt-axis stacks |

`HornHoleRadius`, `HornHoleCount`, `HornHoleDiameter`, `HornRadius`,
`HornThickness`, `ServoTabPitch`, `ServoTabHole`, `ServoTabThickness`,
`ServoTabEndWidth`, `ServoShaftOffset`, `ServoShaftProjection` and fit clearances
remain provisional parameters. They have not been replaced with guesses from a photo.

The current hole generator describes an equally spaced circular pattern. A single-arm
horn with two holes along one arm, an asymmetric cross, or unequal hole radii needs
explicit measured hole coordinates in the printed interface. Changing a radius alone
cannot represent those patterns. Choose the actual horn first; then update only the
affected printed interface and validate its swept outline. Preserve the supplied
horn rather than drilling it to match the current CAD. The visible double-arm and
cross styles offer candidate opposed pairs; their radii are still unmeasured.

## Sort the included screws by function

Keep each servo's accessories together. Presence of mounting screws does not establish
that every fastener required by this assembly is supplied.

1. **Horn centre retention:** use the matching supplied centre screw once identified.
   Record under-head length, head diameter and thread; do not substitute a tab screw.
2. **Servo tab attachment:** identify which supplied screws are intended for tabs and
   measure their diameter, length and thread form. They may not be machine screws
   suitable for M2 nuts. Do not force a coarse/self-tapping screw into the existing
   resin clearance holes or invent a compatible nut size.
3. **Horn-to-printed-part attachment:** check whether any included screws are suitable
   and long enough. The BOM's M2 × 12 entries are conditional candidates, not verified
   supplied hardware. Do not assume the servo's centre screw can perform this job.

For a machine screw and nut, required under-head length includes printed grip,
actual horn thickness, washers and full nut engagement; any exposed tip must clear
the mechanism. For a screw intended to engage a plastic horn, measure the remaining
engagement after the printed grip and washer: it must suit the stock horn and must
not bottom, split it or protrude into the servo. Obtain the intended engagement from
the accessory design/manufacturer rather than choosing an arbitrary turn count.
If the included screws are too short, resolve fastener length or the printed seat
after measurement; do not thin a loaded adapter or countersink it speculatively.

The thrust washer carries pan weight; the horn transmits torque and retains the
rotor. Confirm that the fitted stock horn does not preload the servo shaft axially.
On tilt, the opposite pivot remains essential; tightening horn screws must not pull
the cradle sideways or bind the passive support.

## Existing fit coupon

Use `output_verified/stl/ServoFitCoupon.stl` for the initial body/tab check. No new
measurements presently justify a different coupon, so it has not been regenerated
or relabelled as matched to the purchased unit. Its aperture is 23.4 × 12.8 mm,
tab-hole pitch 28 mm and holes 2.3 mm. Do not force an actual servo into it.
It cannot validate horn geometry, shaft height or the complete screw stack.

Once dimensions are supplied, update the affected parameters and generate a fresh
coupon/output directory. If a horn pattern or hub relief changes, add a small test
piece reproducing that actual printed interface before committing to the assembly
print. Rerun the CAD checks for every changed geometry.

## Blank camera plate and drilling later

The existing plate is 90 × 52 × 4 mm, removable with four M3 fasteners at
X ±34 / Y ±18 mm. The centre remains solid: `CameraHoleEnabled=false`.
Keeping the full 4 mm thickness and the existing cradle support is appropriate
for this preliminary drilling plan; no extra lightening has been added. Actual
drilled-part strength still requires a fit/load check after curing and assembly.

The cradle below it has a **24 × 20 mm centred access opening**. Before drilling,
mark the real insert location with the camera in its intended centred pose. Ensure
the complete underside screw-head/washer footprint fits inside that opening;
otherwise it may prevent the plate seating on the cradle. For a circular footprint
of diameter D, its centre must satisfy `abs(X) + D/2 < 12` and
`abs(Y) + D/2 < 10` mm, with additional practical clearance. X/Y are measured from
the plate centre. For example, a 12 mm footprint allows less than ±6 mm X and
±4 mm Y before adding that clearance. This is a geometric access limit, not a
recommendation to purchase a 12 mm washer.

If the measured insert requires a location outside that usable region, stop and
adjust the printed access geometry before printing the full cradle; shifting the
camera also changes balance and motion clearance. Remove the plate for marking and
drilling, support it flat on sacrificial backing, clamp it without bending it and
drill without the camera attached. Use controlled light feed, avoid overheating
or aggressive countersinking, deburr gently and reject cracking/chipping. Preserve
the four existing fastener lands and enough surrounding material for the actual
head/washer. Do not use a screw's threads to cut a hole through cured resin.

Select the camera screw only after confirming the insert diameter, pitch and usable
depth. The 1/4-20 CAD value remains an unused candidate. Account for the 4 mm plate,
pad/washer thickness and required engagement without bottoming in the insert. Check
that the plate seats flat and the folding mechanism remains free before load testing.

## Measurements to send next

- The attached photo has been reviewed. A separated front/back view would resolve
  the obscured horn outline and screw inventory. For exact dimensions, use the
  datum-based worksheet in [SERVO_MEASUREMENTS.md](SERVO_MEASUREMENTS.md).
- For each selected horn: overall outline, two or more hole-centre coordinates from
  the shaft centre, hole diameter, thickness and hub projection on both sides.
- For each servo: tab-hole pitch/offsets/diameter, tab thickness, and shaft-centre X/Y
  plus installed-horn mating-face height relative to the mounting datum.
- For each screw type: quantity, head diameter, under-head length, thread diameter
  and whether it is a machine or self-tapping thread; thread pitch if measurable.
- For the manual camera mounting: planned insert location and underside head/washer
  footprint, so the access opening and balance can be checked before final printing.

The confirmed 1 litre resin purchase does not require further weight optimization.
Keep the current base and architecture; prioritize accessory fit and practical assembly.
