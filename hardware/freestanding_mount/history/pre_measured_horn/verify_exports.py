"""Run with FreeCAD bundled Python after generation; reads actual exported files."""
import json
import sys
from pathlib import Path
import FreeCAD as App
import Part
import Mesh
from mount_geometry import PRINTED, PAN, TILT, shape_for, V

ROOT=Path(__file__).resolve().parent

def verify(directory):
    directory=Path(directory);p=json.loads((directory/'parameters_used.json').read_text())
    report={'freecad_version':App.Version(),'exports':{},'documents':{},'physical_validation':False}
    for n in PRINTED:
        original=shape_for(n,p);step=Part.read(str(directory/'step'/(n+'.step')))
        mesh=Mesh.Mesh(str(directory/'stl'/(n+'.stl')))
        item={'step_valid':step.isValid(),'step_solids':len(step.Solids),
              'step_volume_error_mm3':abs(step.Volume-original.Volume),
              'stl_closed':mesh.isSolid(),'stl_volume_error_percent':100*abs(abs(mesh.Volume)-original.Volume)/original.Volume,
              'stl_facets':mesh.CountFacets}
        assert item['step_valid'] and item['step_solids']==1 and item['step_volume_error_mm3']<.01,(n,item)
        assert item['stl_closed'] and item['stl_volume_error_percent']<1,(n,item)
        report['exports'][n]=item
    for filename in ('VisionControl_Assembly.FCStd','exploded_mount.FCStd'):
        doc=App.openDocument(str(directory/filename));doc.recompute()
        shapes=[o for o in doc.Objects if hasattr(o,'Shape')]
        assert all(not o.Shape.isNull() and o.Shape.isValid() for o in shapes)
        report['documents'][filename]={'opened':True,'valid_shapes':len(shapes)}
        if doc.getObject('Parameters'):
            before=doc.Cradle.Shape.CenterOfMass
            doc.Parameters.TiltAngle=10.;doc.recompute()
            after=doc.Cradle.Shape.CenterOfMass
            from mount_geometry import posed, values
            expected=posed('Cradle',values(doc.Parameters)).Solids[0].CenterOfMass
            assert (after-expected).Length<1e-6
            assert (after-before).Length>.1
            doc.Parameters.TiltAngle=0.;doc.recompute()
            assert (doc.Cradle.Shape.CenterOfMass-before).Length<1e-6
            report['documents'][filename]['parameter_recompute_roundtrip']=True
        App.closeDocument(doc.Name)
    audit=json.loads((directory/'geometry_audit.json').read_text())
    vols={n:item['volume_ml'] for n,item in audit['parts'].items()}
    density=p['AssumedResinDensity']
    fixed=sum(v for n,v in vols.items() if n not in PAN and n!='ServoFitCoupon')*density+13.6
    moving=sum(v for n,v in vols.items() if n in PAN)*density+96.3+13.6
    tilt_printed=sum(v for n,v in vols.items() if n in TILT)*density
    halfspan=min(p['BaseWidth']/2-p['FootInset'],p['BaseDepth']/2-p['FootInset'])/1000
    overturn=moving/1000*9.80665*.025+.5*.14
    report['mass_stability_screen']={'resin_density_assumption_g_ml':density,'fixed_g_excluding_fasteners':fixed,
       'moving_g_excluding_fasteners':moving,'tilt_printed_g':tilt_printed,
       'tip_ratio_250g_25mm_moving_com_offset_0_5N_pull':(fixed+moving+250)/1000*9.80665*halfspan/overturn,
       'required_ballast_g_for_ratio2':max(0,2*overturn/(9.80665*halfspan)*1000-fixed-moving),
       'notes':'Computed CAD resin mass plus specified camera/servo masses. Fasteners, washer and bushing omitted; COM uncertainty is an assumed 25mm moving-group offset.'}
    report['motion_centres']=[]
    shapes={n:shape_for(n,p) for n in PRINTED if n!='ServoFitCoupon'}
    for pan in (-60,0,60):
        for tilt in (-35,0,35):
            weighted=V();total=0
            for n,s in shapes.items():
                c=V(s.Solids[0].CenterOfMass);mass=s.Volume/1000*density
                if n in TILT:c=App.Rotation(V(1,0,0),-tilt).multVec(c-V(0,0,p['TiltAxisZ']))+V(0,0,p['TiltAxisZ'])
                if n in PAN:c=App.Rotation(V(0,0,1),-pan).multVec(c)
                weighted+=c*mass;total+=mass
            for n,mass in [('CameraEnvelope',96.3),('PanServoEnvelope',13.6),('TiltServoEnvelope',13.6)]:
                from mount_geometry import posed
                c=posed(n,dict(p,PanAngle=pan,TiltAngle=tilt)).Solids[0].CenterOfMass
                weighted+=c*mass;total+=mass
            weighted+=V(0,0,5)*250;total+=250
            c=weighted/total
            report['motion_centres'].append({'pan':pan,'tilt':tilt,'estimated_com_with_250g_mm':[c.x,c.y,c.z],
               'note':'Envelope camera COM; no measured balance or cable; add4mm for desk-height datum'})
    (directory/'export_verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report['mass_stability_screen'],indent=2))
    print('Verified',len(report['exports']),'STL/STEP pairs and both FCStd documents')

if __name__=='__main__':verify(sys.argv[1] if len(sys.argv)>1 else ROOT/'output_verified')
