# Measurement, printing and assembly plan

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
| Horns | actual outline, thickness, bore, available bolt holes, radius, hole diameter | HornRadius/Thickness/HoleRadius/HoleDiameter/Count |
| Centre screws | actual thread and usable engagement | original matching screws only; no guessed M-size |
| Passive support | bushing OD/ID/length; shoulder length; washers; end play | bushing and pivot settings; shaft stack must not clamp rotating parts |
| Cable | jacket diameter, natural bend radius, force over the entire sweep | cable loop and torque calculations |
| Resin | cured coupon dimensions, flatness and hole size with selected exposure | adjust clearance; do not apply a guessed uniform shrink percentage |

The simplified servo model assumes symmetric tabs, their holes in one line,
and a shaft offset in one plane direction. If the actual horn/tab pattern is
asymmetric, edit the point lists in `mount_geometry.py`; do not force symmetry
onto incompatible hardware. The candidate horn count2 is not a purchased-unit fact.
`ServoTabThickness` is a recorded assembly input; tab envelopes are not modeled.

## Fit coupon before assembly parts

Run the generator in FreeCAD and inspect `ServoFitCoupon`: a 4 mm plate with
23.4 ×12.8 mm aperture, provisionally28 mm tab-hole pitch and2.3 mm holes.
It verifies body clearance and tab fit, **not horn geometry or overall load capacity**.
Generate three coupon runs with ServoFitClearance0.4,0.6,0.8 mm (total dimensional
clearance), label each physically, and print/cure them identically to the final parts.
Select a sliding fit without forcing the case or stressing the tabs. Use the
actual mounting hardware to determine tab-hole diameter and washer clearance.
Separately test the journal and bushing seat after kernel validation; no interference
fit is specified for brittle resin. Do not enlarge the servo case with filing.

## Print preparation

Use the original Photon Mono X192 ×120 ×245 mm volume. The largest rotor isØ116,
leaving only4 mm total on the120 mm axis when horizontal: its raft/support envelope
will probably require tilting. The generator's fit flag is bare-part orientation
only. Confirm the complete supported bounding box in the slicer for every job.

| Part | Starting orientation | Support / surface priorities |
|---|---|---|
| Base | tilt20–30° along long axis | support underside/rim; avoid feet and mounting surfaces; keep ballast pockets drainable |
| Cover | tilt25–35° | support edges and underside; check flatness before clamping |
| Pedestal | lean25–35° | support posts and shelf islands; preserve top bearing plane and accessible openings |
| Pan rotor | tilt25–35° | supports on underside outside journal/horn interfaces; no marks on thrust face |
| Forks | lean30–45° | support feet and rear edges; avoid bushing bore and servo mating faces |
| Cradle | lean30° | support underside and sidewall roots; preserve plate contact face |
| Camera plate | lean25–35° | supports underneath, never on the padded-camera contact plane |
| Horn adapter | tilt30° | support perimeter; preserve both flat mating faces and holes |
| Cable saddle/coupon | tilt20–30° | support underside; preserve test aperture edges |

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
451–523 ml budget. Large flat sections may warp; reject bearing faces that rock.

## Assembly sequence

1. Execute the FreeCAD script. Open the FCStd and each representative STEP/STL;
   inspect the geometry audit and full travel. Resolve every unintended intersection,
   disconnected solid, failed mesh and inaccessible fastener before printing finals.
2. Print/cure the servo coupon; verify both servos. Measure horns and mounting insert;
   update interfaces and rerun. Mount-camera clearance hole remains disabled until then.
3. Install base captive nuts from the open pockets. Fit the measured pan servo into
   the pedestal shelf; secure its tabs with matched screws/washers without bending tabs.
   Attach pedestal to base. Confirm flange fasteners can be reached and do not hit ballast.
4. Centre the servo using a suitable standalone tester and the manufacturer's
   procedure, unloaded; remove power before fitting the horn. Do not force a powered
   shaft or assume its advertised180° corresponds to any particular pulse range.
5. Install the PTFE thrust washer, horn and pan rotor. Use the horn centre screw
   through the rotor access hole and verified horn bolts. Confirm gravity load rests
   on the washer, not on the servo shaft; tune washer/adapter stack before proceeding.
6. Bolt the forks to the rotor, add the right servo and its original horn, and attach
   the cradle through the adapter. Install the passive shoulder pivot/bushing/washer
   stack. Set slight free axial play without squeezing the cradle. Check that no nut
   or bolt tail enters the rotating envelope and that horn screws are accessible.
7. Mount camera to its removable plate with the **verified** screw and washer/pad.
   Select under-head length from plate+pad+washer thickness plus required engagement,
   leaving clearance to the bottom of the measured blind insert. Do not bottom out.
   Secure the plate's four flush fasteners; verify all heads clear the actual clip.
8. Add measured, restrained ballast, then fit the cover and feet. Nothing may project
   below the feet. Reweigh assembly, confirm COM and rerun tipping calculation.
9. Fit the USB cable with a loose loop between camera and rotor saddle, then a second
   slack span between rotor and desk anchor. Begin with≥30 mm bend radius and~150–200 mm
   free loop length as provisional routing space, not a cable manufacturer rating.
   Keep loops away from horns/pivots and lens. The saddle's two bolts retain it; use
   a soft strap around the saddle body, loose enough not to pinch the jacket.
10. Inspect unpowered movement with horns disconnected from servo drive if necessary.
    Do not back-drive a geared servo forcibly. Reconnect at known neutral only.

## Mechanical and travel acceptance

- Use a dummy96 g load before the real camera. Start with gentle support under the
  assembly. Check static deflection, loose hardware, resin cracks and bearing friction.
- With power removed, verify assembly at small increments throughout both-axis travel;
  endpoint-only checks can miss intermediate contact. Inspect screw tails and cable
  loops at combined±60/±35 corners, but stop short of any contact.
- Set initial **test** software limits to±10° with slow motion (e.g.5°/s and10°/s²),
  not the final targets. Establish centre and angle mapping separately for each
  purchased servo with an external tester or a future independently reviewed driver.
  No servo pulses or driver are provided by this CAD package.
- Increase one axis at a time in5° increments while watching current, temperature,
  cable pull and geometry. Record first contact/tension/binding boundaries; set
  working endpoints at least5° inside observed boundaries, with more margin for
  backlash/flex. Use the tighter of actual servo, mechanical, cable and desired limits.
  A software number is not a physical stop or an emergency disconnect.
- Keep a reachable servo-power disconnect. Stop on buzzing, rising current, heat,
  visible flex or stall. Never use prolonged stall as a torque test. Test a realistic
  duty cycle and let the servo cool; compare to actual manufacturer limits when available.
- At every pan direction and extreme tilt, apply measured small horizontal loads with
  a force gauge at the cable exit. Confirm no foot lifts or slips at the modeled0.5 N
  load and that the cable anchor intercepts larger pulls. Do not push to overturn near
  the camera. Increase base footprint/ballast when measured margin is insufficient.
- Record optical height at neutral and minimum across tilt; minimum must remain≥101.6 mm.
  Recheck after fastening the actual folding foot and pad. Record cable force, backlash,
  travel, mass, tip/sliding behaviour and any permanent deformation after a soak test.

Until these steps pass, the model is a preliminary fit/assembly design, not an
approved final printable mount. The software's prior simulated-motor arming state
does not authorize a physical servo connection.
