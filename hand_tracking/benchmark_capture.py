"""Synthetic blocking-call overlap experiment, NOT webcam or MediaPipe FPS.

The producer sleeps for a chosen read delay; the consumer sleeps for a chosen
processing delay. Sleeps release the GIL. This isolates handoff/overlap and copy
cost; it does not model sensor timing, CPU contention or recognition accuracy.
"""

import argparse
from pathlib import Path
import platform
import time

import numpy as np

from camera.camera_diagnostics import read_frame
from .performance import Profile, process_cpu_usage, write_report


class SyntheticCapture:
    def __init__(self, read_seconds=.0153, shape=(1080, 1920, 3)):
        self.read_seconds = read_seconds
        self.frame = np.zeros(shape, np.uint8)
        self.released = False

    def read(self):
        time.sleep(self.read_seconds)
        return True, self.frame

    def release(self):
        self.released = True


def measure(mode, frames=100, warmup=20, read_seconds=.0153, processing_seconds=.0238):
    if mode not in ("sync", "latest-thread") or frames <= 0 or warmup < 0 or min(read_seconds, processing_seconds) <= 0:
        raise ValueError("Use a defined mode, positive frames/delays and nonnegative warmup")
    profile = Profile(enabled=False)
    source = cap = None
    if mode == "latest-thread":
        from camera.latest_capture import LatestCapture
        source = LatestCapture(lambda: SyntheticCapture(read_seconds), profile=True, startup_timeout=5.).start()
    else:
        cap = SyntheticCapture(read_seconds)
    start = cpu = previous = None
    try:
        for index in range(warmup+frames):
            if index == warmup:
                profile.enabled = True
                start, cpu = time.perf_counter(), time.process_time()
                if source:
                    source.begin_measurement()
            before = time.perf_counter()
            if source:
                packet = None
                while packet is None:
                    packet = source.take(.01)
                    source.check_deadline()
                read_at = packet.read_completed_at
            else:
                read_frame(cap)
                read_at = time.perf_counter()
            inference_start = time.perf_counter()
            profile.add("consumer_wait", inference_start-before)
            profile.add("frame_age_at_processing_start", inference_start-read_at)
            time.sleep(processing_seconds)
            end = time.perf_counter()
            profile.add("host_age_at_processing_end", end-read_at)
            if profile.enabled and previous is not None:
                profile.add("frame_interval", end-previous)
            previous = end
        elapsed, cpu_seconds = end-start, time.process_time()-cpu
    finally:
        if source:
            source.close()
        elif cap:
            cap.release()
    return {"mode": mode, "frames": frames, "warmup_frames": warmup,
            "read_delay_ms": read_seconds*1000, "processing_delay_ms": processing_seconds*1000,
            "shape": [1080, 1920, 3], "synthetic_completed_iterations_per_second": frames/elapsed,
            "timings": profile.summary(), "resources": process_cpu_usage(cpu_seconds, elapsed, frames),
            "capture": source.snapshot() if source else {"mode": "sync", "buffer_capacity": 0}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-pipeline", choices=("sync", "latest-thread"), default="sync")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--read-ms", type=float, default=15.3)
    parser.add_argument("--processing-ms", type=float, default=23.8)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.warmup < 0 or args.repeats <= 0 or not all(
            np.isfinite(x) and x > 0 for x in (args.read_ms, args.processing_ms)) or args.report.exists():
        parser.error("Use positive counts/delays, nonnegative warmup and a fresh report path")
    runs = [dict(measure(args.capture_pipeline, args.frames, args.warmup, args.read_ms/1000,
                         args.processing_ms/1000), repeat=i+1) for i in range(args.repeats)]
    write_report(args.report, {"kind": "synthetic_blocking_call_overlap", "python": platform.python_version(),
                             "runs": runs, "limitations": __doc__})
    print(f"Saved {args.capture_pipeline} synthetic overlap report: {args.report}; no webcam FPS claim.")


if __name__ == "__main__":
    main()
