# Right fork lower connection reinforcement — 2026-11-17

Current revision: **output_right_fork_web_2026_11_17/**. Only RightFork geometry
changes. Previous corrected output_fit_offset_2026_11_16 is preserved.

## Finding

The screenshots correctly highlight a narrow load path. The38mm horn opening
cuts through the30mm-wide inner upright, leaving two shoulders where the lower
upright meets the outward servo flange. The old CAD is one valid solid, but this
does not establish sufficient strength. Immediately below flange bottomZ112,
a10-micron horizontal slab gives38.087mm² of material. A broad continuous lower
connection is preferable to relying on those shoulders in resin.

## Local correction

Added a30mm-wide outward tapered web, from foot topZ84 to servo-frame bottomZ112.
The old inner upright ends atX58; added thickness grows from2mm at the foot to4mm
at the frame. The web's outside face therefore slopes X60 ->62. A1mm construction
overlap goes into existing flange material; Boolean comparison proves that no
new geometry remains aboveZ112. The actual addition is bounded by:

- X58..62, Y-15..15, Z84..112mm, in the neutral assembly coordinates.
-2.520ml extra resin, no removed material.
- Right fork volume12.411 ->14.931ml; external bounding box unchanged18x40x76mm.

This is lower-segment thickening with a tapered support, not a change to the servo
frame or its pockets. The horn opening, servo aperture/tab holes, screw-tail relief,
base foot and bolt holes retain their original geometry. All other assembly parts
and both0.1mm horn-hole corrections remain unchanged. No extra fasteners required.

Parameters: RightForkLowerWebEnabled=true; FootDepth2, TopDepth4, Width30,
Overlap1mm (each prefixed RightForkLowerWeb). Old documents lacking these properties
retain the previous geometry. The top overlap is only Boolean construction;
the upper frame is unchanged as verified by the added-material bounds.

## Executed validation

FreeCAD1.1.4 executed the updated generator. Twelve valid single printed solids
and twelve closed STL meshes were generated. All12 STL/STEP pairs passed read-back;
both FCStd documents reopened and the editable assembly tilt recompute passed.
The375-position pan/tilt sweep found zero modeled intersections. Existing assumed
hardware-budget checks, including continuous tilt fastener sweeps, pass.

verify_right_fork_web.py independently checks:

- RightFork remains one valid solid; zero old material removed.
- Every other printed/reference shape has zero Boolean symmetric difference.
- Every added region lies within the stated outer lower-segment box.
-6mm cylindrical head/driver budgets at both foot bolts remain clear.
- Section immediately below the flange grows38.087 ->158.076mm² (4.15x material
  area). This is a geometric measure, NOT4.15x verified strength or an FEA result.

Extra resin mass is approximately2.90g using the existing assumed1.15g/ml density.
Whole printed assembly volume increases259.071 ->261.591ml. No resin optimization
was performed. Actual resin strength, fatigue, screw preload and thermal/creep
behaviour have not been physically tested.

## Printing and fit status

The right fork still awaits the previously unresolved servo axial stack before
final production printing. Reinforcement does not resolve the34mm installed
highest-point versus35.5mm modeled mating-face discrepancy. No printer was run.
The earlier four-part batch (Base, BallastCover and two horn tests) is unaffected.

For a later right-fork print, support the lower web/foot and brace the tall frame;
keep tips off servo and bearing faces, bolt bores and horn clearance. Do not print
the narrow junction unsupported merely because the solid is now reinforced.
Use the established calibrated resin process, inspect after cure and perform a
supported dummy-load test before installing the camera. No new hollow chambers.

## Files and reproduction

- Updated full assembly: output_right_fork_web_2026_11_17/VisionControl_Assembly.FCStd
- Updated part: stl/RightFork.stl and step/RightFork.step in that directory.
- right_fork_web_verification.json documents the local geometric comparison.
- geometry_audit.json and interface_verification.json document motion/clearances.
- export_verification.json documents actual exported-file checks.
- render_cad.FCMacro targets this revision and generates before/after fork views.

Generate to a fresh directory with generate_freecad.build, then run
verify_exports.py, verify_interfaces.py and verify_right_fork_web.py on that folder.
The latter requires history/pre_right_fork_web/parameters.json. Existing
verify_fit_offset.py is specific to the earlier offset-only revision.

No commit, push or unrelated app change is included.
