"""Kernel checks of measured-hole revision and explicitly assumed hardware budgets.

Does not model real screw threads or establish actual hardware fit. Run on each
new generated directory; reports failures without silently altering geometry.
"""
import json
import math
import sys
from pathlib import Path
import FreeCAD as App
from mount_geometry import shape_for, cyl, union, PRINTED, COUPONS, PAN, TILT, V

ROOT=Path(__file__).resolve().parent

def check(directory):
    directory=Path(directory)
    p=json.loads((directory/'parameters_used.json').read_text())
    shapes={n:shape_for(n,p) for n in PRINTED if n not in COUPONS}
    from mount_geometry import REFERENCE
    shapes.update({n:shape_for(n,p) for n in REFERENCE})
    az=p['TiltAxisZ']; deck=p['PanDeckZ']; x=p['CradleInnerWidth']/2+p['Wall']
    r=p['HornHoleRadius']; d=p['AssumedHornScrewHeadDiameter']; h=p['AssumedHornScrewHeadHeight']
    top=deck-p['ServoShaftProjection']-p['HornThickness']-p['PanHubThickness']
    budget={
        'pan_attachment_heads':union([cyl(d,h,s*r,0,deck+p['Wall']) for s in (-1,1)]),
        'tilt_attachment_heads':union([cyl(d,h,x+p['HornHeadRecessDepth']-h,0,az+s*r,V(1,0,0)) for s in (-1,1)]),
        'pan_tab_heads':union([cyl(d,h,p['ServoShaftOffset']+s*p['ServoTabPitch']/2,0,top+p['ServoTabThickness']) for s in (-1,1)]),
        'tilt_tab_heads':union([cyl(d,h,p['ForkInnerHalfWidth']+2*p['Wall']+p['ServoTabThickness'],0,az+p['ServoShaftOffset']+s*p['ServoTabPitch']/2,V(1,0,0)) for s in (-1,1)]),
        'tilt_adapter_M3_heads':union([cyl(6,3,x-p['Wall']-3.5,y,az,V(1,0,0)) for y in (-p['AdapterBoltRadius'],p['AdapterBoltRadius'])]),
        'tilt_adapter_M3_shafts':union([cyl(3,14,x-p['Wall']-.5,y,az,V(1,0,0)) for y in (-p['AdapterBoltRadius'],p['AdapterBoltRadius'])]),
        'tilt_adapter_M3_nut_budgets':union([cyl(6.4,2.4,x+p['TiltAdapterThickness'],y,az,V(1,0,0)) for y in (-p['AdapterBoltRadius'],p['AdapterBoltRadius'])]),
        'pan_centre_head':cyl(p['AssumedCentreScrewHeadDiameter'],p['AssumedCentreScrewProjection'],0,0,deck-p['PanHubThickness']),
        'tilt_centre_head':cyl(p['AssumedCentreScrewHeadDiameter'],p['AssumedCentreScrewProjection'],x+p['TiltAdapterThickness']-p['AssumedCentreScrewProjection'],0,az,V(1,0,0)),
    }
    # Cylindrical budgets are deliberately larger than typical head outlines;
    # they are accommodation targets, not measurements of supplied screws.
    neutral=[]
    for name,b in budget.items():
        for part,s in shapes.items():
            if 'Envelope' in part and ('Horn' in part):continue
            vol=b.common(s).Volume if b.BoundBox.intersect(s.BoundBox) else 0
            if vol>.01:neutral.append({'hardware_budget':name,'part':part,'intersection_mm3':vol})
    # Complete rotational sweep of head discs about an axis is an annular cylinder.
    # Fixed members of the opposite group must clear this conservative 360deg set.
    tilt_sweeps=[]
    for name in ('tilt_attachment_heads','tilt_adapter_M3_heads','tilt_adapter_M3_nut_budgets','tilt_adapter_M3_shafts'):
        b=budget[name].BoundBox
        radius=r if name=='tilt_attachment_heads' else p['AdapterBoltRadius']
        head_radius=d/2 if name=='tilt_attachment_heads' else (3 if name.endswith('_heads') else (1.5 if name.endswith('_shafts') else 3.2))
        sweep=cyl(2*(radius+head_radius),b.XLength,b.XMin,0,az,V(1,0,0)).cut(cyl(2*(radius-head_radius),b.XLength+2,b.XMin-1,0,az,V(1,0,0)))
        for part in ('RightFork','LeftFork','PanRotor','TiltServoEnvelope'):
            s=shapes[part];vol=sweep.common(s).Volume if sweep.BoundBox.intersect(s.BoundBox) else 0
            tilt_sweeps.append({'budget':name,'part':part,'intersection_mm3':vol,'clearance_mm':sweep.distToShape(s)[0]})
    # Journal is axially symmetric, so a neutral pan-tab-head intersection proves
    # interference at EVERY pan angle, not merely at a sampled endpoint.
    journal=shapes['PanRotor']
    tabgap=budget['pan_tab_heads'].distToShape(journal)[0]
    drivers={
        'pan_before_camera_and_plate_install':cyl(4,80,0,0,deck-p['PanHubThickness']),
        'tilt_before_camera_install':cyl(4,x+p['TiltAdapterThickness'],0,0,az,V(1,0,0)),
    }
    driver_hits=[]
    for name,b in drivers.items():
        for part,s in shapes.items():
            if part=='CameraEnvelope' or ('Horn' in part and 'Envelope' in part):continue
            if name=='pan_before_camera_and_plate_install' and part=='CameraPlate':continue
            vol=b.common(s).Volume if b.BoundBox.intersect(s.BoundBox) else 0
            if vol>.01:driver_hits.append({'path':name,'part':part,'intersection_mm3':vol})
    # Check that the six unrelated assembly components have identical material.
    old=json.loads((ROOT/'history/pre_measured_horn/parameters.json').read_text())
    unchanged={}
    for n in ('Base','BallastCover','LeftFork','Cradle','CameraPlate','CableSaddle','ServoFitCoupon'):
        a=shape_for(n,old);b=shape_for(n,p)
        delta=a.cut(b).Volume+b.cut(a).Volume
        assert delta<.001,(n,delta)
        unchanged[n]=delta
    # Probe actual BReps at the selected measured centres, independently of the
    # hole-loop implementation. The central camera area must still be material.
    hole_probes={}
    for sign in (-1,1):
        probes=[('pan',cyl(2.2,7,sign*14.5,0,deck-3),'PanRotor'),
                ('tilt',cyl(2.2,6,x,0,az+sign*14.5,V(1,0,0)),'TiltHornAdapter')]
        for label,probe,part in probes:
            volume=probe.common(shapes[part]).Volume
            assert volume<1e-5,(label,sign,volume)
            hole_probes[label+str(sign)]=volume
    plate=shapes['CameraPlate'];probe=cyl(2,4,0,0,plate.BoundBox.ZMin)
    assert abs(probe.common(plate).Volume-probe.Volume)<1e-5
    assert abs(plate.BoundBox.ZLength-4)<1e-6
    # Updated torque screen uses current CAD printed masses/COM. Camera COM remains
    # the owner's unmeasured provisional datum, with a separate uncertainty moment.
    tilt_parts=[shapes[n] for n in PRINTED if n in TILT]
    density=p['AssumedResinDensity']
    bracket_mass=sum(s.Volume/1000*density for s in tilt_parts)/1000
    yc=sum(s.Volume/1000*density*s.Solids[0].CenterOfMass.y for s in tilt_parts)/(bracket_mass*1000)
    zc=sum(s.Volume/1000*density*(s.Solids[0].CenterOfMass.z-az) for s in tilt_parts)/(bracket_mass*1000)
    import engineering
    torque=engineering.calculate(dict(p,AssumedMovingBracketMassG=bracket_mass*1000,AssumedBracketComY=yc,AssumedBracketComZ=zc))
    report={'status':'KERNEL_CHECKED_ASSUMED_HARDWARE_BUDGETS_ONLY','physical_fit_verified':False,
        'neutral_budget_intersections':neutral,'full_360deg_tilt_head_sweeps':tilt_sweeps,
        'pan_tab_head_to_rotor_clearance_mm':tabgap,'driver_path_intersections_without_camera':driver_hits,
        'unchanged_component_symmetric_difference_mm3':unchanged,
        'selected_hole_probe_material_mm3':hole_probes,'blank_4mm_camera_plate_probe_pass':True,
        'dimensions':{'camera_plate_thickness_mm':shapes['CameraPlate'].BoundBox.ZLength,
            'horn_hole_radius_mm':r,'journal_wall_mm':(p['JournalBore']-p['DiametralClearance']-p['JournalInnerDiameter'])/2,
            'journal_bearing_axial_overlap_mm':max(0,min(deck,deck-p['ThrustWasherThickness'])-max(deck-p['JournalLength'],deck-p['ThrustWasherThickness']-p['Wall'])),
            'hub_to_access_radial_budget_mm':(p['HornCenterAccess']-p['HornHubDiameter'])/2,
            'horn_to_pan_cavity_radial_budget_mm':p['JournalInnerDiameter']/2-p['HornRadius'],
            'tilt_horn_to_fork_radial_budget_mm':p['TiltHornOpeningDiameter']/2-p['HornRadius'],
            'tilt_effective_attachment_grip_mm':p['TiltAdapterThickness']-p['HornHeadRecessDepth']},
        'installed_height':{'user_body_bottom_to_highest_point_mm':p['InstalledHornOverallHeight'],
            'cad_body_bottom_to_wing_mating_face_mm':p['ServoHeight']+p['ServoShaftProjection']+p['HornThickness'],
            'difference_mm':p['ServoHeight']+p['ServoShaftProjection']+p['HornThickness']-p['InstalledHornOverallHeight'],
            'resolved':False,'reason':'Highest point is not established as wing mating face. Hub and retaining-head stack remain unmeasured; no final axial fit release.'},
        'torque_screen':{k:torque[k] for k in ('nominal_gravity_peak_Nm','additional_com_uncertainty_Nm','startup_inertia_Nm','assumed_usb_torque_Nm','conservative_sum_Nm','planning_screen_25pct_stall_Nm','note_stall')},
        'tilt_printed_mass_g':bracket_mass*1000,
        'limitations':['Screw heads are assumed clearance budgets; supplied thread, length, engagement and washer sizes unknown.',
            'No real horn outline, hub projection, cable or supplied-screw-tip solid. M3x14 shafts ARE included. No strength/creep/FEA certification.',
            'Head sweeps are continuous for tilt relative to fork; main compound motion is the separate 375-pose sampled test.',
            'A 4mm driver budget applies before camera installation; pan also requires camera plate removal. Actual driver must be tried.',
            'Torque omits fastener mass and joint friction. Cable and COM uncertainty are assumed.']}
    report['assumed_budget_checks_pass']=not neutral and not driver_hits and all(t['intersection_mm3']<.01 for t in tilt_sweeps)
    (directory/'interface_verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    assert report['assumed_budget_checks_pass'],'Hardware-budget interference; inspect interface_verification.json'
    return report

if __name__=='__main__':check(sys.argv[1])
