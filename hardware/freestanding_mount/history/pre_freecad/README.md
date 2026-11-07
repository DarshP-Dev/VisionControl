# Freestanding camera mount — preliminary engineering package

Status at delivery, 2026-11-06: **FreeCAD was not executable in this environment.**
The Python source was syntax checked and its independent engineering arithmetic
was executed. No `.FCStd`, STL, STEP, kernel-projected drawing, CAD assembly render,
or validated solid geometry is supplied. The SVG drawings supplied now are
dimensioned **schematics**, not evidence of CAD execution. This follows the
requested script-only fallback; final print release is pending.

## Files and execution

- `parameters.json`: dimensions, interfaces, fit allowances and calculation assumptions.
- `mount_geometry.py`: FreeCAD Part solids and linked editable FeaturePython components.
- `generate_freecad.py`: creates the assembly, exports, exploded model and collision audit.
- `engineering.py`: independently runnable calculations and schematic drawing generator.
- `engineering_estimates.json`: actual output of those arithmetic calculations.
- `drawings/dimensioned_layout.svg`, `exploded_schematic.svg`, `interface_schedule.csv`.
- `BOM.csv`: preliminary hardware quantities and lengths; provisional interfaces flagged.
- `MEASURE_AND_BUILD.md`: measurement, printing, assembly and acceptance sequence.
- `test_engineering.py`: arithmetic and input-file checks, not kernel validation.

Open FreeCAD, enable **View → Panels → Python console**, and paste:

```python
import sys
sys.path.insert(0, r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount")
import generate_freecad
doc, audit = generate_freecad.build()
```

FreeCAD must supply `FreeCAD`, `Part`, `MeshPart`, and `TechDraw`; installing a Python
package named FreeCAD into VisionControl's virtual environment is not a substitute.
No additional dependency is required for the existing camera application.
The generator refuses an existing `generated` directory. For another iteration use
`generate_freecad.build(r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount\generated_v2")`.
Keep the failed iteration for diagnosis; fix the source/parameters before generating again.

Expected outputs **after a successful future FreeCAD execution**:

1. `freestanding_mount.FCStd`: component shapes linked to editable `Parameters`.
2. `exploded_mount.FCStd`: separated component arrangement; GUI PNG if available.
3. `stl/*.stl` and `step/*.step`: eleven individual printed-component candidates,
   including the servo coupon. Reference camera/servos/horns are excluded.
4. `drawings/*.svg`: kernel-projected component views with envelope dimensions;
   use the interface schedule for hole locations. Drawing failures are reported.
5. `geometry_audit.json`: single-solid validity, mesh closure, part volumes,
   nominal build-volume fit and sampled collisions. `parameters_used.json` records inputs.

The script checks 15 pan/tilt combinations, including endpoints and mid-tilts.
**A sample sweep is not proof of continuous clearance.** It deliberately reports
intersections even between reference envelopes and printed parts. Review every hit;
do not whitelist an interference merely to get a passing result. Screws, shaft
details, clip articulation and flexible cable are not represented accurately enough
for a final clearance claim. Failed solid/mesh checks raise an error. Collision
findings and missing projected drawings do not prevent saving a reviewable assembly.

To edit a generated model, keep this directory on `sys.path` before opening the
FCStd, select `Parameters`, change values, then recompute. All linked features
regenerate. Export changes by updating `parameters.json` and rerunning in a fresh
output directory; saved document edits do not silently modify the JSON source.
Basic construction details such as access windows and rib placement are named
in the Python geometry source; those remain editable there.

```powershell
Set-Location C:\Users\Darsh\VisionControl
.\.venv\Scripts\python.exe hardware/freestanding_mount/engineering.py
.\.venv\Scripts\python.exe -m unittest discover -s hardware/freestanding_mount -p test_engineering.py -v
```

## Photo observations and dimensional confidence

Both supplied ZIP archives were opened: four images in `camerapics.zip` and three
in `morecamerapics.zip`. All seven were inspected together. They show a metal insert
in the underside of the folding foot, a padded mounting surface, a front lens,
the articulated folding clip, and a rear cable exit offset toward one side.
The additional side views help establish the folded configuration and cable path.
The tape in the background is not in a suitable plane for precise measurement.
No thread pitch, depth, centre of mass, lens height or servo dimensions were derived
from pixels. Locally reduced reference images are ignored by Git for privacy.

The 82 × 46 × 45 mm camera envelope, 96.3 g mass, and servo seller specifications
are user-provided values. The envelope includes the clip; **46 mm is not treated
as the camera body height alone**. The complete envelope is represented conservatively
as a box. The lens height above the mounting face is provisionally 32 mm.

The camera insert placeholder is major diameter 6.35 mm / pitch 1.27 mm (1/4-20).
This is an adjustable candidate, **not an identification of the photographed insert**.
`CameraHoleEnabled` defaults false, so the camera plate exports blank at the insert.
After verification, set the real diameter, position and clearance, then enable the
clearance hole. No resin thread is modeled. Screw length must respect measured
usable thread depth and must not bottom out in the camera.

Servo tab pitch 28 mm, shaft offset 5.3 mm, projection 5 mm, horn radius 11 mm,
horn fastener radius 8 mm and hole 2.3 mm are **unverified design placeholders**.
The two horns are the supplied hardware horns, attached with their original centre
screws; printed components never engage a spline directly. The 180° advertisement
does not establish safe pulse endpoints, continuous torque or backlash.

## Mechanical layout

Coordinate origin is the underside of the base: +X right, +Y forward, +Z up.
Positive pan turns right about -Z; positive tilt looks down about -X.

The base starts at 110 × 100 × 14 mm. Four Ø12 rubber-foot recesses are 1 mm deep;
5 mm feet produce 4 mm desk clearance. A 3 mm bottom cover therefore clears the
desk by approximately 1 mm. Two open underside 38 × 72 × 7 mm ballast pockets
have a cover with foot-clearance notches and flush countersunk bottom screw heads.
The pockets
avoid sealed resin cavities. Captive base nuts are loaded from underneath before
ballast; stock must be shaped around nuts, bolt tails and pocket walls.

An open four-column pedestal supports a pan bearing surface. The pan servo mounts
to its internal shelf and is installed before the pedestal is bolted to the base.
Base screw centres are X ±31, Y ±8, outside the columns so a driver can reach them.
A Ø39.5 printed journal runs in the Ø40 top aperture; a separate 2 mm PTFE thrust
washer carries vertical load. The stock pan horn transmits torque to the rotor and
retains it. Adjust the height stack so the washer supports weight without pressing
the servo shaft axially. Excess clearance permits rocking: reject and adjust the
coupon/washer stack if that occurs. This plain bearing is a prototype wear surface,
not a precision or lifetime-rated bearing.

The Ø116 rotor underside is Z76; its top is Z80. Separate bolted fork uprights carry
the tilt axis at Z128. The right servo drives a bolted horn adapter; the left has
a nominal Ø5 shoulder pivot in an Ø8 × 8 mm plain bushing, captured by washers.
The fork inner spacing is 108 mm. Cradle inside width is 90 mm; camera width is82.
There is no lens clamp, adhesive mounting, or modification to the folding hinge.
An open centre in the cradle permits access to the camera attachment screw.
Four flush-head M3 fasteners join the removable plate to the cradle; compare their
heads to the actual clip footprint and ensure they sit flush before mounting it.

Neutral optical height is **140 mm above the desk**, based on the provisional
32 mm lens datum. Lens height is unverified; the minimum-height requirement must
be measured on the assembled mount. The clip is retained intact, but its complete
opening sweep is not known. Remove the plate to fold/unfold it if clearance is
insufficient; do not force the clip against the frame.

The starting geometry uses 4 mm structural walls and local reinforcing ribs.
It avoids hidden hollow cavities. Large simple sections intentionally precede
weight optimization: use actual kernel volumes, cured-part weights and deflection
tests before removing material. Generic large fillets are avoided in this first
Boolean script because edge naming changes after parameters move. Add tested
root radii after geometry execution; inspect resin stress concentrations meanwhile.

## Engineering screening — assumptions, not certification

All numeric results below are reproducible in `engineering.py`. Gravitational
torque is `g × (camera_mass × horizontal_COM_arm + bracket_mass × arm)` after
rotation. The camera COM starts at Y0/Z-1 mm relative to tilt; moving cradle/plate/
adapter/fastener mass is assumed 65 g at Y0/Z-15 mm. Sweep ±35° gives approximately
**0.0060 N·m** nominal maximum gravity torque.

A conservative additional **15 mm COM uncertainty applied to both masses** adds
0.0237 N·m. Startup at 60°/s² adds about 0.00029 N·m under the stated inertia model.
USB resistance of 0.2 N at a 40 mm arm adds 0.008 N·m. Their conservative sum is
**0.0380 N·m**, approximately 0.388 kg·cm.

Advertised stall torque 2 kg·cm converts to 0.196 N·m. An arbitrary 25% planning
screen is 0.049 N·m; **this is not a documented continuous rating**. The calculated
load is below that screen with little reserve for cable snags, offset errors or
resin deflection. A 1 N cable pull alone contributes 0.040 N·m, taking the sum to
about 0.070 N·m: unacceptable against that screen. Minimize cable resistance and
measure temperature/current/holding behaviour under the real duty cycle. Sudden
stops can exceed this smooth-start model; no impact survival is established.

Pan gravity does not produce torque about a vertical axis on a level desk. Pan
demand comes from bearing friction, rotating inertia and cable twist. As an order
of magnitude, 0.30 kg at a conservative 60 mm gyration radius, accelerating at
60°/s², needs ~0.0011 N·m inertial torque. A provisional bearing friction coefficient
0.15 at a 22.5 mm radius adds ~0.0099 N·m; cable torque adds ~0.008 N·m. Total
~0.019 N·m remains a screening estimate: friction must be measured, especially
after cure, wear and any assembly preload.

Stability uses the conservative **foot-centre** support half-span of 42 mm, fixed
mass 200 g and total rotating mass 300 g. The latter includes camera, forks, rotor,
tilt servo, cradle and fasteners; it differs from the 65 g tilt-bracket estimate.
The moving COM is allowed 25 mm horizontal offset in any pan direction. An assumed
0.5 N equivalent lateral load at 140 mm includes cable/startup/disturbance effects.
Overturning moment is 0.1435 N·m. Without ballast the restoring/overturning ratio is
**1.43**; a target ratio of2 requires **about197 g additional low ballast**.
Using **250 g secured ballast** gives approximately2.15 under these assumptions.

The pockets have 38.3 ml gross capacity, equivalent to301 g of completely solid
steel; nuts, screws, gaps and actual stock reduce this. Loose washers may not fit
250 g. Weigh the installed ballast. If the target mass cannot fit securely, enlarge
the base (e.g.140 ×120 mm), regenerate, and recalculate. Do not treat loose ballast
as acceptable. This calculation is tipping only; rubber friction and sliding need
testing. Larger pulls and desk bumps can defeat either base. A desk-side cable
anchor should intercept accidental pulls before they reach the camera loop.

The rectangular camera envelope's local tilt sweep radius is approximately32.9 mm.
At35° the cradle floor corner is Z86.9, approximately6.9 mm above the rotor top.
Allowing3 mm fastener projection leaves approximately3.9 mm by this planar estimate.
This is not a 3D interference check: fork ribs, horn screws, shoulder stack, clip
sweep and cable need full CAD plus physical review. Pan ±60° is only a target.

Gross primitive resin estimates total **~361 ml**, including the coupon, with
**~451–523 ml** budgeted for supports/rafts and losses (25–45%). These estimates
partly double-count joined solids and omit some cuts; they are not slicer volumes.
Use `geometry_audit.json` volumes and the slicer report once generated. Density
1.15 g/ml is an explicit planning assumption, not a verified cured-resin measurement.

## Sources and verification boundaries

Official FreeCAD documentation establishes the intended scripting/export APIs:
[scripted objects](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Scripted_objects.md),
[Part export](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Part_Export.md),
[meshing](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Mesh_FromPartShape.md).
These API references do not validate the unexecuted model.
[Anycubic's ABS-Like Resin 3.0 page](https://store.anycubic.com/products/abs-like-resin-3-0)
is the material reference; use its current instructions and your bottle's SDS.
No resin tensile number is used as a guarantee for a notched, printed, cured part.

No application code, physical motor driver, GPIO, power system, servo pulse routine,
or Git commit/push was added. This package is mechanical development only.
