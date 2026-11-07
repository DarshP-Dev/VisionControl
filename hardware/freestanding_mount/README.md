# VisionControl freestanding mount — measured-horn fit revision

Updated2026-11-07. Current executed artifacts are in **output_measured_fit/**.
FreeCAD1.1.4 generated the geometry and exports; files were read back, documents
reopened/recomputed and actual GUI renders inspected. This is ready for a small
**fit-test print**, not full mechanical release.

Start with [FIRST_PRINT.md](FIRST_PRINT.md). Print ServoFitCoupon, PanHornCoupon
and TiltHornAdapter only. They total21.07 ml solid (roughly26–31 ml with supports
and waste). Resolve the installed horn mating-face/tab datum: the owner reports
34 mm to the highest point while the provisional model places the mating face at
35.5 mm. That unresolved stack prevents final pedestal/fork/rotor print release.

## Current files

- [Editable assembly](output_measured_fit/VisionControl_Assembly.FCStd)
- [Exploded assembly](output_measured_fit/exploded_mount.FCStd)
- [STL](output_measured_fit/stl/) and [STEP](output_measured_fit/step/) —12 designs,
  including two separate coupons;10 parts form the assembly.
- [Assembly preview](output_measured_fit/assembly_iso.png),
  [extreme pose](output_measured_fit/assembly_extreme.png),
  [exploded preview](output_measured_fit/exploded.png)
- [Projected drawings](output_measured_fit/drawings/) and interface schedule
- [Validation](CAD_VALIDATION.md), [accessory comparison](SERVO_ACCESSORY_REVIEW.md),
  [measurements](SERVO_MEASUREMENTS.md), [parameter provenance](measurement_status.json)
- [BOM](BOM.csv), [assembly instructions](MEASURE_AND_BUILD.md),
  [physical results worksheet](FIRST_PRINT_RESULTS.md)

The chosen first-fit horn is the supplied double-arm on each axis, using the
approximately14.5 mm outer radius. Cross horns are alternatives only after their
actual patterns/arms are measured. Unknown bores, screw types and tab/shaft datums
remain explicitly provisional. Never substitute a printed spline for a stock horn.

## Preserved design

Base110 x100 mm; target optical centre140 mm above desk; target pan±60/tilt±35;
supported pan journal/thrust washer; opposite passive tilt bushing;250 g ballast
plan. Camera plate remains blank at the camera screw location and4 mm thick,
with its existing four structural mounting holes. No further resin optimization.
Current assembly resin259.07 ml; plus both standalone coupons273.55 ml, about
342–397 ml including rough25–45% support/waste allowance. No slicer estimate made.

## Open and edit

In FreeCAD: View → Panels → Python console:

```python
import sys
sys.path.insert(0, r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount")
import mount_geometry
mount_geometry.open_assembly(r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount\output_measured_fit\VisionControl_Assembly.FCStd")
```

Select Parameters, edit and recompute. Keep mount_geometry.py on sys.path; its
FeaturePython callbacks are external to FCStd. open_assembly restores them if GUI
security loads saved shapes only. Reference discs are conservative horn envelopes,
not accurate replicas and not print parts. Both coupons are hidden in assembly.

parameters.json is the generation source; GUI edits do not update it automatically.
measurement_status.json records measurement versus design assumptions. The34 mm
height and4.5 mm inner radius are recorded evidence, not active mounting constraints.
The6 mm hub is checked against7 mm access; its axial shape remains unknown.

## Reproduce in PowerShell

Use FreeCAD's interpreter, not VisionControl's virtual environment. Choose a fresh
output directory; generation deliberately refuses to overwrite an existing one.

```powershell
Set-Location C:\Users\Darsh\VisionControl
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -c "import sys; sys.path.insert(0,r'C:\Users\Darsh\VisionControl\hardware\freestanding_mount'); import generate_freecad as g; g.build(g.ROOT/'output_next')"
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' hardware/freestanding_mount/verify_exports.py hardware/freestanding_mount/output_next
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' hardware/freestanding_mount/verify_interfaces.py hardware/freestanding_mount/output_next
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m unittest discover -s hardware/freestanding_mount -p test_engineering.py -v
```

For GUI rendering, change the output variable in render_cad.FCMacro to the new
folder first (currently output_measured_fit), then run:

```powershell
Start-Process -FilePath 'C:\Program Files\FreeCAD 1.1\bin\freecad.exe' -ArgumentList 'C:\Users\Darsh\VisionControl\hardware\freestanding_mount\render_cad.FCMacro' -WindowStyle Hidden -Wait
```

The macro opens its own documents/process, renders, saves presentation settings,
and closes. Inspect render_status.json and any render_error.txt, then the images.
No physical servo is controlled by any script in this package.

## Preserved history

output_verified contains the preceding validated geometry, unchanged. Its sources
and documents are preserved in history/pre_measured_horn; use that historical
module to reproduce it. output_measured_fit_v1 and _v2 are retained diagnostic
iterations with known hardware-budget conflicts, NOT print sources. Earlier
output_final is also a historical iteration, not current release. Old ZIP files
remain untouched. New work stays inside this hardware package; no commit or push.
