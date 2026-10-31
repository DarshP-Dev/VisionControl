"""Paired Phase 4.2 host tracking vs tracking+centering. No camera or input.

Generated detector outputs and existing hand fixtures exclude neural inference,
capture, HighGUI and physical movement. Iterations/second are not webcam FPS.
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
from hand_tracking.benchmark_synthetic import observations
from hand_tracking.diagnostics import process_memory
from hand_tracking.gesture_preview import classify_result
from hand_tracking.performance import Profile, process_cpu_usage, write_report
from hand_tracking.smoothing import LandmarkSmoother
from .benchmark_tracking import samples
from .centering import FaceCentering
from .centering_preview import draw_centering
from .face_geometry import adapt_result
from .face_tracker import FaceTracker
from .preview import draw_tracks


def run_case(*, faces=1, hands=False, centering=False, frames=2000, warmup=200):
    if faces not in (1,2,4) or frames <= 0 or warmup < 0:
        raise ValueError("Use 1/2/4 faces, positive frames and nonnegative warmup")
    inputs = samples(faces)
    hand_inputs = observations(2) if hands else None
    smoother = LandmarkSmoother() if hands else None
    tracker = FaceTracker()
    calculator = FaceCentering() if centering else None
    profile, disabled = Profile(enabled=False), Profile(enabled=False)
    for i in range(frames+warmup):
        if i == warmup:
            profile.enabled = True
            started, cpu_started = time.perf_counter(), time.process_time()
        before = time.perf_counter()
        stamp = i*33
        if hands:
            hand = smoother.apply(hand_inputs[i%120], stamp, (1080,1920))
            classify_result(hand, stamp, ImageSize(1920,1080), disabled)
        after_hands = time.perf_counter()
        detected = adapt_result(inputs[i%120], (640,360), (1920,1080), stamp)
        tracked = tracker.update(detected, profile=profile)
        after_tracking = time.perf_counter()
        if calculator:
            calculator.update(tracked, now=stamp/1000, profile=profile)
        ended = time.perf_counter()
        profile.add('hand_host', after_hands-before)
        profile.add('face_adapter_tracking', after_tracking-after_hands)
        profile.add('host_total', ended-before)
    wall, cpu = time.perf_counter()-started, time.process_time()-cpu_started
    return {'faces':faces, 'hands':2 if hands else 0, 'centering':centering,
            'frames':frames, 'warmup_frames':warmup, 'timings':profile.summary(),
            'synthetic_host_iterations_per_second':frames/wall,
            'resources':process_cpu_usage(cpu,wall,frames), 'memory_snapshot':process_memory(),
            'centering_metadata':calculator.metadata() if calculator else None}


def _snapshot():
    tracker = FaceTracker()
    inputs = samples(1)
    for i in range(4):
        output = tracker.update(adapt_result(inputs[i], (640,360), (1920,1080), i*33))
    return output


def memory_probe(frames=10000):
    """Separate from timings; changing immutable timestamps, fixed face geometry."""
    template = _snapshot()
    calculator = FaceCentering()
    for i in range(200):
        t = i*.033
        item = replace(template, timestamp_ms=i*33,
                       tracks=(replace(template.primary,last_detected=t),))
        calculator.update(item,now=t)
    gc.collect()
    tracemalloc.start()
    baseline,_ = tracemalloc.get_traced_memory()
    for i in range(200,frames+200):
        t = i*.033
        item = replace(template, timestamp_ms=i*33,
                       tracks=(replace(template.primary,last_detected=t),))
        calculator.update(item,now=t)
    gc.collect()
    retained,peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'frames':frames, 'retained_python_bytes_delta':retained-baseline,
            'peak_python_traced_bytes':peak, 'state_keys':len(calculator.states),
            'transition_keys':len(calculator.transitions),
            'limitations':'Python only; includes immutable input assembly, fixed geometry, no inference/native camera memory'}


def render_probe(frames=1000):
    """Only synthetic face overlays on a reused 640x360 canvas; no imshow/events."""
    tracked = _snapshot()
    calculator = FaceCentering()
    recommendation = calculator.update(tracked,now=.099)
    preview = np.zeros((360,640,3),np.uint8)
    output = []
    for enabled in (False,True):
        profile = Profile(enabled=False)
        for i in range(frames+100):
            if i == 100:
                profile.enabled = True
            preview.fill(0)
            start = time.perf_counter()
            draw_tracks(preview,tracked,now=.099)
            if enabled:
                draw_centering(preview,recommendation,now=.099,config=calculator.config)
            profile.add('synthetic_face_rendering',time.perf_counter()-start)
        output.append({'centering_overlay':enabled,'canvas_size':[640,360],'frames':frames,'timings':profile.summary()})
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=2000)
    parser.add_argument('--warmup',type=int,default=200)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--faces',type=int,nargs='+',choices=(1,2,4),default=[1,2,4])
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.warmup < 0 or args.repeats <= 0:
        parser.error('frames/repeats must be positive; warmup nonnegative')
    if args.report.exists():
        parser.error('report exists; choose a fresh filename')
    cases = []
    for repeat in range(args.repeats):
        for count in args.faces:
            for hands in (False,True):
                for enabled in ((False,True) if repeat%2==0 else (True,False)):
                    cases.append({'repeat':repeat, **run_case(faces=count,hands=hands,centering=enabled,
                                                           frames=args.frames,warmup=args.warmup)})
    comparisons = []
    for count in args.faces:
        for hands in (0,2):
            group = [c for c in cases if c['faces']==count and c['hands']==hands]
            before,after = (statistics.median(c['timings']['host_total']['mean_ms'] for c in group if c['centering']==enabled)
                            for enabled in (False,True))
            comparisons.append({'faces':count,'hands':hands,'before_mean_ms_median_run':before,
                                'after_mean_ms_median_run':after,'added_ms':after-before,'change_percent':100*(after/before-1)})
    report = {'phase':'4.3','kind':'synthetic_host_only','created_utc':datetime.now(timezone.utc).isoformat(),
              'python':platform.python_version(),'platform':platform.platform(),
              'limitations':'No neural inference, capture, HighGUI or input. Two-hand host is EMA/static classification. Timings include opt-in profiling. Synthetic observation ages are zero; these are not sensor ages. Working sets share a process and allocator.',
              'source_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ('centering.py','centering_geometry.py','centering_preview.py','benchmark_centering.py','face_tracker.py')},
              'cases':cases,'comparisons':comparisons,'memory_probe':memory_probe(),'render_probe':render_probe()}
    write_report(args.report,report)
    for item in comparisons:
        print(f"{item['faces']} faces / {item['hands']} hands: {item['before_mean_ms_median_run']:.4f} -> {item['after_mean_ms_median_run']:.4f} ms ({item['change_percent']:+.1f}%)")
    return report


if __name__ == '__main__':
    main()
