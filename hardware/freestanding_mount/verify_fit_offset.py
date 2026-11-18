"""Verify the 2026-11-16 positional correction against the preceding geometry."""
import json
import math
import sys
from pathlib import Path
from mount_geometry import shape_for, PRINTED, REFERENCE, cyl, union, V

ROOT=Path(__file__).resolve().parent

def verify(directory):
    out=Path(directory)
    before=json.loads((ROOT/'history/pre_fit_offset/parameters.json').read_text())
    after=json.loads((out/'parameters_used.json').read_text())
    changed={'PanRotor','PanHornCoupon','TiltHornAdapter'}
    assert {k for k in after if after[k]!=before.get(k)}=={'PanHornOffsetY','TiltHornOffsetY'}
    assert after['PanHornOffsetY']==after['TiltHornOffsetY']==.1
    report={'physical_alignment_verified':False,'parts':{},'coordinate_convention':
        'View horn-contact face: pan +X right / normal -Z; tilt +Z right / normal +X. Screen down is +Y. Unmarked-part 180-degree orientation remains a physical assumption.'}
    for n in PRINTED+REFERENCE:
        old=shape_for(n,before);new=shape_for(n,after)
        assert new.isValid()
        delta=old.cut(new).fuse(new.cut(old))
        row={'symmetric_difference_mm3':delta.Volume,'volume_change_mm3':new.Volume-old.Volume}
        if n not in changed:
            assert delta.Volume<1e-6,(n,delta.Volume)
        else:
            is_tilt=n=='TiltHornAdapter'
            tools=[]
            for sign in (-1,1):
                for y in (0.,.1):
                    tools.append(cyl(2.3,300,-100,y,128+sign*14.5,V(1,0,0)) if is_tilt else cyl(2.3,300,sign*14.5,y,-100))
            excess=delta.cut(union(tools)).Volume
            assert excess<1e-6,(n,excess)
            assert abs(new.Volume-old.Volume)<1e-5
            row['changed_material_outside_old_and_new_bores_mm3']=excess
            bores=[];recesses=[]
            for face in new.Faces:
                s=face.Surface
                if not hasattr(s,'Radius'):continue
                if abs(s.Radius-1.15)<1e-7:
                    bores.append([s.Center.y,s.Center.z] if is_tilt else [s.Center.x,s.Center.y])
                if is_tilt and abs(s.Radius-2.75)<1e-7:
                    recesses.append([s.Center.y,s.Center.z])
            expected=[[.1,113.5],[.1,142.5]] if is_tilt else [[-14.5,.1],[14.5,.1]]
            assert len(bores)==2
            assert all(any(math.dist(a,b)<1e-6 for b in bores) for a in expected)
            assert abs(math.dist(*bores)-29)<1e-6
            if is_tilt:
                assert len(recesses)==2
                assert all(any(math.dist(a,b)<1e-6 for b in recesses) for a in [[0,113.5],[0,142.5]])
            row.update(bore_centres=bores,diameter_mm=2.3,spacing_mm=math.dist(*bores),fixed_recess_centres=recesses)
        report['parts'][n]=row
    radial=math.hypot(14.5,.1)
    report['material_and_clearance']={
        'pan_hub_edge_ligament_before_after_mm':[19-14.5-1.15,19-radial-1.15],
        'tilt_nose_edge_ligament_before_after_mm':[18-14.5-1.15,18-radial-1.15],
        'tilt_head_recess_edge_ligament_mm':20-14.5-2.75,
        'tilt_remaining_axial_grip_mm':6-2.2,
        'assumed_4_5mm_head_radial_clearance_in_fixed_recess_mm':(5.5-4.5)/2-.1,
        'note':'No strength certification; actual screw seating and corrected alignment need repeat fit test. Diameters, recess depth and bulk material outside bore relocation unchanged.'}
    report['passed']=True
    (out/'fit_offset_verification.json').write_text(json.dumps(report,indent=2))
    print('Offset verification passed: only three intended solids changed; bore diameter/spacing and fixed recess centres verified.')

if __name__=='__main__':verify(sys.argv[1])
