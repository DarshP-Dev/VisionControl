"""Explicit synthetic pinhole feedback; never modifies real webcam observations."""

import argparse
from dataclasses import dataclass
import math
from pathlib import Path

from face_tracking.centering import FaceCentering
from face_tracking.face_geometry import convert_box
from face_tracking.track_models import FaceTrack, TrackedFaces, TrackState
from hand_tracking.performance import Profile, write_report
from .centering_adapter import from_centering
from .controller import MotorController
from .models import MotorConfig, MotorReason, finite


@dataclass(frozen=True,slots=True)
class SceneConfig:
    horizontal_fov_deg: float
    vertical_fov_deg: float
    target_pan_deg: float=18.
    target_tilt_deg: float=-8.
    duration: float=8.
    fps: int=60

    def __post_init__(self):
        if (not all(finite(v) for v in (self.horizontal_fov_deg,self.vertical_fov_deg,self.target_pan_deg,self.target_tilt_deg,self.duration))
                or not 1<=self.horizontal_fov_deg<=170 or not 1<=self.vertical_fov_deg<=170
                or not abs(self.target_pan_deg)<89 or not abs(self.target_tilt_deg)<89
                or not 0<self.duration<=120 or isinstance(self.fps,bool) or not isinstance(self.fps,int) or not 1<=self.fps<=240):
            raise ValueError('Synthetic scene requires explicit 1..170 deg FOVs, target angles within +/-89, duration (0,120], FPS 1..240')


def project_target(scene,pan_deg,tilt_deg):
    """World +X right, +Y forward, +Z up. Pan +right, tilt +down.

    Inverse R_x(+tilt) R_z(+pan) maps the fixed world ray into camera axes.
    Image-down is -camera Z; separate explicit horizontal/vertical focal scales.
    """
    if not all(finite(v) for v in (pan_deg,tilt_deg)):raise ValueError('Virtual orientation must be finite')
    tp,tt,p,t=map(math.radians,(scene.target_pan_deg,scene.target_tilt_deg,pan_deg,tilt_deg))
    x,y,z=math.sin(tp)*math.cos(tt),math.cos(tp)*math.cos(tt),-math.sin(tt)
    x1,y1=math.cos(p)*x-math.sin(p)*y,math.sin(p)*x+math.cos(p)*y
    forward=math.cos(t)*y1-math.sin(t)*z
    up=math.sin(t)*y1+math.cos(t)*z
    if forward<=1e-9:return None
    return x1/(forward*math.tan(math.radians(scene.horizontal_fov_deg)/2)), -up/(forward*math.tan(math.radians(scene.vertical_fov_deg)/2))


def run_scene(scene,*,motor_config=None,loss_interval=None):
    if loss_interval is not None and (len(loss_interval)!=2 or not all(finite(v) for v in loss_interval)
                                     or not 0<=loss_interval[0]<loss_interval[1]<=scene.duration):
        raise ValueError('Synthetic loss interval must lie within scene duration')
    controller=MotorController(motor_config or MotorConfig(),enabled=True)
    centering=FaceCentering()
    size=(640,360)
    profile=Profile()
    n=round(scene.duration*scene.fps)
    stride=max(1,math.ceil((n+1)/255))
    samples=[]
    last_seen=0.
    initial=project_target(scene,controller.state.pan.angle_deg,controller.state.tilt.angle_deg)
    max_pan_speed=max_tilt_speed=max_pan_accel=max_tilt_accel=0.
    previous=None
    for i in range(n+1):
        now=i/scene.fps
        error=project_target(scene,controller.state.pan.angle_deg,controller.state.tilt.angle_deg)
        visible=error is not None and all(abs(v)<=1 for v in error) and not (loss_interval and loss_interval[0]<=now<loss_interval[1])
        face=None
        if visible:
            face=convert_box((error[0]+1)/2-.02,(error[1]+1)/2-.03,.04,.06,(1,1),size,.99)
            last_seen=now
        track=FaceTrack(1,TrackState.TRACKED if visible else TrackState.LOST,face,face,.99,0.,last_seen,now-last_seen,
                        i+3 if visible else 0,0 if visible else 1,True,False)
        observation=TrackedFaces(round(now*1000),size,(track,),1)
        recommendation=centering.update(observation,now=now)
        state=controller.update(from_centering(recommendation,now=now),now=now,profile=profile)
        max_pan_speed=max(max_pan_speed,abs(state.pan.velocity_deg_s))
        max_tilt_speed=max(max_tilt_speed,abs(state.tilt.velocity_deg_s))
        if previous is not None and state.reason==MotorReason.TRACKING:
            max_pan_accel=max(max_pan_accel,abs(state.pan.velocity_deg_s-previous.pan.velocity_deg_s)*scene.fps)
            max_tilt_accel=max(max_tilt_accel,abs(state.tilt.velocity_deg_s-previous.tilt.velocity_deg_s)*scene.fps)
        if i%stride==0 or i==n:
            samples.append({'time':now,'pan_deg':state.pan.angle_deg,'tilt_deg':state.tilt.angle_deg,
                            'pan_velocity_deg_s':state.pan.velocity_deg_s,'tilt_velocity_deg_s':state.tilt.velocity_deg_s,
                            'projected_error':error,'reason':str(state.reason),'visible':bool(visible)})
        previous=state
    final=project_target(scene,controller.state.pan.angle_deg,controller.state.tilt.angle_deg)
    report={'mode':'synthetic_closed_loop','assumptions':{'horizontal_fov_deg':scene.horizontal_fov_deg,'vertical_fov_deg':scene.vertical_fov_deg,
            'projection':'independent explicit focal scales; rigid yaw/pitch inverse ray transform; no actuator delay/noise/backlash',
            'world_target_pan_deg':scene.target_pan_deg,'world_target_tilt_deg':scene.target_tilt_deg,'fps':scene.fps,'duration':scene.duration},
            'initial_error':initial,'final_error':final,'maximum_pan_speed_deg_s':max_pan_speed,'maximum_tilt_speed_deg_s':max_tilt_speed,
            'maximum_ordinary_pan_acceleration_deg_s2':max_pan_accel,'maximum_ordinary_tilt_acceleration_deg_s2':max_tilt_accel,
            'motor':controller.metadata(),'timings':profile.summary(),'samples':samples,
            'limitations':'Synthetic geometry only; no UGREEN calibration or real servo/motor performance is established'}
    controller.shutdown(now=scene.duration)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizontal-fov',type=float,required=True,help='assumed synthetic degrees, NOT real webcam calibration')
    parser.add_argument('--vertical-fov',type=float,required=True)
    parser.add_argument('--target-pan',type=float,default=18)
    parser.add_argument('--target-tilt',type=float,default=-8)
    parser.add_argument('--duration',type=float,default=8)
    parser.add_argument('--fps',type=int,default=60)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.report.exists():parser.error('Report exists; choose a fresh filename')
    try:scene=SceneConfig(args.horizontal_fov,args.vertical_fov,args.target_pan,args.target_tilt,args.duration,args.fps)
    except ValueError as exc:parser.error(str(exc))
    report=run_scene(scene)
    write_report(args.report,report)
    print(f"SYNTHETIC ONLY: error {report['initial_error']} -> {report['final_error']}; hardware output DISABLED")
    return report


if __name__=='__main__':main()
