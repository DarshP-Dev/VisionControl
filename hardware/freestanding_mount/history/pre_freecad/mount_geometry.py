"""FreeCAD-only parametric preliminary mount. Units mm, degrees, grams.

No FreeCAD execution has occurred at delivery. Keep this module beside the FCStd
and on sys.path when reopening so FeaturePython proxies can recompute.
"""
import math
import FreeCAD as App
import Part

V = App.Vector
PRINTED = ['Base', 'BallastCover', 'Pedestal', 'PanRotor', 'LeftFork',
           'RightFork', 'Cradle', 'CameraPlate', 'TiltHornAdapter', 'CableSaddle',
           'ServoFitCoupon']
REFERENCE = ['CameraEnvelope', 'PanServoEnvelope', 'TiltServoEnvelope',
             'PanHornEnvelope', 'TiltHornEnvelope', 'ThrustWasher', 'PivotBushing']
TILT = {'Cradle','CameraPlate','TiltHornAdapter','CameraEnvelope','TiltHornEnvelope'}
PAN = TILT | {'PanRotor','LeftFork','RightFork','TiltServoEnvelope','PivotBushing','CableSaddle'}

def box(w,d,h,x=0,y=0,z=0):
    return Part.makeBox(w,d,h,V(x-w/2,y-d/2,z))

def cyl(d,h,x=0,y=0,z=0,direction=V(0,0,1)):
    return Part.makeCylinder(d/2,h,V(x,y,z),direction)

def union(parts):
    result=parts[0]
    for part in parts[1:]: result=result.fuse(part)
    return result.removeSplitter()

def holes(shape,points,d,length=300,axis='z'):
    for a,b in points:
        cutter = cyl(d,length,a,b,-100) if axis=='z' else cyl(d,length,-100,a,b,V(1,0,0))
        shape=shape.cut(cutter)
    return shape

def nut_prism(af,depth,x,y,z):
    r=af/math.sqrt(3)
    pts=[V(x+r*math.cos(i*math.pi/3),y+r*math.sin(i*math.pi/3),z) for i in range(6)]
    return Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(V(0,0,depth))

def values(obj):
    return {k:getattr(obj,k) for k in obj.PropertiesList if k not in ('Label','Label2','ExpressionEngine','Visibility') and not k.startswith('_')}

def validate(p):
    required=['Wall','BaseWidth','BaseDepth','BaseHeight','ServoWidth','ServoDepth','ServoHeight','PanDiameter','TiltAxisZ']
    if any(not math.isfinite(p[k]) or p[k]<=0 for k in required): raise ValueError('Invalid dimensions')
    if p['Wall']<3: raise ValueError('Starting structural wall must be >=3 mm')
    if p['CradleInnerWidth']<p['CameraWidth']+4: raise ValueError('Insufficient camera side clearance')
    if p['ForkInnerHalfWidth']<=p['CradleInnerWidth']/2+p['Wall']+2: raise ValueError('Insufficient tilt side clearance')
    if abs(p['PanAngle'])>p['PanLimit'] or abs(p['TiltAngle'])>p['TiltLimit']: raise ValueError('Requested pose exceeds target limits')
    if not 0<p['DiametralClearance']<2: raise ValueError('Invalid journal clearance')

def shape_for(kind,p):
    validate(p)
    w=p['Wall']; bz=p['BaseHeight']; deck=p['PanDeckZ']; az=p['TiltAxisZ']; f=p['ForkInnerHalfWidth']
    half=p['CradleInnerWidth']/2; bottom=az-p['CameraBottomBelowAxis']; floor=bottom-2*w
    mount=[(x,y) for x in (-p['BaseBoltX'],p['BaseBoltX']) for y in (-p['BaseBoltY'],p['BaseBoltY'])]
    forkholes=[(s*(f-p['ForkBoltInset']),y) for s in (-1,1) for y in (-p['ForkBoltY'],p['ForkBoltY'])]
    servo_top=deck-p['ServoShaftProjection']-p['HornThickness']-p['PanHubThickness']
    if kind=='Base':
        s=box(p['BaseWidth'],p['BaseDepth'],bz)
        for x in (-p['BaseWidth']/4,p['BaseWidth']/4):
            s=s.cut(box(p['BallastPocketWidth'],p['BallastPocketDepth'],p['BallastPocketHeight']+1,x,0,-1))
        s=holes(s,mount,p['M3Clearance'])
        # Captive nuts are exposed to the open underside for assembly/replacement.
        for x,y in mount:s=s.cut(nut_prism(p['M3NutAcrossFlats'],p['M3NutDepth']+0.1,x,y,p['BallastPocketHeight']))
        for x in (-p['BaseWidth']/2+p['FootInset'],p['BaseWidth']/2-p['FootInset']):
            for y in (-p['BaseDepth']/2+p['FootInset'],p['BaseDepth']/2-p['FootInset']):
                s=s.cut(cyl(p['FootDiameter'],1.1,x,y,-.1))
        s=holes(s,[(0,-p['CoverBoltY']),(0,p['CoverBoltY'])],p['M3Clearance'])
        return s
    if kind=='BallastCover':
        s=holes(box(p['BaseWidth']-18,p['BaseDepth']-12,3,z=-3),[(0,-p['CoverBoltY']),(0,p['CoverBoltY'])],p['M3Clearance'])
        # Corner relief keeps the cover clear of the four protruding rubber feet.
        for x in (-p['BaseWidth']/2+p['FootInset'],p['BaseWidth']/2-p['FootInset']):
            for y in (-p['BaseDepth']/2+p['FootInset'],p['BaseDepth']/2-p['FootInset']):
                s=s.cut(cyl(p['FootDiameter']+2,5,x,y,-4))
        # Bottom heads must be flush: a pan head would project below the feet.
        for y in (-p['CoverBoltY'],p['CoverBoltY']):
            s=s.cut(Part.makeCone(p['M3CountersinkDiameter']/2,p['M3Clearance']/2,p['M3CountersinkDepth'],V(0,y,-3)))
        return s
    if kind=='Pedestal':
        top=deck-p['ThrustWasherThickness']
        plate=box(p['TowerWidth'],p['TowerDepth'],w,z=top-w).cut(cyl(p['JournalBore'],w+2,z=top-w-1))
        posts=[box(p['PostWidth'],p['PostWidth'],top-bz-w,x,y,bz) for x in (-p['PostX'],p['PostX']) for y in (-p['PostY'],p['PostY'])]
        foot=box(p['PedestalFootWidth'],p['PedestalFootDepth'],w,z=bz)
        foot=foot.cut(box(32,26,w+2,z=bz-1))
        shelf=box(p['TowerWidth'],p['TowerDepth'],w,z=servo_top-w)
        shelf=shelf.cut(box(p['ServoWidth']+p['ServoFitClearance'],p['ServoDepth']+p['ServoFitClearance'],w+2,p['ServoShaftOffset'],0,servo_top-w-1))
        shelf=holes(shelf,[(p['ServoShaftOffset']+s*p['ServoTabPitch']/2,0) for s in (-1,1)],p['ServoTabHole'])
        s=union([plate,foot,shelf]+posts)
        # Base mounting holes only through the flange, not the full columns.
        for x,y in mount:s=s.cut(cyl(p['M3Clearance'],w+2,x,y,bz-1))
        return s
    if kind=='PanRotor':
        disk=cyl(p['PanDiameter'],w,z=deck)
        ring=cyl(p['JournalBore']-p['DiametralClearance'],p['JournalLength'],z=deck-p['JournalLength']).cut(cyl(p['JournalInnerDiameter'],p['JournalLength']+2,z=deck-p['JournalLength']-1))
        hub=cyl(p['PanHubDiameter'],p['PanHubThickness'],z=deck-p['PanHubThickness'])
        s=union([disk,ring,hub])
        s=holes(s,[(p['HornHoleRadius']*math.cos(i*2*math.pi/p['HornHoleCount']),p['HornHoleRadius']*math.sin(i*2*math.pi/p['HornHoleCount'])) for i in range(p['HornHoleCount'])],p['HornHoleDiameter'])
        s=holes(s,[(0,0)],p['HornCenterAccess'])
        return holes(s,forkholes+[(x,-p['PanDiameter']/2+p['CableSaddleOffset']) for x in (-p['CableSaddleBoltX'],p['CableSaddleBoltX'])],p['M3Clearance'])
    if kind in ('LeftFork','RightFork'):
        sign=-1 if kind=='LeftFork' else 1
        foot=box(p['ForkFootWidth'],p['ForkFootDepth'],w,sign*(f-1),0,deck+w)
        upright=box(w,p['ForkDepth'],az+p['ForkAboveAxis']-(deck+w),sign*(f+w/2),0,deck+w)
        # Wide rear/front ribs tie wall to mounting foot without closed cavities.
        ribs=[box(10,4,22,sign*(f-3),y,deck+w) for y in (-6,6)]
        s=union([foot,upright]+ribs)
        s=holes(s,[(sign*(f-p['ForkBoltInset']),y) for y in (-p['ForkBoltY'],p['ForkBoltY'])],p['M3Clearance'])
        if sign<0:
            boss=cyl(16,p['BushingLength'],-f-p['BushingLength'],0,az,V(1,0,0))
            s=s.fuse(boss).cut(cyl(p['BushingOD']+p['BushingFitAllowance'],20,-f-12,0,az,V(1,0,0)))
        else:
            s=s.cut(cyl(28,12,f-1,0,az,V(1,0,0)))
            # Outer servo flange; actual tabs and shaft datum remain provisional.
            flange=box(w,36,44,f+1.5*w,0,az-16)
            flange=flange.cut(box(w+2,p['ServoDepth']+p['ServoFitClearance'],p['ServoWidth']+p['ServoFitClearance'],f+1.5*w,0,az+p['ServoShaftOffset']-(p['ServoWidth']+p['ServoFitClearance'])/2))
            flange=holes(flange,[(0,az+p['ServoShaftOffset']+s*p['ServoTabPitch']/2) for s in (-1,1)],p['ServoTabHole'],axis='x')
            s=s.fuse(flange)
        return s.removeSplitter()
    if kind=='Cradle':
        base=box(2*half+2*w,p['CradleDepth'],w,z=floor)
        sides=[box(w,p['CradleSideDepth'],az+p['CradleAboveAxis']-floor,s*(half+w/2),0,floor) for s in (-1,1)]
        s=union([base]+sides)
        s=holes(s,[(x,y) for x in (-p['PlateBoltX'],p['PlateBoltX']) for y in (-p['PlateBoltY'],p['PlateBoltY'])],p['M3Clearance'])
        s=s.cut(cyl(p['PivotDiameter']+p['PivotClearance'],w+2,-half-w-1,0,az,V(1,0,0)))
        s=s.cut(cyl(p['HornCenterAccess'],w+2,half-1,0,az,V(1,0,0)))
        s=holes(s,[(y,az+z) for y,z in ((-p['AdapterBoltRadius'],0),(p['AdapterBoltRadius'],0))],p['M3Clearance'],length=300,axis='x')
        # Open central underside provides access to camera screw without clip modification.
        return s.cut(box(24,20,w+2,z=floor-1))
    if kind=='CameraPlate':
        s=box(2*half,p['CradleDepth'],w,z=bottom-w)
        s=holes(s,[(x,y) for x in (-p['PlateBoltX'],p['PlateBoltX']) for y in (-p['PlateBoltY'],p['PlateBoltY'])],p['M3Clearance'])
        for x in (-p['PlateBoltX'],p['PlateBoltX']):
            for y in (-p['PlateBoltY'],p['PlateBoltY']):
                s=s.cut(Part.makeCone(p['M3Clearance']/2,p['M3CountersinkDiameter']/2,p['M3CountersinkDepth'],V(x,y,bottom-p['M3CountersinkDepth'])))
        if p['CameraHoleEnabled']:
            s=s.cut(cyl(p['CameraThreadMajor']+p['CameraHoleClearance'],w+2,p['CameraInsertX'],p['CameraInsertY'],bottom-w-1))
        return s
    if kind=='TiltHornAdapter':
        s=cyl(28,p['TiltAdapterThickness'],half+w,0,az,V(1,0,0))
        s=s.cut(cyl(p['HornCenterAccess'],10,half+w-1,0,az,V(1,0,0)))
        s=holes(s,[(-p['AdapterBoltRadius'],az),(p['AdapterBoltRadius'],az)],p['M3Clearance'],axis='x')
        return holes(s,[(p['HornHoleRadius']*math.sin(i*2*math.pi/p['HornHoleCount']),az+p['HornHoleRadius']*math.cos(i*2*math.pi/p['HornHoleCount'])) for i in range(p['HornHoleCount'])],p['HornHoleDiameter'],axis='x')
    if kind=='CableSaddle':
        # Split-free open saddle, retained with a loose reusable strap through two slots.
        s=box(24,10,8,0,-p['PanDiameter']/2+12,deck+w)
        s=s.cut(cyl(p['CableDiameter']+2,12,0,-p['PanDiameter']/2+6,deck+w+8,V(0,1,0)))
        s=holes(s,[(-8,-p['PanDiameter']/2+12),(8,-p['PanDiameter']/2+12)],p['M3Clearance'])
        return s
    if kind=='ServoFitCoupon':
        s=box(p['ServoTabPitch']+16,p['ServoDepth']+14,w)
        s=s.cut(box(p['ServoWidth']+p['ServoFitClearance'],p['ServoDepth']+p['ServoFitClearance'],w+2,z=-1))
        return holes(s,[(x*p['ServoTabPitch']/2,0) for x in (-1,1)],p['ServoTabHole'])
    if kind=='CameraEnvelope':return box(p['CameraWidth'],p['CameraDepth'],p['CameraHeight'],z=bottom)
    if kind=='PanServoEnvelope':return box(p['ServoWidth'],p['ServoDepth'],p['ServoHeight'],p['ServoShaftOffset'],0,servo_top-p['ServoHeight'])
    if kind=='TiltServoEnvelope':return box(p['ServoHeight'],p['ServoDepth'],p['ServoWidth'],f+2*w+p['ServoHeight']/2,0,az+p['ServoShaftOffset']-p['ServoWidth']/2)
    if kind=='PanHornEnvelope':return cyl(p['HornRadius']*2,p['HornThickness'],z=deck-p['PanHubThickness']-p['HornThickness'])
    if kind=='TiltHornEnvelope':return cyl(p['HornRadius']*2,p['HornThickness'],half+w+p['TiltAdapterThickness'],0,az,V(1,0,0))
    if kind=='ThrustWasher':return cyl(p['ThrustWasherOD'],p['ThrustWasherThickness'],z=deck-p['ThrustWasherThickness']).cut(cyl(p['JournalBore']+.5,4,z=deck-3))
    if kind=='PivotBushing':return cyl(p['BushingOD'],p['BushingLength'],-f-p['BushingLength'],0,az,V(1,0,0)).cut(cyl(p['PivotDiameter'],p['BushingLength']+2,-f-p['BushingLength']-1,0,az,V(1,0,0)))
    raise ValueError(kind)

def posed(kind,p):
    s=shape_for(kind,p)
    if kind in TILT:s.rotate(V(0,0,p['TiltAxisZ']),V(1,0,0),-p['TiltAngle'])
    if kind in PAN:s.rotate(V(0,0,0),V(0,0,1),-p['PanAngle'])
    return s

class Component:
    def __init__(self,obj,kind,params):
        obj.addProperty('App::PropertyString','Kind').Kind=kind
        obj.addProperty('App::PropertyLink','Parameters').Parameters=params
        obj.Proxy=self
    def execute(self,obj):obj.Shape=posed(obj.Kind,values(obj.Parameters))
    def dumps(self):return None
    def loads(self,state):pass
