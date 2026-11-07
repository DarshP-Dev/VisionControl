# Freestanding camera mount — executed FreeCAD design

Updated 2026-11-07. FreeCAD **1.1.4** has executed the existing generator, and actual
CAD/export files are in **[output_verified/](output_verified/)**. Hardware interfaces
remain provisional; this is **not yet approved for final printing**.

The servos have now arrived with **supplied plastic horns and mounting screws**.
See [SERVO_ACCESSORY_REVIEW.md](SERVO_ACCESSORY_REVIEW.md) for the interface review,
measurement list and owner-drilled camera plate guidance. The reattached photo has
been inspected: double-arm and cross-shaped horns are visible, with an apparent
single-arm horn partly obscured. A double-arm on each axis is preferred if both
kits include one. Exact fit and screw specifications remain unverified. See
[SERVO_MEASUREMENTS.md](SERVO_MEASUREMENTS.md) for the measurement worksheet.
Geometry and the existing coupon have not changed in this review.

Start with [CAD_VALIDATION.md](CAD_VALIDATION.md) for the findings, resin comparison,
clearances, physical assumptions and remaining tests. The original script-only
handoff is preserved in `history/pre_freecad/`. Earlier output folders are iterations;
use `output_verified`, even though an intermediate folder is named `output_final`.

## Open and edit

In FreeCAD, open **View → Panels → Python console** and run:

```python
import sys
sys.path.insert(0, r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount")
import mount_geometry
mount_geometry.open_assembly(r"C:\Users\Darsh\VisionControl\hardware\freestanding_mount\output_verified\VisionControl_Assembly.FCStd")
```

Keep `mount_geometry.py` available on that path. The custom Python proxies live in
that module, not embedded executable code in the FCStd. The helper restores the
callbacks if FreeCAD initially loads only saved shapes. Select **Parameters** in
the document tree, edit a dimension or angle, and recompute. Reference envelopes
are not printable components. `ServoFitCoupon` is hidden in the assembly because
it is a standalone test part; its STL and STEP are exported separately.

`parameters.json` is the reproducible generation source. Document edits do not
silently update the JSON. Update it explicitly before regenerating exports.

## Reproduce with the installed Windows environment

The following uses FreeCAD's bundled interpreter, not VisionControl's virtualenv.
Use a fresh output directory for each generation; existing output is never overwritten
by the generator. GUI rendering intentionally refreshes its own preview files.

```powershell
Set-Location C:\Users\Darsh\VisionControl
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -c "import sys; sys.path.insert(0,r'C:\Users\Darsh\VisionControl\hardware\freestanding_mount'); import generate_freecad as g; g.build(g.ROOT/'output_next')"
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' hardware/freestanding_mount/verify_exports.py hardware/freestanding_mount/output_next
```

For GUI renders, `render_cad.FCMacro` currently targets `output_verified`. Adjust
its `output` variable for a new generation, then run:

```powershell
Start-Process -FilePath 'C:\Program Files\FreeCAD 1.1\bin\freecad.exe' -ArgumentList 'C:\Users\Darsh\VisionControl\hardware\freestanding_mount\render_cad.FCMacro' -WindowStyle Hidden -Wait
```

That macro opens the generated files in its FreeCAD process, renders the views,
saves presentation settings, and closes its own documents/application. Keep its
module path consistent with the generator. It does not operate physical motors.

## Delivered artifacts

- [Editable assembly](output_verified/VisionControl_Assembly.FCStd)
- [Exploded assembly](output_verified/exploded_mount.FCStd)
- [Individual STL files](output_verified/stl/) and [STEP files](output_verified/step/)
- [Actual assembly preview](output_verified/assembly_iso.png) and [exploded preview](output_verified/exploded.png)
- [Projected component drawings](output_verified/drawings/), SVG and PNG
- [Fit coupon STL](output_verified/stl/ServoFitCoupon.stl)
- [Geometry audit](output_verified/geometry_audit.json) and [export/read-back validation](output_verified/export_verification.json)
- [BOM](BOM.csv) and [measurement/print/assembly instructions](MEASURE_AND_BUILD.md)

The current kernel assembly volume is **258.56 ml**, down from **332.91 ml** before
optimization (**22.33%**). One coupon adds about3.38 ml. Support/raft/waste allowance
of25–45% gives approximately327–380 ml total; no slicer support estimate was made.
Density1.15 g/ml is an assumption, not a measurement of the cured resin.

## Mechanical configuration and limitations

Base110 ×100 ×14 mm; rubber feet project4 mm below the base. Target pan±60°,
tilt±35°, tilt axis128 mm above the base bottom, provisional optical height140 mm
above the desk. The original camera/clip envelope remains82 ×46 ×45 mm,96.3 g.

The pan journal and PTFE thrust washer carry the camera load; the purchased stock
horn transmits torque. The opposite tilt pivot uses a shoulder bolt and plain
bushing. Both horn patterns and servo-tab/shaft positions are provisional. The
camera plate remains blank at its insert location: `CameraHoleEnabled=false`.
The6.35 mm/1.27 mm insert values are a1/4-20 candidate, **not a verified thread**.

The revised base has43 ×92 ×10 mm open ballast pockets with retained nut/foot
bosses. Nominal target ballast remains250 g secured metal. Calculated tipping
ratio is~2.17 under the documented0.5 N load and25 mm moving-COM-offset assumptions;
that does not establish resistance to larger pulls, sliding or desk impacts.

The modeled375-pose sweep found no positive-volume intersections. Minimum sampled
journal clearance is0.25 mm; fork/cradle clearance is2.87 mm. These checks omit the
actual USB loop, detailed clip articulation and exact fastener/horn geometry.
Use the measurement checklist and fit coupon before finalizing those interfaces.
The provisional tilt torque screen is~0.038 N·m; advertised stall torque is not
continuous operating torque. Physical load, thermal and deflection tests remain.

All seven reference photos were reviewed in the earlier handoff. They establish a
folding foot, underside metal insert and rear cable exit, but not a usable thread,
COM or optical-height measurement. Locally reduced images remain ignored by Git.

This work changes only the hardware project. No software driver, live hardware
control, Git staging, commit or push is included.
