"""Run from FreeCAD's Python console; see README. Never controls hardware.

Creates editable assembly, component STEP/STL, projected SVG sheets, exploded
FCStd, and a JSON geometry audit. It refuses to overwrite an existing output dir.
"""
import json
import math
from pathlib import Path
import FreeCAD as App
import Part
import MeshPart
from mount_geometry import PRINTED, REFERENCE, PAN, TILT, Component, shape_for, posed, validate, values, V

ROOT=Path(__file__).resolve().parent

def export_sheet(shape,name,path):
    import TechDraw
    from xml.sax.saxutils import escape
    b=shape.BoundBox
    snippets=[]
    # Projection is kernel-derived. Envelope dimensions are tabulated, not hole callouts.
    for normal,cx,cy,label in [(V(0,-1,0),105,100,'FRONT'),(V(0,0,1),280,100,'TOP'),(V(1,0,0),105,245,'SIDE')]:
        local=shape.copy();local.translate(-b.Center)
        svg=TechDraw.projectToSVG(local,normal)
        snippets.append(f'<g transform="translate({cx},{cy}) scale(1,-1)">{svg}</g><text x="{cx-25}" y="{cy+70}">{label}</text>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
        '<rect width="420" height="297" fill="white"/><g font-family="sans-serif" font-size="4">'
        f'<text x="10" y="10">{escape(name)} — PROVISIONAL; mm; projection scale 1:1 at 100% print</text>'
        f'<text x="220" y="230">Envelope X {b.XLength:.2f} / Y {b.YLength:.2f} / Z {b.ZLength:.2f} mm</text>'
        '<text x="220" y="240">Hole coordinates: drawings/interface_schedule.csv</text>'
        '<text x="220" y="250">Fit coupon and physical interface verification required</text>'
        +''.join(snippets)+'</g></svg>',encoding='utf-8')

def collision_sweep(p):
    """Sampled rigid-solid interference, not continuous proof or cable simulation."""
    names=[n for n in PRINTED if n!='ServoFitCoupon']+REFERENCE
    # Contact surfaces are not ignored; only volume >0.1mm3 is reported.
    results=[]
    for pan in (-p['PanLimit'],0,p['PanLimit']):
        for tilt in (-p['TiltLimit'],-p['TiltLimit']/2,0,p['TiltLimit']/2,p['TiltLimit']):
            q=dict(p,PanAngle=pan,TiltAngle=tilt)
            shapes={n:posed(n,q) for n in names}
            hits=[]
            for i,a in enumerate(names):
                for b in names[i+1:]:
                    volume=shapes[a].common(shapes[b]).Volume
                    if volume>.1:hits.append({'a':a,'b':b,'intersection_mm3':volume})
            results.append({'pan':pan,'tilt':tilt,'intersections':hits})
    return results

def build(output=None):
    p=json.loads((ROOT/'parameters.json').read_text());validate(p)
    output=Path(output) if output else ROOT/'generated'
    output.mkdir(parents=True,exist_ok=False)
    for d in ('stl','step','drawings'): (output/d).mkdir()
    doc=App.newDocument('FreestandingMount')
    params=doc.addObject('App::FeaturePython','Parameters')
    for key,value in p.items():
        typ='App::PropertyBool' if isinstance(value,bool) else 'App::PropertyInteger' if isinstance(value,int) else 'App::PropertyFloat'
        params.addProperty(typ,key,'Dimensions and assumptions', 'Provisional: see measurement checklist').__setattr__(key,value)
    components=[]
    for name in PRINTED+REFERENCE:
        obj=doc.addObject('Part::FeaturePython',name);Component(obj,name,params)
        if App.GuiUp:
            obj.ViewObject.ShapeColor=(.3,.55,.75) if name in PRINTED else (.65,.65,.65)
            if name in REFERENCE:obj.ViewObject.Transparency=65
            if name=='ServoFitCoupon':obj.ViewObject.Visibility=False
        components.append(obj)
    doc.recompute()
    audit={'status':'KERNEL_EXECUTED_PROVISIONAL','freecad_version':list(App.Version()),'parts':{},'drawing_errors':[],
           'warning':'No mechanical certification. Collision sampling omits cable, screws and detailed clip/servo/horn geometry.'}
    for name in PRINTED:
        # Neutral component geometry, positioned on Z=0 for individual exports.
        s=shape_for(name,dict(p,PanAngle=0.,TiltAngle=0.))
        if s.isNull() or not s.isValid() or len(s.Solids)!=1:
            raise RuntimeError(f'{name}: invalid or disconnected solid; no completed assembly export')
        b=s.BoundBox;s.translate(V(-b.XMin,-b.YMin,-b.ZMin))
        b=s.BoundBox
        fits=any(a<=192 and c<=120 and h<=245 for a,c,h in [(b.XLength,b.YLength,b.ZLength),(b.YLength,b.XLength,b.ZLength),
                  (b.XLength,b.ZLength,b.YLength),(b.ZLength,b.XLength,b.YLength),(b.YLength,b.ZLength,b.XLength),(b.ZLength,b.YLength,b.XLength)])
        mesh=MeshPart.meshFromShape(Shape=s,LinearDeflection=.08,AngularDeflection=.25,Relative=False)
        if not mesh.isSolid(): raise RuntimeError(name+': mesh is not closed')
        mesh.write(str(output/'stl'/(name+'.stl')))
        s.exportStep(str(output/'step'/(name+'.step')))
        try: export_sheet(s,name,output/'drawings'/(name+'.svg'))
        except Exception as e:audit['drawing_errors'].append({'part':name,'error':str(e)})
        audit['parts'][name]={'volume_ml':s.Volume/1000,'estimated_mass_g':s.Volume/1000*p['AssumedResinDensity'],
            'bbox_mm':[b.XLength,b.YLength,b.ZLength],'fits_bare_build_volume_some_orientation':fits,'solid_count':len(s.Solids),'valid':s.isValid()}
    audit['sampled_collisions']=collision_sweep(p)
    audit['collision_free_at_samples']=not any(x['intersections'] for x in audit['sampled_collisions'])
    audit['printed_volume_ml']=sum(v['volume_ml'] for k,v in audit['parts'].items() if k!='ServoFitCoupon')
    (output/'geometry_audit.json').write_text(json.dumps(audit,indent=2))
    (output/'parameters_used.json').write_text(json.dumps(p,indent=2))
    doc.recompute();doc.saveAs(str(output/'freestanding_mount.FCStd'))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll()
        Gui.activeDocument().activeView().saveImage(str(output/'assembly.png'),1600,1200,'White')
    exp=App.newDocument('ExplodedMount')
    for n in PRINTED:
        if n=='ServoFitCoupon':continue
        o=exp.addObject('Part::Feature',n);s=shape_for(n,p)
        dx=(-50 if n=='LeftFork' else 50 if n in ('RightFork','TiltHornAdapter') else 0)
        dz={'Base':0,'BallastCover':-25,'Pedestal':30,'PanRotor':70,'LeftFork':95,'RightFork':95,
            'Cradle':145,'CameraPlate':170,'TiltHornAdapter':145,'CableSaddle':100}[n]
        s.translate(V(dx,0,dz));o.Shape=s
    exp.recompute();exp.saveAs(str(output/'exploded_mount.FCStd'))
    if App.GuiUp:
        Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll()
        Gui.activeDocument().activeView().saveImage(str(output/'exploded.png'),1600,1600,'White')
    print('Generated PROVISIONAL exports:',output)
    print('Sample collisions:',sum(len(v['intersections']) for v in audit['sampled_collisions']))
    print('Inspect geometry_audit.json; a generated file is not a print release.')
    return doc,audit

if __name__=='__main__':build()
