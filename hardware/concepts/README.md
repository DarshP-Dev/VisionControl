# Editable pan/tilt mount concept — Phase 4.5

[pan_tilt_concept.scad](pan_tilt_concept.scad) is an optional OpenSCAD concept,
independent of the Python runtime. OpenSCAD is not an application dependency.
It was not found on PATH or in the standard installation locations in this
environment: **no OpenSCAD compilation, mesh export or CAD preview render was
performed**. Structural tests inspect the source/parameters only.

Open the `.scad` file in OpenSCAD, adjust the parameters at the top, then use
Preview (F5). Inspect neutral `pan_deg=0; tilt_deg=0`, pan left/right (-30/+30)
and tilt up/down (-15/+15). Interactive orbit/zoom helps distinguish the axes.
The transparent colored lines/arcs are conceptual axes/range indicators, not
structural shafts. No preview PNGs or fabrication-ready meshes are supplied.

The dark stationary base represents a mounting plate/possible weighted base,
with an approximate pan-motor enclosure and vertical red pan axis. The circular
platform and both upright brackets rotate together. A horizontal orange tilt
axis passes between the brackets; short external pivots and a cradle support
the camera plate. The camera/plate tilt as one assembly. The second blue motor
enclosure indicates one possible outside-bracket placement. A transparent rear
path indicates space that a cable might need; it is not a verified clearance.

Coordinates: +X scene-right, +Y neutral camera-forward, +Z up. Positive logical
pan points right (`rotate z=-pan_deg`); positive tilt points down (`rotate x=-tilt_deg`).
These match the software's conceptual convention, not future motor polarity.

All dimensions are **illustrative millimetres**, not measured UGREEN dimensions
or particular servo specifications. Editable parameters include base dimensions,
camera approximate dimensions, bracket spacing, platform/support geometry,
motor enclosure sizes, camera mounting offset, pan/tilt angles and indicated
ranges. Default camera bottom and mounting plate meet geometrically; editing
offsets/dimensions can create intersections and requires visual review. The basic
assertions do not prove that all moving clearances are safe.

This is not for fabrication or purchase decisions. No webcam mass, center of
gravity, screw thread/pattern, servo outline, bearing load, torque, stiffness,
tip stability, printable wall thickness or cable bend radius is verified.
Illustrative +/-45 pan and +/-25 tilt limits are not measured mechanical limits.
Motor overhang, support stiffness, actual pivot attachment and cable sweep need
review after parts are selected. Range indicators can overlap parts deliberately.

Before any build, measure the actual webcam and mounting interface, mass and
center of gravity; establish desired travel and clearances; identify motor/shaft/
bearing envelopes, torque/speed/duty requirements, base anchoring and safe power/
cable routing; then revise the geometry and validate collisions/load capacity.
Hardware selection, mounting compatibility, tolerances, verified limits and a
fabrication-ready design are deferred to Phase 4.6. No bill of materials or motor
purchasing recommendation is made here.
