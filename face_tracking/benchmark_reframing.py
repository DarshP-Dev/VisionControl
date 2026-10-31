"""Paired synthetic centering/reframing host costs and original/dual display work.

No camera, neural inference, HighGUI calls, desktop input or physical movement.
Synthetic iteration rates are not webcam/application FPS.
"""

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

from gestures.models import ImageSize
from gestures.tests.static_fixtures import as_result
from hand_tracking.benchmark_synthetic import observations
from hand_tracking.diagnostics import process_memory
from hand_tracking.gesture_preview import classify_result
from hand_tracking.performance import Profile, process_cpu_usage, write_report
from hand_tracking.smoothing import LandmarkSmoother
from hand_tracking.tracking_utils import make_preview, PreviewRenderer
from .benchmark_tracking import samples
from .benchmark_centering import _snapshot
from .centering import FaceCentering
from .centering_preview import draw_centering
from .digital_reframing import DigitalReframer
from .face_geometry import adapt_result
from .face_tracker import FaceTracker
from .preview import draw_tracks
from .reframing_preview import ReframeRenderer


def run_case(*, faces=1, hands=False, reframing=False, frames=1000, warmup=100):
    if faces not in (1,2,4) or frames<=0 or warmup<0:
        raise ValueError('Use 1/2/4 faces, positive frames and nonnegative warmup')
    inputs=samples(faces)
    hand_inputs=observations(2) if hands else None
    smoother=LandmarkSmoother() if hands else None
    tracker,centering=FaceTracker(),FaceCentering()
    reframer=DigitalReframer() if reframing else None
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
        after_hands=time.perf_counter()
        detected=adapt_result(inputs[i%120],(640,360),(1920,1080),stamp)
        tracked=tracker.update(detected,profile=profile)
        recommendation=centering.update(tracked,now=stamp/1000,profile=profile)
        if reframer:
            reframer.update(recommendation,source_size=(1920,1080),now=stamp/1000,profile=profile)
        ended=time.perf_counter()
        profile.add('hand_host',after_hands-before)
        profile.add('host_total',ended-before)
    wall,cpu=time.perf_counter()-started,time.process_time()-cpu_started
    return {'faces':faces,'hands':2 if hands else 0,'reframing':reframing,
            'frames':frames,'warmup_frames':warmup,'timings':profile.summary(),
            'synthetic_host_iterations_per_second':frames/wall,
            'resources':process_cpu_usage(cpu,wall,frames),'memory':process_memory(),
            'reframer':reframer.metadata() if reframer else None}


def memory_probe(frames=10000):
    template=FaceCentering().update(_snapshot(),now=.099)
    reframer=DigitalReframer()
    def step(i):
        t=i*.033
        observed=replace(template,source_timestamp_ms=i*33,observation_timestamp=t,evaluated_at=t,observation_age=0.)
        reframer.update(observed,source_size=(1920,1080),now=t)
    for i in range(100):step(i)
    gc.collect();tracemalloc.start()
    baseline,_=tracemalloc.get_traced_memory()
    for i in range(100,frames+100):step(i)
    gc.collect()
    retained,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'frames':frames,'retained_python_bytes_delta':retained-baseline,'peak_python_traced_bytes':peak,
            'metadata':reframer.metadata(),'limitations':'Python-only geometry/state and immutable input assembly; no image buffers or native inference'}


def render_probe(frames=500):
    source=np.zeros((1080,1920,3),np.uint8)
    tracked=_snapshot()
    centering=FaceCentering()
    recommendation=centering.update(tracked,now=.099)
    viewport=DigitalReframer().update(recommendation,source_size=(1920,1080),now=.099)
    output=[]
    for dual in (False,True):
        original,secondary=PreviewRenderer(),ReframeRenderer() if dual else None
        profile=Profile(enabled=False)
        for i in range(frames+50):
            if i==50:
                profile.enabled=True
                started,cpu_started=time.perf_counter(),time.process_time()
            before=time.perf_counter()
            display=make_preview(source,as_result(),30,False,renderer=original,hand_tracking_enabled=False)
            draw_tracks(display,tracked,now=.099)
            draw_centering(display,recommendation,now=.099,config=centering.config)
            after_original=time.perf_counter()
            if secondary:
                secondary.render(source,viewport,now=.099,profile=profile)
            ended=time.perf_counter()
            profile.add('original_preview',after_original-before)
            profile.add('all_preview_preparation',ended-before)
        wall,cpu=time.perf_counter()-started,time.process_time()-cpu_started
        output.append({'dual_preview':dual,'source_size':[1920,1080],'frames':frames,'timings':profile.summary(),
                       'original_display_buffer_bytes':original.buffer.nbytes,
                       'secondary_display_buffer_bytes':secondary.buffer.nbytes if secondary else 0,
                       'resources':process_cpu_usage(cpu,wall,frames),'memory':process_memory()})
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=1000)
    parser.add_argument('--warmup',type=int,default=100)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--faces',type=int,nargs='+',choices=(1,2,4),default=[1,2,4])
    parser.add_argument('--render-frames',type=int,default=500)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.frames<=0 or args.warmup<0 or args.repeats<=0 or args.render_frames<=0:
        parser.error('Use positive frames/repeats/render-frames and nonnegative warmup')
    if args.report.exists():parser.error('Report exists; choose a fresh filename')
    cases=[]
    for repeat in range(args.repeats):
        for count in args.faces:
            for hands in (False,True):
                for enabled in ((False,True) if repeat%2==0 else (True,False)):
                    cases.append({'repeat':repeat,**run_case(faces=count,hands=hands,reframing=enabled,frames=args.frames,warmup=args.warmup)})
    comparisons=[]
    for count in args.faces:
        for hands in (0,2):
            group=[c for c in cases if c['faces']==count and c['hands']==hands]
            before,after=(statistics.median(c['timings']['host_total']['mean_ms'] for c in group if c['reframing']==enabled)
                          for enabled in (False,True))
            comparisons.append({'faces':count,'hands':hands,'before_mean_ms_median_run':before,
                                'after_mean_ms_median_run':after,'added_ms':after-before,'change_percent':100*(after/before-1)})
    root=Path(__file__).resolve().parents[1]
    sources=('face_tracking/digital_reframing.py','face_tracking/reframing_models.py','face_tracking/reframing_preview.py',
             'face_tracking/benchmark_reframing.py','hand_tracking/hand_tracker.py')
    report={'phase':'4.4','kind':'synthetic_host_and_display_preparation','python':platform.python_version(),
            'platform':platform.platform(),'created_utc':datetime.now(timezone.utc).isoformat(),
            'limitations':'No camera, neural inference, HighGUI/event costs or input. Two-hand host uses existing EMA/static fixtures. Synthetic observation age is zero. Rendering uses blank full-size frames; working sets share a process/allocator.',
            'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources},
            'cases':cases,'comparisons':comparisons,'memory_probe':memory_probe(),'render_probe':render_probe(args.render_frames)}
    write_report(args.report,report)
    for c in comparisons:
        print(f"{c['faces']} faces / {c['hands']} hands: {c['before_mean_ms_median_run']:.4f} -> {c['after_mean_ms_median_run']:.4f} ms ({c['change_percent']:+.1f}%)")
    return report


if __name__=='__main__':main()
