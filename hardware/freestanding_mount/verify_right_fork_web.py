"""Local reinforcement checks; section areas are geometric, not a strength test."""
import json,sys,math
from pathlib import Path
from mount_geometry import PRINTED,REFERENCE,shape_for,box,cyl,V

ROOT=Path(__file__).resolve().parent
def verify(directory):
    out=Path(directory)
    before=json.loads((ROOT/'history/pre_right_fork_web/parameters.json').read_text())
    after=json.loads((out/'parameters_used.json').read_text())
    report={'physical_load_tested':False,'parts':{}}
    for n in PRINTED+REFERENCE:
        a=shape_for(n,before);b=shape_for(n,after)
        removed=a.cut(b);added=b.cut(a)
        assert b.isValid()
        if n!='RightFork':assert removed.Volume+added.Volume<1e-6,n
        else:
            assert len(b.Solids)==1 and removed.Volume<1e-6
            # Added material must be only on outer lower segment, below the
            # original flange bottom; upper servo frame stays EXACTLY unchanged.
            region=box(4,30,28,60,0,84)
            assert added.cut(region).Volume<1e-6
            delta_bounds=added.BoundBox
            report['addition_bounds_xyz_mm']=[[delta_bounds.XMin,delta_bounds.XMax],
                [delta_bounds.YMin,delta_bounds.YMax],[delta_bounds.ZMin,delta_bounds.ZMax]]
            # Average horizontal material area in a10-micron slab immediately
            # below the flange. A reproducible geometric indicator of load path.
            slab=box(200,200,.01,0,0,111.99)
            old_area=a.common(slab).Volume/.01;new_area=b.common(slab).Volume/.01
            report['section_below_flange']={'z_slab_mm':[111.99,112.],
                'old_area_mm2':old_area,'new_area_mm2':new_area,'ratio':new_area/old_area,
                'note':'Not stress, FEA, strength or fatigue certification.'}
            # Cylindrical access budgets for M3 foot bolts remain clear to a
            # straight6mm driver/head envelope well above the foot.
            access=[]
            for y in (-12,12):
                tool=cyl(6,50,50,y,84)
                v=b.common(tool).Volume
                assert v<1e-6
                access.append({'y_mm':y,'intersection_mm3':v})
            report['foot_bolt_tool_access_6mm']=access
        report['parts'][n]={'removed_mm3':removed.Volume,'added_mm3':added.Volume,
            'new_solid_ml':b.Volume/1000}
    report['passed']=True
    (out/'right_fork_web_verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='parts'},indent=2))
    print('RightFork:',report['parts']['RightFork'])
if __name__=='__main__':verify(sys.argv[1])
