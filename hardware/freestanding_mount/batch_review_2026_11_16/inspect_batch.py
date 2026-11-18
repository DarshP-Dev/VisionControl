"""Read-only CAD/STL inspection; writes this review's JSON only. No slicer work."""
from pathlib import Path
import json,sys,math,hashlib
import FreeCAD
import Mesh
OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
sys.path.insert(0,str(ROOT))
from mount_geometry import shape_for,PRINTED
p=json.loads((ROOT/'output_fit_offset_2026_11_16/parameters_used.json').read_text())
result={'stls':{},'sensitivity':{},'layout_slicer_validated':False}
for n in PRINTED:
    path=ROOT/'output_fit_offset_2026_11_16/stl'/(n+'.stl')
    m=Mesh.Mesh(str(path));b=m.BoundBox
    assert m.isSolid(),n
    result['stls'][n]={'solid_ml':abs(m.Volume)/1000,'bbox_mm':[b.XLength,b.YLength,b.ZLength],
        'closed':True,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
for key,value in [('ServoShaftProjection',3.5),('ThrustWasherThickness',3.),
                  ('PanHornOffsetY',0.),('TiltHornOffsetY',0.),('BushingOD',8.5),('PivotDiameter',5.5)]:
    changed=[]
    for n in PRINTED:
        a=shape_for(n,p);b=shape_for(n,dict(p,**{key:value}))
        if a.cut(b).Volume+b.cut(a).Volume>1e-5:changed.append(n)
    result['sensitivity'][key]={'trial_value':value,'changed_parts':changed}
# Bounds of rotated bounding boxes deliberately overestimate the bare footprints.
# No shape rotations are saved; these are planning envelopes, not supports.
layout=[]
for n,axis,angle in [('Base','Y',65),('BallastCover','X',65),('PanHornCoupon','Y',45),('TiltHornAdapter','Y',45)]:
    x,y,z=result['stls'][n]['bbox_mm']
    if n=='TiltHornAdapter':x,y,z=y,z,x # Put circular mating face inXY first.
    t=math.radians(angle)
    w=x*math.cos(t)+z*math.sin(t) if axis=='Y' else x
    d=y*math.cos(t)+z*math.sin(t) if axis=='X' else y
    h=(x if axis=='Y' else y)*math.sin(t)+z*math.cos(t)
    if n in ('PanHornCoupon','TiltHornAdapter'):
        diameter,thickness=(43.5,9.5) if n=='PanHornCoupon' else (40.,6.)
        # Every orientation of the enclosing cylinder fits this cube. Preserve
        # the prior successful test orientation rather than changing fit conditions.
        w=d=h=math.hypot(diameter,thickness)
        axis='reuse prior successful test orientation';angle=None
    if n=='Base':left,bottom=5.,5.
    elif n=='BallastCover':left,bottom=5+layout[0]['reserved_footprint_mm'][0]+5,5.
    elif n=='PanHornCoupon':left,bottom=layout[1]['origin_xy_mm'][0],5+layout[1]['reserved_footprint_mm'][1]+5
    else:left,bottom=layout[2]['origin_xy_mm'][0]+layout[2]['reserved_footprint_mm'][0]+5,layout[2]['origin_xy_mm'][1]
    assert left+w+8<=187 and bottom+d+8<=115
    layout.append({'part':n,'axis_of_flat_part':axis,'angle_deg_from_flat':angle,
        'origin_xy_mm':[left,bottom],'bare_projected_bbox_mm':[w,d,h],
        'reserved_footprint_mm':[w+8,d+8],'height_with_8mm_lift_mm':h+8})
for i,a in enumerate(layout):
    for b in layout[i+1:]:
        ax,ay=a['origin_xy_mm'];aw,ad=a['reserved_footprint_mm']
        bx,by=b['origin_xy_mm'];bw,bd=b['reserved_footprint_mm']
        assert ax+aw<=bx or bx+bw<=ax or ay+ad<=by or by+bd<=ay
result['layout']=layout
result['planning_allowances']={'plate_mm':[192,120,245],'edge_mm':5,'gap_between_reserved_envelopes_mm':5,
    'lateral_support_allowance_each_side_mm':4,'assumed_lift_above_plate_mm':8,
    'warning':'No supports/rafts or slices generated. Real supports may exceed these allowances. Orientation signs must be chosen for drainage.'}
(OUT/'inspection.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'sensitivity':result['sensitivity'],'layout':layout},indent=2))
