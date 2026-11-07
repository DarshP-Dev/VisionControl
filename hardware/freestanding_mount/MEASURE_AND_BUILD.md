# Measurement, printing and assembly plan

Updated 2026-11-07: current fit-revision outputs are in `output_measured_fit/`; read
`CAD_VALIDATION.md` for executed checks and the current resin/mass comparison.
CAD checks have passed within their stated scope; physical fit and load checks remain.
The34 mm installed highest-point measurement conflicts with the35.5 mm modeled wing
mating-face datum. Resolve the axial stack before printing the full mount; start
with the three small parts in FIRST_PRINT.md.

The servos have arrived with plastic horns and mounting screws. Use those horns;
read [SERVO_ACCESSORY_REVIEW.md](SERVO_ACCESSORY_REVIEW.md) before selecting screws
or changing an interface. The reattached accessory photo has been inspected;
exact fit remains pending the worksheet in SERVO_MEASUREMENTS.md.
Supplied tab screws, horn-centre screws and horn-attachment screws are different
functions; do not assume all are included or interchangeable.

## Measure first

Use calipers, a thread gauge and actual hardware; record units and uncertainty.
Do not infer the insert from photographs or force a guessed screw.

| Interface | Measurements required | Parameters / consequence |
|---|---|---|
| Camera insert | major diameter, pitch, usable depth, entry chamfer, whether blind | CameraThreadMajor/Pitch; screw selection; CameraHoleEnabled |
| Insert position | X/Y from folded mounting footprint centre | CameraInsertX/Y; verify cradle access opening still aligns |
| Camera | folded height/width/depth; padded contact footprint; optical centre XYZ | camera envelope and optical height; plate screw head clearance |
| Balance | camera COM with chosen clip position and cable supported | CameraComY/Z; pivot height and fore/aft alignment |
| Clip | open/closed swept volume and hinge access | remove plate for articulation if needed; no hinge modification |
| Each servo | body, tabs, tab underside datum, thickness, hole diameter and spacing | ServoWidth/Depth/Height, ServoTabPitch/Hole/Thickness |
| Servo shaft | shaft-axis offset in both mounting-plane directions; projection to horn face | ServoShaftOffset/Projection; modify geometry if second-axis offset nonzero |
| Horns | Actual full outline, pilot diameters and hub projections; verify measured2 mm wing,6 mm hub and14.5 mm outer radius on both horns | HornRadius18 is a budget; HoleDiameter2.3 is printed clearance only |
| Centre screws | actual thread and usable engagement | original matching screws only; no guessed M-size |
| Passive support | bushing OD/ID/length; shoulder length; washers; end play | bushing and pivot settings; shaft stack must not clamp rotating parts |
| Cable | jacket diameter, natural bend radius, force over the entire sweep | cable loop and torque calculations |
| Resin | cured coupon dimensions, flatness and hole size with selected exposure | adjust clearance; do not apply a guessed uniform shrink percentage |

The simplified servo model assumes symmetric tabs, their holes in one line,
and a shaft offset in one plane direction. If the actual horn/tab pattern is
asymmetric, edit the point lists in `mount_geometry.py`; do not force symmetry
onto incompatible hardware. The two opposed outer attachments are a design selection; confirm their29 mm span on each actual horn.
`ServoTabThickness` and `ServoTabEndWidth` now define provisional tab envelopes.
Their exact geometry and hole compatibility remain unmeasured.

## Fit coupon before assembly parts

Print the three parts in **FIRST_PRINT.md**: ServoFitCoupon, PanHornCoupon and
TiltHornAdapter, from output_measured_fit/stl. The existing body coupon is unchanged;
the added pan core and real tilt adapter check the measured outer-hole interfaces,
hub/outline fit and recessed screw/driver access. This set totals21.07 ml solid,
approximately26–31 ml including a rough support/waste allowance.

Measure both servos and both horns after full cure. No single coupon validates
all shaft/tab datums or the final load path. Record B-to-M and T-to-M explicitly;
34 mm to the highest installed point is not a substitute. Do not force hardware
or self-tap resin. Use FIRST_PRINT_RESULTS.md to record passes and unresolved items.

## Print preparation

Use the original Photon Mono X192 Ã—120 Ã—245 mm volume. The largest rotor isÃ˜116,
leaving only4 mm total on the120 mm axis when horizontal: its raft/support envelope
will probably require tilting. The generator's fit flag is bare-part orientation
only. Confirm the complete supported bounding box in the slicer for every job.

| Part | Starting orientation | Support / surface priorities |
|---|---|---|
| Base | tilt20â€“30Â° along long axis | support underside/rim; avoid feet and mounting surfaces; keep ballast pockets drainable |
| Cover | tilt25â€“35Â° | support edges and underside; check flatness before clamping |
| Pedestal | lean25â€“35Â° | support posts and shelf islands; preserve top bearing plane and accessible openings |
| Pan rotor | tilt25â€“35Â° | supports on underside outside journal/horn interfaces; no marks on thrust face |
| Forks | lean30â€“45Â° | support feet and rear edges; avoid bushing bore and servo mating faces |
| Cradle | lean30Â° | support underside and sidewall roots; preserve plate contact face |
| Camera plate | lean25â€“35Â° | supports underneath, never on the padded-camera contact plane |
| Horn adapter | tilt30Â° | support perimeter; preserve both flat mating faces and holes |
| Cable saddle/coupon | tilt20â€“30Â° | support underside; preserve test aperture edges |

These are slicer starting points, not a tested support recipe. Inspect every layer
for islands and suction cups. The open pockets and frame do not need hidden hollow
resin chambers; orient open faces so they drain and can be fully washed/cured.
Use the resin manufacturer's handling, ventilation, PPE, wash and cure guidance.
Keep uncured resin and wash waste out of drains. Do not copy exposure times from
a different printer/resin. Calibrate the actual Mono X with this bottle, temperature
and layer height. Post-cure before judging fit, load or flatness. Avoid a press fit,
threaded resin fasteners, over-tightened countersinks and solvent-trapping pockets.

Weigh cured parts. Review the calculated torque with actual tilt assembly mass
and balance. Use slicer resin volume and actual support weight to replace the rough
327â€“380 ml allowance including one coupon. Large flat sections may warp; reject
bearing faces that rock. No further resin optimization is planned for the confirmed
1 litre purchase.

## Assembly sequence

1. Execute the FreeCAD script. Open the FCStd and each representative STEP/STL;
   inspect the geometry audit and full travel. Resolve every unintended intersection,
   disconnected solid, failed mesh and inaccessible fastener before printing finals.
2. Print/cure the three first-fit parts from FIRST_PRINT.md; verify both servos. Measure
   the supplied horns and screws; update only interfaces that need it and rerun CAD
   validation if geometry changes. Resolve the axial height discrepancy before full printing. Keep the camera clearance hole disabled for owner
   drilling; check its intended location against the cradle access opening first.
3. Install base captive nuts from the open pockets. Fit the measured pan servo into
   the pedestal shelf; secure its tabs with matched screws/washers without bending tabs.
   Attach pedestal to base. Confirm flange fasteners can be reached and do not hit ballast.
4. Centre the servo using a suitable standalone tester and the manufacturer's
   procedure, unloaded; remove power before fitting the horn. Do not force a powered
   shaft or assume its advertised180Â° corresponds to any particular pulse range.
5. Prefer the supplied straight double-arm horn for pan if its measured hole pair,
   full outline and hub seating fit. Orient the opposed pair along rotor X at neutral.
   Use the revised ID44.5/OD50/2 mm PTFE washer only after axial verification.
   Install washer, horn and rotor. BEFORE installing the blank camera plate or camera, fit the horn centre screw
   through the rotor access hole and verified horn bolts. Confirm gravity load rests
   on the washer, not on the servo shaft; tune washer/adapter stack before proceeding.
6. Prefer a supplied straight double-arm horn for tilt, with its opposed pair along
   local Z at neutral; keep the separate M3 fasteners along local Y accessible. If
   considering a cross horn, check its unused arms against those fasteners and the
   fork throughout travel. Bolt the forks to the rotor, add the right servo and its
   matching stock horn, and attach
   the cradle through the adapter. Fit horn attachment screws into the rear5.5 x2.2 mm
   recesses before mating the adapter to the cradle; heads must stay below flush.
   Preserve the checked M3x14 /0.5 mm washer stack and verify actual tail clearance.
   Install the passive shoulder pivot/bushing/washer
   stack. Set slight free axial play without squeezing the cradle. Check that no nut
   or bolt tail enters the rotating envelope and that horn screws are accessible.
7. Remove the blank plate and follow the drilling/access guidance in
   SERVO_ACCESSORY_REVIEW.md. Mount the camera with the **verified** screw and washer/pad.
   Select under-head length from plate+pad+washer thickness plus required engagement,
   leaving clearance to the bottom of the measured blind insert. Do not bottom out.
   Secure the plate's four flush fasteners; verify all heads clear the actual clip.
8. Add measured, restrained ballast, then fit the cover and feet. Nothing may project
   below the feet. Reweigh assembly, confirm COM and rerun tipping calculation.
9. Fit the USB cable with a loose loop between camera and rotor saddle, then a second
   slack span between rotor and desk anchor. Begin withâ‰¥30 mm bend radius and~150â€“200 mm
   free loop length as provisional routing space, not a cable manufacturer rating.
   Keep loops away from horns/pivots and lens. The saddle's two bolts retain it; use
   a soft strap around the saddle body, loose enough not to pinch the jacket.
10. Inspect unpowered movement with horns disconnected from servo drive if necessary.
    Do not back-drive a geared servo forcibly. Reconnect at known neutral only.

## Separate 5V supply and Pico PWM — future bench connection

Use a separate regulated5V servo supply sized for both servos' actual startup and
load current, with suitable distribution wiring and a reachable power disconnect.
Connect supply negative, both servo grounds and Pico GND to a shared reference.
Power the Pico by its intended USB arrangement for this bench setup; do not tie
positive rails together without a separately checked power design. Servo motor
power must not come from GPIO or Pico3V3.

Route two assigned Pico PWM outputs to the two servo signal inputs. Pico GPIO is
3.3V logic; verify these particular servos accept that signal level and confirm
connector polarity rather than trusting colour alone. Never apply5V to a Pico
GPIO. The official [Pico datasheet](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf)
and [PWM API documentation](https://www.raspberrypi.com/documentation/pico-sdk/hardware.html#hardware_pwm)
cover Pico logic/pin functions; they do not establish the Miuzei input threshold
or safe pulse endpoints. Verify those separately, starting unloaded at neutral.
No PWM code, live movement or new control integration is introduced here.

## Mechanical and travel acceptance

- Use a dummy96 g load before the real camera. Start with gentle support under the
  assembly. Check static deflection, loose hardware, resin cracks and bearing friction.
- With power removed, verify assembly at small increments throughout both-axis travel;
  endpoint-only checks can miss intermediate contact. Inspect screw tails and cable
  loops at combinedÂ±60/Â±35 corners, but stop short of any contact.
- Set initial **test** software limits toÂ±10Â° with slow motion (e.g.5Â°/s and10Â°/sÂ²),
  not the final targets. Establish centre and angle mapping separately for each
  purchased servo with an external tester or a future independently reviewed driver.
  No servo pulses or driver are provided by this CAD package.
- Increase one axis at a time in5Â° increments while watching current, temperature,
  cable pull and geometry. Record first contact/tension/binding boundaries; set
  working endpoints at least5Â° inside observed boundaries, with more margin for
  backlash/flex. Use the tighter of actual servo, mechanical, cable and desired limits.
  A software number is not a physical stop or an emergency disconnect.
- Keep a reachable servo-power disconnect. Stop on buzzing, rising current, heat,
  visible flex or stall. Never use prolonged stall as a torque test. Test a realistic
  duty cycle and let the servo cool; compare to actual manufacturer limits when available.
- At every pan direction and extreme tilt, apply measured small horizontal loads with
  a force gauge at the cable exit. Confirm no foot lifts or slips at the modeled0.5 N
  load and that the cable anchor intercepts larger pulls. Do not push to overturn near
  the camera. Increase base footprint/ballast when measured margin is insufficient.
- Record optical height at neutral and minimum across tilt; minimum must remainâ‰¥101.6 mm.
  Recheck after fastening the actual folding foot and pad. Record cable force, backlash,
  travel, mass, tip/sliding behaviour and any permanent deformation after a soak test.

Until these steps pass, the model is a preliminary fit/assembly design, not an
approved final printable mount. The software's prior simulated-motor arming state
does not authorize a physical servo connection.
