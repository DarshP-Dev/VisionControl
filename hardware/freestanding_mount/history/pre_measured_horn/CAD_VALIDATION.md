# FreeCAD execution and mechanical review — 2026-11-07

## Result and limits

The existing design was executed and corrected in **FreeCAD 1.1.4**, build
`20260928`, commit `4fd3bf320d9566a27e60069fc8387448aaa3a094`, installed in
`C:\Program Files\FreeCAD 1.1`. The bundled `bin\python.exe` successfully imports
FreeCAD, Part, MeshPart and TechDraw; the GUI executable runs the rendering macro.
This is actual kernel execution, file export/read-back and GUI rendering.

**CAD validation is not physical verification or release for final printing.**
Hardware interfaces are still provisional. No measured servo horn, clip sweep,
thread engagement, cable resistance, resin strength, fatigue or motor thermal test
is implied by these results. No FEA or slicer support-volume computation was run.

Final deliverables are in **`output_verified/`**. That name refers to the checks
below, not hardware approval. Earlier folders are preserved evidence:
`baseline_executed/`, `iteration_01/`, `output_v2/`, `output_v3/`, `output_final/`.
The latter is an intermediate iteration despite its historical name; use
**output_verified**. `history/pre_freecad/` preserves the original source/documents.
The older ZIP in the parent hardware folder is the original script-only handoff.

## Actual generated files

- `VisionControl_Assembly.FCStd`: 18 geometry objects plus editable Parameters;
  11 printable designs, including the hidden standalone coupon, plus 7 hardware
  reference envelopes. References must not be printed.
- `exploded_mount.FCStd`: 10 separated assembly components, excluding the coupon.
- `stl/`: 11 individual closed STL meshes in millimetres.
- `step/`: 11 individually readable STEP solids in millimetres.
- `drawings/`: 11 kernel-projected SVG sheets and rendered PNGs, plus the interface
  coordinate schedule. They give front/top/side outlines and envelope dimensions;
  they are preliminary dimension sheets, not fully toleranced manufacturing drawings.
- `assembly_iso.png`, `assembly_front.png`, `assembly_side.png`, `assembly_top.png`,
  `assembly_extreme.png` and `exploded.png`: FreeCAD GUI renders of actual shapes.
- `geometry_audit.json`, `export_verification.json`, `parameters_used.json` and
  `render_status.json`: machine-readable evidence.

The camera box represents the entire camera-and-folded-clip envelope. Its face
does not reproduce the lens or detailed hinge. Servo tabs are included as assumed
6 mm end-tab envelopes; actual tab and shaft measurements can change the fit.
Flexible USB cable, screw heads/tails and actual stock-horn outlines are not fully
modeled. Check those physically and in an updated model after measurement.

## Problems found and corrected

1. The original pan journal overlapped the pedestal column corners by about
   4.74 mm³. A circular journal clearance was cut through that region.
2. The original inward fork ribs overlapped the cradle by up to144 mm³ on each
   side. Ribs now reinforce the outer side of each fork, clear of the tilt sweep.
3. A zero-volume contact remained at the journal bottom/servo shelf. The journal
   was shortened from10 to7 mm, preserving engagement through the4 mm top bearing
   plate while giving space above the provisional2 mm servo tabs. A contact-only
   check would have missed this because the intersection volume was zero.
4. Reopened Part::FeaturePython objects could retain the old placement after a
   parameter edit. Component execution now writes the transformed Placement as
   well as the single-solid Shape. Reopening, changing tilt to10°, comparing its
   centre to the explicitly transformed kernel shape and returning to0° are tested.
5. The side-view label on the generated drawing was below its sheet boundary.
   The projection was moved upward. Screenshots now wait for the GUI camera to
   finish moving; exploded components are explicitly visible before export.
6. The GUI initially restored saved shapes without their Python callbacks. The
   documented `mount_geometry.open_assembly()` helper explicitly attaches those
   callbacks. The GUI macro asserts that its +60° pan/+35° tilt pose matches the
   transformed kernel geometry before rendering; this check passes. Import the
   module and use the helper when opening for editing, as shown in README.

## Geometry and motion checks

All11 printed parts are non-null, valid, single solids. All11 STEP files were read
back and compared to their source volumes; errors are below0.01 mm³. All11 STL
files were read back, report closed solid meshes, and differ in volume by less
than1%. This is a kernel/mesh-closure check, not an independent slicer repair or
resin print test. Both FCStd files reopen with valid geometry.

The collision sweep contains **375 poses**: pan -60° through+60° in5° increments,
tilt -35° through+35° in5° increments. Every pair is checked for positive volume
overlap above0.01 mm³, with caching only for relative transforms invariant under
shared rigid rotations. There are **zero detected intersections** in the modeled
parts and reference envelopes. Contact faces are not silently excluded.

Minimum sampled distances for selected non-contact pairs:

| Pair | Minimum distance |
|---|---:|
| Pedestal / pan rotor | 0.25 mm |
| Pan rotor / cradle | 6.874 mm |
| Left fork / cradle | 2.874 mm |
| Right fork / cradle | 2.874 mm |

The0.25 mm journal clearance is a CAD value; resin fit must be calibrated. The
sample sweep is not a mathematical proof between samples. Actual screw heads,
horn screws, tab variations, clip articulation and cable can still interfere.
Nut locations and driver routes were reviewed in the geometry and assembly
sequence. Pan servo installation precedes bolting on the pedestal; the camera
plate must be removed for some camera-screw and horn access. Hardware-in-hand
assembly remains mandatory. Do not force a servo into the nominal opening.

All bare part bounding boxes fit the192 ×120 ×245 mm printer envelope in at least
one orthogonal orientation. The largest footprint is theØ116 rotor, which leaves
only4 mm total on the120 mm axis when horizontal. Tilt it in the slicer and check
raft/support bounds. This check does not say that the chosen supported print
orientation fits or that the unsupported shape can be printed directly on the bed.

Neutral optical height remains provisionally140 mm above the desk. This uses the
unmeasured32 mm lens datum and4 mm foot protrusion. It must be confirmed with the
real clip/pad arrangement; the minimum requirement remains101.6 mm over travel.

## Resin optimization

The original arithmetic estimate was451–523 ml including allowances. Actual
kernel volumes now permit a like-for-like comparison (assembly only, coupon excluded):

| Component | Original CAD ml | Revised CAD ml |
|---|---:|---:|
| Base | 114.52 | 79.25 |
| Cover | 23.68 | 23.68 |
| Pedestal | 67.45 | 48.57 |
| Pan rotor | 48.76 | 30.30 |
| Left fork | 12.74 | 11.88 |
| Right fork | 15.00 | 14.14 |
| Cradle | 27.34 | 27.34 |
| Camera plate | 18.50 | 18.50 |
| Horn adapter | 3.30 | 3.30 |
| Cable saddle | 1.61 | 1.61 |
| **Assembly total** | **332.906** | **258.563** |

Reduction: **74.343 ml / 22.33%**. The separate coupon adds approximately3.38 ml,
making approximately261.94 ml total solid volume for one of every printed item.
Applying the same unmeasured25–45% support/raft/waste allowance gives approximately
**327–380 ml**. This is an allowance, **not a slicer-estimated support volume**.
The pre-optimization kernel assembly plus coupon with that allowance is420–488 ml;
it is a more comparable baseline than the original rough451–523 ml estimate.

Changes are larger open ballast pockets (43 ×92 ×10 mm each), retained local nut
bosses and solid foot supports, 10 mm solid pedestal columns, and a rib/spoke pan
rotor with an8 mm radial rim and14 mm spokes. Mounting pads are retained. No sealed
resin chambers were introduced. The loaded camera plate and cradle remain4 mm
thick; uncertain clip contact made aggressive cutouts inappropriate at this stage.
There is no quantitative strength/fatigue proof for the smaller columns or rotor.
Use the dummy-load, deflection and soak tests before accepting the material savings.

## Mass, torque and stability

At the explicit assumed cured density1.15 g/ml, the kernel parts plus the supplied
camera/servo masses give approximately187.8 g fixed mass and233.0 g rotating mass,
excluding screws, washer and bushing. Printed tilt components weigh approximately
56.5 g; the earlier65 g tilt-bracket allowance leaves about8.5 g for its fasteners.
Weigh real cured parts and replace these assumptions.

The existing conservative tilt screening remains approximately0.038 N·m: nominal
gravity~0.006, COM uncertainty~0.0237, smooth startup~0.00029 and cable~0.008 N·m.
This is below an assumed25%-of-stall budget0.049 N·m. **That budget is not a
manufacturer continuous rating.** A1 N cable pull adds enough torque to exceed
it. Do not run sustained stalls to validate the MG90S. Torque, thermal behaviour,
backlash and resin stiffness need actual hardware tests.

Using the new CAD masses, conservative moving-group COM offset25 mm and equivalent
horizontal load0.5 N at140 mm, approximately196.5 g ballast is required for a2×
tipping ratio;250 g gives approximately**2.17×**. The JSON includes nominal CAD
centres of mass at nine extreme/neutral combinations, with250 g at the base.
Camera envelope COM is not a measured COM. The stability screening retains larger
uncertainty than those nominal coordinates and does not certify resistance to desk
bumps or sliding. Additional fastener mass is omitted, not assigned a guessed location.

Enlarged pockets have79.12 ml gross volume; local nut and foot bosses reduce it.
250 g steel occupies31.85 ml before gaps, so volume is plausible but usable stock
shape and fastening must be checked. Secure the ballast against movement. The
cover is relieved around the feet and has flush underside screws. Do not place
loose balls/washers where they can escape or obstruct the captive nuts.

## Remaining fit and print gates

- Verify camera insert diameter/pitch/depth/position. The mounting hole remains
  disabled; the plate is intentionally blank at that location.
- Measure both actual servo bodies, tabs, horn outlines, bolt patterns, shaft
  offset/projection, centre screws and tolerances. Print the coupon first.
- Verify shoulder/bushing stack, journal fit, washer thickness, axial play and
  actual horn fastener access. The pan washer must carry weight without shaft preload.
- Inspect full clip articulation and lens clearance with the removable plate;
  do not assume the rectangular envelope models the open clip.
- Route two slack cable spans and use a desk anchor; measure cable force over
  combined travel. The saddle provides a location, not a validated flexible-cable model.
- Slice supported orientations, inspect islands/drainage, calibrate exposure and
  cure, and inspect bearing/contact flatness. All cavities are accessible; wash
  and cure before measuring fit. Do not use closed hollow pockets.
- Use measured masses and a dummy camera load for deflection/stability tests.
  Start actual servo commissioning unloaded, with a reachable power disconnect
  and conservative travel/speed limits; follow MEASURE_AND_BUILD.md.

No hardware output, application change, Git stage, commit or push was performed.
