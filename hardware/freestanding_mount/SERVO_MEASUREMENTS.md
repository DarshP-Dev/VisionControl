# Measurement worksheet — measured-horn revision

Measure servo A/B and horn P/T separately in mm; record instrument resolution and
repeated readings. The photograph is not a dimensional reference. See also
measurement_status.json for parameter provenance.

Recorded approximate owner values: body22.8 x12.2 x28.5; wing2; hubOD6; inner-hole
radius4.5; outer-hole radius14.5; body-bottom to highest installed horn point34 mm.
These are NOT hole diameters or tab-based heights.

## Required before full assembly print

| Record for EACH servo/horn | Exact datum or method | CAD consequence |
|---|---|---|
| B-to-C body height |Same body bottom B to case top C, excluding shaft/horn|Reconcile28.5 mm body datum|
| B-to-M and T-to-M |M = flat wing face contacting print; T = actual tab mounting contact face; horn fully seated|Resolve35.5 mm model vs34 mm highest-point conflict|
| B-to-H with/without centre screw |Identify H as wing, hub or head; include side sketch|Do not substitute H for M|
| Hub dimensions BOTH faces |ODs and signed projections relative to M|7 mm access,0.5 mm radial budget to6 mm boss|
| Each outer-hole coordinate |Spline centre origin; U along arm, V transverse; signed(U,V) and full span|Candidate(+14.5,0),(-14.5,0);29 mm span|
| Each selected bore |Diameter, taper, straight/pilot depth|2.3 mm printed clearance is not horn bore size|
| Full horn outline |Centre-to-tip every arm, widths, thickness at each fastening land|Must fit radius18 budget; pan cavityID37|
| Tab-hole centres |X/Y from named body corner; spacing and symmetry|28 mm pitch, zero transverse offset unverified|
| Tabs |Hole diameter, thickness, width, length, radii, contact height|2.3 /2 /6 mm provisional dimensions|
| Shaft position |Two in-plane offsets from same body corner, plus body dimensions|Current axis=body centre minus5.3 along long dimension, zero across|
| Case/cable protrusions |Insertion and connector-removal envelope|Body coupon alone does not validate final routing|
| Every screw type |Count, thread major diameter/pitch/type, under-head length, headOD/height, drive and tip|Keep centre/tab/horn-attachment roles separate|
| Joint engagement |Depth before bottoming, actual grip, washer/nut stack, exposed tip|Pan grip7; tilt3.8 mm; no invented screw length|

Pan U maps to rotor X; tilt U maps to local Z at neutral. If centres are asymmetric,
use measured point coordinates in the generator, not a forced radial pair.

## Physical acceptance measurements

- Cured coupon aperture, holes and flatness; journalOD43.5 /bore44, washer thickness.
- BushingOD/ID/length and shoulder-bolt/washer/end-play stack. Current5 mm pivot,
  8 mm OD bushing and8 mm length remain procurement assumptions.
- Actual optical centre, folded camera footprint, supported-cable COM and masses.
- Owner's camera thread, pitch, usable blind depth, insert position and screw/head
  access through24 x20 cradle opening. Keep camera plate blank4 mm until drilling.
- Cable force through travel, friction, backlash, resin deflection, thermal
  behaviour and tip/slip margin; CAD cannot supply these measurements.

Log results in FIRST_PRINT_RESULTS.md. Unknown means unverified, not passed.
