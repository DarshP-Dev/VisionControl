# Measured stock-horn integration — 2026-11-07

Use **output_measured_fit/** for this first-fit revision. **output_verified/** is
preserved as the previous executed design. Full hardware fit is not yet verified.

## Evidence and horn selection

The actual supplied photo `ChatGPT Image Nov 7, 2026, 03_31_23 PM.jpg` was opened
and inspected: double-arm horn, cross horn, partly obscured single-arm shape,
pointed/coarse mounting screws and a shorter candidate centre screw. The owner
confirms the accessory types. The bag does not establish exact quantities,
threads, dimensions or screw functions; no dimensions were read from the photo.

**Pan first-fit choice: measured double-arm, opposed outer holes.** Two screws at
radius14.5 mm give a balanced torque connection. Ideal equal-sharing force for a
given torque is8/14.5 =0.552 times that at the previous assumed8 mm radius. The
journal and washer support the assembly; the centre screw retains the stock horn.
A cross horn could offer additional attachments, but its pattern and outline are
unmeasured, and four screws do not automatically share load equally.

**Tilt first-fit choice: measured double-arm, outer pair along local Z at neutral.**
The separate cradle M3 holes lie along local Y at radius9 mm. The straight horn
avoids the cross horn's extra transverse arms near these fasteners and preserves
the opposite passive support. A cross horn remains an alternative after its own
pattern/clearance check. A single arm provides less balanced fastening and is not
selected. The choice is conditional on BOTH actual selected horns passing fit;
measurements from one horn are not proof that the second is identical.

## Measurement-to-CAD comparison

All supplied measurements are approximate, not metrology-certified.

| Feature | Previous CAD | New evidence / treatment |
|---|---|---|
| Body |22.8 x12.2 x28.5 mm|Approximately confirmed;23.4 x12.8 aperture retained|
| Wing thickness |2 mm|Approximately2 mm; retained|
| Hub OD |Not recorded separately|Approximately6 mm;7 mm centre access gives0.5 mm radial budget|
| Inner attachment radius |Not represented|4.5 mm recorded; not used for primary fastening|
| Selected outer radius |Assumed8 mm|Approximately14.5 mm;29 mm opposed span must be checked on both horns|
| Full outline |Assumed radius11 mm|Unknown; radius18 mm is a design clearance budget, NOT a measured outline|
| Small attachment bores |Unknown|Still unknown;2.3 mm is PRINTED clearance only|
| Installed height |35.5 mm to wing mating face|34 mm body-bottom to HIGHEST installed point; axial stack unresolved|
| Tabs / shaft offset |28 mm pitch;2 mm tabs;5.3 mm offset|Still provisional; generic MG90S dimensions were not substituted|

The4.5 mm pair conflicts with the present access opening: a provisional2.3 mm
printed hole overlaps the7 mm central hole by0.15 mm. The14.5 mm pair lies outside
the former tilt adapter's14 mm radius. No measured usable8 mm hole pair exists
in the evidence. These are specific reasons for local interface changes.

## Axial datum — 34 mm is NOT shaft projection

Define B as the measured body bottom, C as case top excluding shaft/horn, M as the
flat wing face contacting the print, T as tab mounting-contact face, and H as the
highest point. Measure B-to-C, B-to-M, T-to-M and B-to-H on both units.

If B-to-C is28.5 mm on matching datums,34 -28.5 =5.5 mm is C-to-H, not necessarily
C-to-M. The old model uses5 mm case-top-to-wing-underside plus2 mm wing thickness,
so B-to-M =35.5 mm, already1.5 mm above the reported highest point. Whether H
includes a hub or retaining screw remains unknown.

`InstalledHornOverallHeight=34` records evidence without driving a guessed mating
plane. `ServoShaftProjection=5` remains an unresolved legacy placeholder. Obtain
B-to-M and T-to-M before finalizing the pan shelf/washer and tilt servo location.
Any axial correction must rerun the tab-head/journal/fork checks. **Hold full
pedestal/forks/rotor printing until this stack and fastening method are resolved.**

## Local geometry changes

- Pan hole radius8 ->14.5; hub diameter28 ->38; journal cavity30 ->37; journal
  OD39.5 ->43.5; pedestal bore40 ->44 mm. Journal wall3.25 mm; diametral clearance
  remains0.5 mm. Thrust washer changes toID44.5 /OD50 /thickness2 mm.
- Journal length7 ->5.5 mm clears the checked4.5 mm diameter x2 mm high pan-tab
  screw-head budget by0.5 mm; bearing overlap remains3.5 mm. Actual head dimensions
  and the unresolved axial stack must still be measured.
- Tilt adapter is a40 mm rear disc4 mm thick plus36 mm nose2 mm thick. Total6 mm
  unchanged; fork opening28 ->38 mm. Two rear head recesses5.5 diameter x2.2 deep
  leave3.8 mm printed attachment grip and accept the assumed4.5 x2 mm heads below
  flush. Fit these screws before bolting the adapter to the cradle.
- A22 mm diameter x1 mm deep inner right-flange relief clears the existingM3x14
  adapter screw tails with a0.5 mm washer budget, leaving3 mm flange thickness.
  Different head/washer/nut stacks require rechecking.
- New PanHornCoupon copies the actual central rotor section. ServoFitCoupon is
  unchanged. The real TiltHornAdapter is the third small first-print test part.

Only Pedestal, PanRotor, RightFork and TiltHornAdapter changed among assembly
components. Boolean comparisons establish unchanged Base, BallastCover, LeftFork,
Cradle, CameraPlate, CableSaddle and ServoFitCoupon. No resin optimization occurred.

## Fastening and service access

Use the supplied matching centre screws. Prefer supplied tab screws only after
identifying their intended joint: a coarse screw does not establish compatibility
with a machine nut or printed clearance hole. Do not self-tap brittle resin.
Through-fastened tabs may require measured machine screws/nuts if the included
hardware cannot retain that joint.

Horn-to-print attachment is a separate function. Do not assume the kits include
four suitable attachment screws. Match diameter/thread to the actual horn pilots;
select length from grip plus usable engagement, checking exposed tips. Pan grip
is7 mm; tilt grip3.8 mm. Do not enlarge stock horn holes or trim arms to fit guessed
CAD. Through-bolts/nuts require a separate servo-side clearance check; they are
not validated by this candidate.

Fit the pan centre screw before installing the camera **plate and camera**.
For tilt, fit centre screw and recessed attachment screws while the adapter and
cradle are accessible, before the camera. Try the actual driver. For servicing,
remove camera/plate, disconnect power and support the cradle before undoing horn
or passive pivot. Printed parts must not rely on the centre screw alone for torque.

## Blank camera plate

CameraHoleEnabled=false; central mounting area remains blank and4 mm thick.
The four M3 plate-to-cradle countersinks remain. Remove the plate; support it on a
sacrificial backer before owner drilling. Mark the actual folded clip/insert,
keep clear of edges and structural fastener lands, and avoid heat/excess clamping.
Control resin dust. Do not drill until screw and position are established.

The cradle opening is24 x20 mm centred. For a screw-head/washer footprint radius r
centred at(x,y), require abs(x)+r <12 and abs(y)+r <10 mm plus practical tool/edge
clearance. Otherwise revise access before drilling. Verify thread/pitch/blind
depth and avoid bottoming. The unused6.35 mm /1.27 mm values are a1/4-20 candidate,
not a confirmed camera thread.

See FIRST_PRINT.md, SERVO_MEASUREMENTS.md and CAD_VALIDATION.md.
