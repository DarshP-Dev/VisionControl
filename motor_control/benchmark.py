"""Opt-in synthetic motor/vision-host and display-preparation benchmarks; no I/O."""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import gc
import hashlib
from pathlib import Path
import platform
import statistics
import time
import tracemalloc

import numpy as np

from face_tracking.benchmark_tracking import samples
from face_tracking.benchmark_centering import _snapshot
from face_tracking.centering import FaceCentering
from face_tracking.centering_preview import draw_centering
from face_tracking.digital_reframing import DigitalReframer
from face_tracking.face_geometry import adapt_result
from face_tracking.face_tracker import FaceTracker
from face_tracking.preview import draw_tracks
from gestures.models import ImageSize
from gestures.tests.static_fixtures import as_result
from hand_tracking.benchmark_synthetic import observations
from hand_tracking.diagnostics import process_memory
from hand_tracking.gesture_preview import classify_result
from hand_tracking.performance import Profile, process_cpu_usage, write_report
from hand_tracking.smoothing import LandmarkSmoother
from hand_tracking.tracking_utils import make_preview, PreviewRenderer
from .centering_adapter import from_centering
from .closed_loop import SceneConfig, run_scene
from .controller import MotorController
from .models import MotorInput, MotorReason as R
from .visualization import MotorRenderer


def motor_only(frames=2000,warmup=200):
    if frames<=0 or warmup<0:raise ValueError('Use positive frames and nonnegative warmup')
    motor=MotorController(enabled=True)
    profile=Profile(enabled=False)
    now=0.
    for i in range(frames+warmup):
        if i==warmup:
            profile.enabled=True
            started,cpu_started=time.perf_counter(),time.process_time()
        now+=.3 if i and i%240==225 else 1/60
        stamp=round(now*1000)
        if 180<=i%240<195:
            data=MotorInput(observation_timestamp=now,source_timestamp_ms=stamp,tracking_id=1,reason=R.TARGET_LOST)
        else:
            data=MotorInput(.8,-.5,now-.3 if 195<=i%240<210 else now,stamp,1,True,R.TRACKING)
        motor.update(data,now=now,profile=profile)
    wall,cpu=time.perf_counter()-started,time.process_time()-cpu_started
    return {'frames':frames,'warmup_frames':warmup,'timings':profile.summary(),'motor':motor.metadata(),
            'resources':process_cpu_usage(cpu,wall,frames),'synthetic_updates_per_second':frames/wall,
            'note':'fixed command inputs with scripted loss/stale/stall; no camera feedback'}


def run_case(*,hands=False,reframing=False,motors=False,frames=500,warmup=100):
    if frames<=0 or warmup<0:raise ValueError('Use positive frames and nonnegative warmup')
    face_inputs=samples(1)
    hand_inputs=observations(2) if hands else None
    smoother=LandmarkSmoother() if hands else None
    tracker,centering=FaceTracker(),FaceCentering()
    reframer=DigitalReframer() if reframing else None
    motor=MotorController(enabled=True) if motors else None
    profile,disabled=Profile(enabled=False),Profile(enabled=False)
    size=ImageSize(1920,1080)
    for i in range(frames+warmup):
        if i==warmup:
            profile.enabled=True
            started,cpu_started=time.perf_counter(),time.process_time()
        before=time.perf_counter()
        stamp=i*33
        if hands:
            hand=smoother.apply(hand_inputs[i%120],stamp,(1080,1920))
            classify_result(hand,stamp,size,disabled)
        tracked=tracker.update(adapt_result(face_inputs[i%120],(640,360),(1920,1080),stamp),profile=profile)
        recommended=centering.update(tracked,now=stamp/1000,profile=profile)
        if reframer:reframer.update(recommended,source_size=(1920,1080),now=stamp/1000,profile=profile)
        if motor:
            begin_motor=time.perf_counter()
            motor.update(from_centering(recommended,now=stamp/1000),now=stamp/1000,profile=profile)
            profile.add('motor_total',time.perf_counter()-begin_motor)
        profile.add('host_total',time.perf_counter()-before)
    wall,cpu=time.perf_counter()-started,time.process_time()-cpu_started
    return {'hands':2 if hands else 0,'reframing':reframing,'motor_simulation':motors,'frames':frames,'warmup_frames':warmup,
            'timings':profile.summary(),'resources':process_cpu_usage(cpu,wall,frames),'memory':process_memory(),
            'synthetic_host_iterations_per_second':frames/wall,'motor':motor.metadata() if motor else None}


def memory_probe(frames=10000):
    motor=MotorController(enabled=True)
    for i in range(100):motor.update(MotorInput(.5,-.3,i*.02,i*20,1,True,R.TRACKING),now=i*.02)
    gc.collect();tracemalloc.start()
    before,_=tracemalloc.get_traced_memory()
    for i in range(100,frames+100):motor.update(MotorInput(.5,-.3,i*.02,i*20,1,True,R.TRACKING),now=i*.02)
    gc.collect();retained,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'frames':frames,'retained_python_bytes_delta':retained-before,'peak_python_traced_bytes':peak,
            'limitations':'Python-only input/state/commands, no image/model/native hardware memory','motor':motor.metadata()}


def render_probe(frames=500):
    source=np.zeros((1080,1920,3),np.uint8)
    tracked=_snapshot();centering=FaceCentering();recommended=centering.update(tracked,now=.099)
    motor=MotorController(enabled=True)
    for i in range(60):state=motor.update(MotorInput(.8,-.4,i/60,round(i/60*1000),1,True,R.TRACKING),now=i/60)
    output=[]
    for visual in (False,True):
        renderer=MotorRenderer() if visual else None
        original=PreviewRenderer();profile=Profile(enabled=False)
        for i in range(frames+50):
            if i==50:
                profile.enabled=True;started,cpu_started=time.perf_counter(),time.process_time()
            before=time.perf_counter()
            preview=make_preview(source,as_result(),30,False,renderer=original,hand_tracking_enabled=False)
            draw_tracks(preview,tracked,now=.099)
            draw_centering(preview,recommended,now=.099,config=centering.config)
            if renderer:renderer.render(state,motor.config,profile=profile)
            profile.add('all_preview_preparation',time.perf_counter()-before)
        wall,cpu=time.perf_counter()-started,time.process_time()-cpu_started
        output.append({'motor_visualization':visual,'frames':frames,'timings':profile.summary(),
                       'motor_display_buffer_bytes':renderer.buffer.nbytes if renderer else 0,
                       'resources':process_cpu_usage(cpu,wall,frames),'memory':process_memory()})
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=500)
    parser.add_argument('--warmup',type=int,default=100)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--render-frames',type=int,default=500)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.frames<=0 or args.warmup<0 or args.repeats<=0 or args.render_frames<=0:parser.error('Use positive frames/repeats and nonnegative warmup')
    if args.report.exists():parser.error('Report exists; choose a fresh filename')
    cases=[]
    for repeat in range(args.repeats):
        for hands in (False,True):
            for reframing in (False,True):
                for enabled in ((False,True) if repeat%2==0 else (True,False)):
                    cases.append({'repeat':repeat,**run_case(hands=hands,reframing=reframing,motors=enabled,frames=args.frames,warmup=args.warmup)})
    comparisons=[]
    for hands in (0,2):
        for reframing in (False,True):
            group=[c for c in cases if c['hands']==hands and c['reframing']==reframing]
            before,after=(statistics.median(c['timings']['host_total']['mean_ms'] for c in group if c['motor_simulation']==on) for on in (False,True))
            comparisons.append({'hands':hands,'reframing':reframing,'before_mean_ms':before,'after_mean_ms':after,
                                'added_ms':after-before,'change_percent':100*(after/before-1)})
    root=Path(__file__).resolve().parents[1]
    sources=('motor_control/models.py','motor_control/controller.py','motor_control/simulator.py','motor_control/centering_adapter.py',
             'motor_control/visualization.py','motor_control/closed_loop.py','motor_control/benchmark.py',
             'hand_tracking/hand_tracker.py','hardware/concepts/pan_tilt_concept.scad')
    report={'phase':'4.5','kind':'synthetic_simulation_and_host_only','created_utc':datetime.now(timezone.utc).isoformat(),
            'python':platform.python_version(),'platform':platform.platform(),
            'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources},
            'limitations':'No camera, neural inference, HighGUI, desktop/motor I/O. One face and optional two-hand EMA/static fixture. Synthetic observations have zero host age. Working sets share a process/allocator.',
            'cases':cases,'comparisons':comparisons,'independent_controller':motor_only(),
            'memory_probe':memory_probe(),'render_probe':render_probe(args.render_frames),
            'closed_loop':run_scene(SceneConfig(60,40))}
    write_report(args.report,report)
    for item in comparisons:print(f"{item['hands']} hands, reframe={item['reframing']}: {item['before_mean_ms']:.4f} -> {item['after_mean_ms']:.4f} ms ({item['change_percent']:+.1f}%)")
    return report


if __name__=='__main__':main()
