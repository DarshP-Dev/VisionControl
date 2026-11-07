"""Executable arithmetic checks and schematic drawings; does NOT use a CAD kernel."""
import csv
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent

def calculate(p):
    g=9.80665;m=p['CameraMassG']/1000;b=p['AssumedMovingBracketMassG']/1000
    points=[]
    # Downward tilt is rotation about -X. Moment arm for weight is world Y.
    for i in range(141):
        a=math.radians(-p['TiltLimit']+2*p['TiltLimit']*i/140)
        yc=(p['CameraComY']*math.cos(a)+p['CameraComZ']*math.sin(a))/1000
        yb=(p['AssumedBracketComY']*math.cos(a)+p['AssumedBracketComZ']*math.sin(a))/1000
        points.append(abs(g*(m*yc+b*yb)))
    grav=max(points)
    uncertain=(m+b)*g*p['AssumedComUncertainty']/1000
    inertia=m*((p['CameraHeight']/1000)**2+(p['CameraDepth']/1000)**2)/12
    inertia+=m*(math.hypot(p['CameraComY'],p['CameraComZ'])/1000)**2
    inertia+=b*(.05**2+.035**2) # deliberately conservative point-mass bracket radius
    startup=inertia*p['AssumedAngularAcceleration']
    cable=p['AssumedCableForceN']*p['AssumedCableLever']/1000
    support=min(p['BaseWidth']/2-p['FootInset'],p['BaseDepth']/2-p['FootInset'])/1000
    fixed=p['AssumedFixedMassG']/1000;moving=p['AssumedTotalMovingMassG']/1000
    offset=moving*g*p['AssumedMovingComOffset']/1000
    external=p['AssumedDynamicLateralForceN']*p['AssumedPullHeight']/1000
    overturn=offset+external
    ballast=max(0.,p['TargetTipMargin']*overturn/(g*support)-fixed-moving)
    volume=2*p['BallastPocketWidth']*p['BallastPocketDepth']*p['BallastPocketHeight']/1000
    # Gross stock bounds per piece, minus only simple open spaces. Not BRep volume.
    w=p['Wall'];top=p['PanDeckZ']-p['ThrustWasherThickness'];base=p['BaseHeight']
    volumes={
      'Base':(p['BaseWidth']*p['BaseDepth']*base)/1000-volume,
      'BallastCover':(p['BaseWidth']-18)*(p['BaseDepth']-12)*3/1000,
      'Pedestal':(4*p['PostWidth']**2*(top-base-w)+2*p['TowerWidth']*p['TowerDepth']*w+p['PedestalFootWidth']*p['PedestalFootDepth']*w-math.pi*(p['JournalBore']/2)**2*w)/1000,
      'PanRotor':(math.pi*(p['PanDiameter']/2)**2*w+math.pi/4*((p['JournalBore']-p['DiametralClearance'])**2-p['JournalInnerDiameter']**2)*p['JournalLength']+math.pi*(p['PanHubDiameter']/2)**2*p['PanHubThickness'])/1000,
      'ForkPair':2*(p['ForkFootWidth']*p['ForkFootDepth']*w+w*p['ForkDepth']*(p['TiltAxisZ']+p['ForkAboveAxis']-p['PanDeckZ']-w)+2*10*4*22)/1000+8,
      'Cradle':((p['CradleInnerWidth']+2*w)*p['CradleDepth']*w+2*w*p['CradleSideDepth']*(p['CameraBottomBelowAxis']+2*w+p['CradleAboveAxis']))/1000,
      'CameraPlate':p['CradleInnerWidth']*p['CradleDepth']*w/1000,
      'TiltHornAdapter':math.pi*14**2*p['TiltAdapterThickness']/1000,
      'CableSaddle':24*10*8/1000,
      'ServoFitCoupon':((p['ServoTabPitch']+16)*(p['ServoDepth']+14)-(p['ServoWidth']+p['ServoFitClearance'])*(p['ServoDepth']+p['ServoFitClearance']))*w/1000}
    foot=p['FootThickness']-1
    return {'status':'ARITHMETIC_ONLY_NOT_CAD_VALIDATED','assumed_units':'mm, g; report torque N m',
      'optical_height_desk_mm':foot+p['TiltAxisZ']-p['CameraBottomBelowAxis']+p['OpticalHeightAboveCameraBottom'],
      'camera_clip_full_envelope_sweep_radius_mm':math.hypot(p['CameraDepth']/2,max(p['CameraBottomBelowAxis'],p['CameraHeight']-p['CameraBottomBelowAxis'])),
      'cradle_floor_corner_min_z_mm':p['TiltAxisZ']-(p['CameraBottomBelowAxis']+2*w)*math.cos(math.radians(p['TiltLimit']))-p['CradleDepth']/2*math.sin(math.radians(p['TiltLimit'])),
      'nominal_gravity_peak_Nm':grav,'additional_com_uncertainty_Nm':uncertain,'startup_inertia_Nm':startup,
      'assumed_usb_torque_Nm':cable,'conservative_sum_Nm':grav+uncertain+startup+cable,
      'advertised_stall_Nm':2*.0980665,'planning_screen_25pct_stall_Nm':.5*.0980665,
      'note_stall':'25% is an assumed screening budget, NOT a manufacturer continuous rating.',
      'stability':{'support_half_span_m':support,'offset_moment_Nm':offset,'external_moment_Nm':external,
          'no_ballast_tip_margin':(fixed+moving)*g*support/overturn,'required_ballast_g':ballast*1000,
          'tip_margin_with_250g':(fixed+moving+.25)*g*support/overturn,
          'gross_pocket_capacity_ml':volume,'ideal_solid_steel_capacity_g':volume*7.85,
          'note':'Assumed 0.5 N equivalent lateral load includes cable pull/startup/disturbance. No sliding test. Pocket hardware reduces capacity.'},
      'rough_resin_ml_by_part':volumes,'rough_resin_total_ml':sum(volumes.values()),
      'planning_resin_with_supports_ml':[sum(volumes.values())*1.25,sum(volumes.values())*1.45],
      'note_resin':'Gross primitive estimates, overlaps partly double-counted; exact Boolean volumes only after FreeCAD. Density assumed 1.15 g/ml.'}

def svg_file(path,title,elements,notes):
    text='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900">'
    text+='<rect width="1200" height="900" fill="#f8fafc"/><g font-family="Arial" fill="#172b42">'
    text+=f'<text x="45" y="45" font-size="26">{escape(title)}</text><text x="45" y="75" font-size="15">PRELIMINARY SCHEMATIC — mm — NOT A FREECAD RENDER — NOT TO SCALE</text>'
    text+=elements
    for i,n in enumerate(notes):text+=f'<text x="45" y="{765+i*23}" font-size="15">{escape(n)}</text>'
    path.write_text(text+'</g></svg>',encoding='utf-8')

def drawings(p):
    out=ROOT/'drawings';out.mkdir(exist_ok=True)
    def rect(x,y,w,h,c):return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}" stroke="#263e53" stroke-width="2"/>'
    def line(x1,y1,x2,y2):return f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="#526579" stroke-width="1.5"/>'
    def text(x,y,t,size=17):return f'<text x="{x}" y="{y}" font-size="{size}">{escape(str(t))}</text>'
    e=rect(130,625,440,56,'#96b5cc')+rect(238,377,224,248,'#c8d6e0')+rect(118,365,464,16,'#578caf')
    e+=rect(112,190,16,175,'#578caf')+rect(572,190,16,175,'#578caf')
    e+=rect(154,292,392,16,'#7fae9b')+rect(170,276,360,16,'#c2daca')+rect(186,92,328,184,'#dce1e7')
    e+=line(80,180,650,180)+text(660,186,f'Tilt axis Z {p["TiltAxisZ"]} above base bottom')
    e+=line(80,148,514,148)+text(660,150,f'Lens height: ~{p["FootThickness"]-1+p["TiltAxisZ"]-p["CameraBottomBelowAxis"]+p["OpticalHeightAboveCameraBottom"]:g} above desk (assumed)')
    e+=line(130,712,570,712)+line(130,688,130,724)+line(570,688,570,724)+text(285,707,f'Base {p["BaseWidth"]:g}')
    e+=text(650,280,'Camera envelope 82 W × 46 H × 45 D')+text(650,315,'Removable 90 × 52 × 4 blank plate')
    e+=text(650,350,'4 × M3 plate bolts: X ±34, Y ±18')+text(650,385,'Fork inner spacing: 108')
    e+=text(650,420,'Passive pivot: Ø5 shoulder / Ø8 bushing')+text(650,455,'Pan journal: Ø39.5 in Ø40')
    e+=text(650,490,'Pan deck Ø116 × 4; underside Z76')+text(650,525,'Pan ±60°; tilt ±35° target only')
    e+=text(650,560,'Body height includes clip; lens datum unmeasured')
    svg_file(out/'dimensioned_layout.svg','Freestanding webcam mount | preliminary dimension schedule',e,
      ['Origin: base bottom; +X right, +Y forward, +Z up. Feet add 4 mm desk clearance.',
       'Actual geometry and all movement clearances require FreeCAD execution plus physical interface checks.',
       'Camera mounting hole is DISABLED. Never force a provisional screw into the insert.'])
    # Exploded diagram intentionally schematic, showing assembly order and mechanical connections.
    e='';items=[('Camera + existing folding clip','Owner hardware; insert unverified',180,130,360,60,'#dce1e7'),
      ('CameraPlate','4 × M3 flush-head bolts to cradle',170,225,380,18,'#c2daca'),
      ('Cradle + horn adapter','Opposite pivot + stock servo horn',150,315,420,25,'#7fae9b'),
      ('LeftFork / RightFork','2 × M3 each to rotor; tilt servo on right',120,400,480,25,'#578caf'),
      ('PanRotor + stock horn','PTFE thrust washer; supported journal',115,485,490,18,'#578caf'),
      ('Pedestal + pan servo','Install servo before attaching to base',225,555,270,65,'#c8d6e0'),
      ('Base + captive nuts + ballast','Cover below; rubber feet clear cover',130,675,460,28,'#96b5cc')]
    e+=line(360,110,360,735)
    for name,desc,x,y,w,h,c in items:e+=rect(x,y,w,h,c)+text(640,y+8,name,20)+text(640,y+32,desc,14)
    svg_file(out/'exploded_schematic.svg','Exploded assembly sequence | schematic',e,
      ['Stock horns provide the splined interface. Printed adapters bolt to horns; no printed spline coupling.',
       'Pan thrust washer carries gravity load. Opposite tilt bushing supports the camera cradle.',
       'Rendered exploded FCStd/PNG is generated only when generate_freecad.build() runs successfully.'])
    rows=[['component','interface','coordinates_mm','hole_mm','status'],
      ['Base/Pedestal','4 mounting screws',f'X +/-{p["BaseBoltX"]}; Y +/-{p["BaseBoltY"]}',p['M3Clearance'],'M3; nut AF5.8 depth2.6'],
      ['Base/Cover','2 cover screws','X0; Y +/-40',p['M3Clearance'],'M3'],
      ['Rotor/Forks','4 screws',f'X +/-{p["ForkInnerHalfWidth"]-p["ForkBoltInset"]}; Y +/-{p["ForkBoltY"]}',p['M3Clearance'],'M3'],
      ['Cradle/Plate','4 screws',f'X +/-{p["PlateBoltX"]}; Y +/-{p["PlateBoltY"]}',p['M3Clearance'],'M3; plate countersink6.5x1.7 provisional'],
      ['Cradle/Adapter','2 screws','Y +/-9; Z128',p['M3Clearance'],'M3; along X'],
      ['Pan horn','2 screws','X +/-8; Y0',p['HornHoleDiameter'],'UNVERIFIED M2 candidate'],
      ['Tilt horn','2 screws','Y0; Z128 +/-8',p['HornHoleDiameter'],'UNVERIFIED M2 candidate'],
      ['Pan servo tabs','2 holes','X5.3 +/-14; Y0',p['ServoTabHole'],'UNVERIFIED'],
      ['Tilt servo tabs','2 holes','Y0; Z128+5.3 +/-14',p['ServoTabHole'],'UNVERIFIED'],
      ['Camera insert','disabled','X0; Y0','none','6.35 major/1.27 pitch placeholder ONLY'],
      ['Left pivot','shoulder bolt','Y0; Z128',p['PivotDiameter']+p['PivotClearance'],'5mm shoulder, M4 threaded tip; measure grip'],
      ['Left bushing seat','plain bushing','Y0; Z128',p['BushingOD']+p['BushingFitAllowance'],'8.2 slip seat; axial capture with washers']]
    with (out/'interface_schedule.csv').open('w',newline='') as f:csv.writer(f).writerows(rows)

def main():
    p=json.loads((ROOT/'parameters.json').read_text());result=calculate(p)
    (ROOT/'engineering_estimates.json').write_text(json.dumps(result,indent=2))
    drawings(p)
    print(json.dumps({k:v for k,v in result.items() if k!='rough_resin_ml_by_part'},indent=2))

if __name__=='__main__':main()
