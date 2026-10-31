"""Paired synthetic detector-output/hand-host benchmarks; no camera or native input.

The before path uses the unchanged Phase 4.1 geometry adapter. Neither path runs
neural inference, capture, GUI or live input. Iterations/second are NOT webcam FPS.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gc
import hashlib
import math
from pathlib import Path
import platform
import statistics
import time
import tracemalloc
from types import SimpleNamespace as NS

from gestures.models import ImageSize
from hand_tracking.benchmark_synthetic import observations
from hand_tracking.diagnostics import process_memory
from hand_tracking.gesture_preview import classify_result
from hand_tracking.performance import Profile, process_cpu_usage, write_report
from hand_tracking.smoothing import LandmarkSmoother
from .face_geometry import adapt_result, convert_box
from .face_models import FaceFrame
from .face_tracker import FaceTracker, TrackerConfig


def samples(count):
    output = []
    for index in range(120):
        detections = []
        for slot in range(count):
            col, row = slot % 4, slot // 4
            x, y = .05+col*.23+.01*math.sin(index/20), .2+row*.4
            detections.append(NS(bounding_box=NS(origin_x=x*640, origin_y=y*360, width=.12*640, height=.18*360),
                                 categories=[NS(score=.8+.01*((slot+index)%5))]))
        # Deliberately permute detector ordering and scores without crossings.
        output.append(NS(detections=detections[::-1] if index%2 else detections))
    return output


def run_case(*, faces=1, hands=False, tracking=False, frames=2000, warmup=200):
    if faces not in (1, 2, 4, 8) or frames <= 0 or warmup < 0:
        raise ValueError("Use 1/2/4/8 faces, positive frames and nonnegative warmup")
    inputs = samples(faces)
    hand_inputs = observations(2) if hands else None
    smoother = LandmarkSmoother() if hands else None
    tracker = FaceTracker() if tracking else None
    profile = Profile(enabled=False)
    disabled = Profile(enabled=False)
    size = ImageSize(1920, 1080)
    switches = 0
    expected_ids = None
    for i in range(frames+warmup):
        if i == warmup:
            profile.enabled = True
            started, cpu_started = time.perf_counter(), time.process_time()
        before = time.perf_counter()
        stamp = i*33
        if hands:
            result = smoother.apply(hand_inputs[i%120], stamp, (1080, 1920))
            classify_result(result, stamp, size, disabled)
        after_hands = time.perf_counter()
        observation = adapt_result(inputs[i%120], (640, 360), (1920, 1080), stamp)
        after_geometry = time.perf_counter()
        if tracker:
            output = tracker.update(observation, profile=profile)
        ended = time.perf_counter()
        profile.add("hand_host", after_hands-before)
        profile.add("face_detector_output_geometry", after_geometry-after_hands)
        profile.add("host_total", ended-before)
        if tracker and i >= warmup:
            ids = tuple(t.track_id for t in sorted((t for t in output.tracks if t.detected), key=lambda t:t.raw.center_x+t.raw.center_y*10))
            if expected_ids is not None:
                switches += sum(a != b for a, b in zip(expected_ids, ids))
            expected_ids = ids
    wall, cpu = time.perf_counter()-started, time.process_time()-cpu_started
    return {"faces": faces, "hands": 2 if hands else 0, "tracking": tracking,
            "frames": frames, "warmup_frames": warmup, "timings": profile.summary(),
            "synthetic_host_iterations_per_second": frames/wall,
            "resources": process_cpu_usage(cpu, wall, frames), "memory_snapshot": process_memory(),
            "synthetic_known_trajectory_id_switches": switches if tracker else None,
            "tracker": tracker.metadata() if tracker else None}


def memory_probe(frames=10000):
    """Separate allocation probe: tracemalloc overhead excluded from timing cases."""
    tracker = FaceTracker()
    inputs = samples(4)
    for i in range(200):
        tracker.update(adapt_result(inputs[i%120], (640,360), (1920,1080), i*33))
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    for i in range(200, frames+200):
        tracker.update(adapt_result(inputs[i%120], (640,360), (1920,1080), i*33))
    gc.collect()
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"frames": frames, "faces": 4, "retained_python_bytes_delta": retained-baseline,
            "peak_python_traced_bytes": peak, "active_tracks": tracker.metadata()["active_tracks"],
            "notes": "Python allocations only; separate from timed runs; includes adapter and tracker"}


def continuity_probe():
    tracker = FaceTracker()
    def update(t, xs):
        faces = tuple(convert_box(x, .4, .14, .2, (1,1), (1920,1080), .9) for x in xs)
        return tracker.update(FaceFrame(round(t*1000), (1920,1080), (640,360), faces))
    for t in (0, .04, .08):
        update(t, (.2,))
    update(.12, ())
    recovered = update(.16, (.22,))
    retained = recovered.primary_id == 1 and recovered.primary.detected
    update(.2, (.25, .5)); update(.24, (.3, .45))
    crossing = update(.28, (.37, .38))
    return {"plausible_primary_reacquisition_preserved_id": retained,
            "crossing_status": crossing.status, "crossing_current_coordinates_withheld": all(not t.detected for t in crossing.tracks),
            "counters": tracker.metadata()["counters"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--faces", type=int, nargs='+', choices=(1,2,4,8), default=[1,2,4])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.warmup < 0 or args.repeats <= 0:
        parser.error("frames/repeats must be positive; warmup nonnegative")
    if args.report.exists():
        parser.error("report already exists; choose a fresh path")
    cases = []
    for repeat in range(args.repeats):
        for count in args.faces:
            for hands in (False, True):
                # Alternate before/after order to reduce simple ordering bias.
                for tracking in ((False, True) if repeat%2 == 0 else (True, False)):
                    cases.append({"repeat": repeat, **run_case(faces=count, hands=hands, tracking=tracking,
                                                              frames=args.frames, warmup=args.warmup)})
    comparisons = []
    for count in args.faces:
        for hands in (0, 2):
            group = [c for c in cases if c['faces']==count and c['hands']==hands]
            before = statistics.median(c['timings']['host_total']['mean_ms'] for c in group if not c['tracking'])
            after = statistics.median(c['timings']['host_total']['mean_ms'] for c in group if c['tracking'])
            comparisons.append({"faces": count, "hands": hands, "before_mean_ms_median_run": before,
                                "after_mean_ms_median_run": after, "delta_ms": after-before,
                                "change_percent": 100*(after/before-1)})
    report = {"phase": "4.2", "kind": "synthetic_host_only", "python": platform.python_version(),
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "tracker_defaults": asdict(TrackerConfig()),
              "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ('benchmark_tracking.py', 'face_tracker.py', 'track_models.py', 'face_geometry.py')},
              "limitations": "No capture, neural inference, preview, desktop input or physical identity ground truth. Before is unchanged Phase 4.1 output adaptation; hand host is two-hand EMA/static recognition only. Timing includes bounded profiling. Memory snapshots share a process and are not isolated per-case deltas.",
              "cases": cases, "comparisons": comparisons, "memory_probe": memory_probe(),
              "continuity_probe": continuity_probe()}
    write_report(args.report, report)
    for item in comparisons:
        print(f"{item['faces']} faces / {item['hands']} hands: {item['before_mean_ms_median_run']:.4f} -> {item['after_mean_ms_median_run']:.4f} ms; +{item['delta_ms']:.4f} ms")
    return report


if __name__ == '__main__':
    main()
