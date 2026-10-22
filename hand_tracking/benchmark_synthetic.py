"""Offline recognition/controller microbenchmarks. No camera, GUI or Windows input.

Synthetic observations are test fixtures, not recorded camera images. These costs
exclude capture, conversion, inference, rendering, physical input and the watchdog.
"""

import argparse
from dataclasses import asdict
from pathlib import Path
import platform
import time
from types import SimpleNamespace

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.pinch import PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.swipe import SwipeSettings
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE, as_result
from gestures.tests.test_swipe import sample_hand
from .gesture_preview import classify_result
from .performance import WorkloadProfile, process_cpu_usage, write_report
from .smoothing import LandmarkSmoother
from .multi_hand import TrackedPipeline
from .multi_hand_fixtures import hand as synthetic_hand


WORKLOADS = ("static", "pinch", "swipes", "simulate-relative", "simulate-absolute")


def observations(hand_count, *, tracked=False):
    """A repeatable 120-frame pointing/open-palm/pinch/release cycle."""
    frames = []
    for index in range(120):
        dx = (max(0., (89-index)*2/14) if index >= 75 else max(0., min(2., (index-55)*.15))) if index < 90 else 0.
        if tracked or hand_count > 2:
            phase_ratio = (.08 if index < 110 else .8) if index >= 90 else None
            hands = [synthetic_hand(x + dx * .0385, side="Left" if slot % 2 else "Right", ratio=phase_ratio,
                                    pose="point" if index < 30 else "open")
                     for slot, x in enumerate((.15, .37, .59, .81)[:hand_count])]
            frames.append(as_result(*hands))
            continue
        hands = []
        for side, offset in (("Right", .22), ("Left", -.22))[:hand_count]:
            if index >= 90:
                hand = pinch_hand(.08 if index < 110 else .8, side=side, scale=.04, offset=offset)
            else:
                pose = "point" if index < 30 else "open"
                dx = (max(0., (89-index)*2/14) if index >= 75
                      else max(0., min(2., (index-55)*.15)))
                hand = sample_hand(dx, side=side, offset=offset, pose=pose).observation
            hands.append(hand)
        frames.append(as_result(*hands))
    return frames


def measure(workload, hand_count, frames=500, warmup=100, *, track_ids=False):
    if (workload not in WORKLOADS or isinstance(hand_count, bool) or not isinstance(hand_count, int)
            or hand_count not in (0, 1, 2, 3, 4) or frames <= 0 or warmup < 0
            or workload.startswith("simulate-") and (hand_count > 2 or track_ids)):
        raise ValueError("Use 0–4 observation hands, at most two legacy control hands, positive frames/nonnegative warmup")
    source = observations(hand_count, tracked=track_ids)
    profile = WorkloadProfile(enabled=False)
    smoother = LandmarkSmoother()
    pinch = PinchTracker() if workload != "static" else None
    manager = GestureStateManager(swipe_settings=SwipeSettings()) if workload not in ("static", "pinch") else None
    tracked = (TrackedPipeline(SimpleNamespace(max_hands=max(1, hand_count), smoothing=True, smoothing_alpha=.75,
                                              multi_hand_debug=False, gestures=True, pinch=pinch is not None,
                                              swipes=manager is not None), pinch, manager)
               if hand_count > 2 or track_ids else None)
    backend = SimulationBackend()
    stamp = 0
    controller = (DesktopController(backend, ControlSettings(mapping=workload.removeprefix("simulate-"),
                                                            mouse=True, tabs=True), clock=lambda: stamp/1000)
                  if workload.startswith("simulate-") else None)
    start = cpu_start = None
    try:
        for index in range(frames+warmup):
            if index == warmup:
                profile.enabled = True
                start, cpu_start = time.perf_counter(), time.process_time()
            stamp = index*33
            before_processing = time.perf_counter()
            before = time.perf_counter()
            if tracked is not None:
                result, static, pinches, state = tracked.update(source[index % len(source)], stamp, SIZE, profile)
                shared = tracked.features
            else:
                result = smoother.apply(source[index % len(source)], stamp, (SIZE.height, SIZE.width))
                profile.add("smoothing", time.perf_counter()-before)
                prepared = []
                static = classify_result(result, stamp, SIZE, profile, features_out=prepared)
                shared = tuple(prepared)
                if pinch is not None:
                    before = time.perf_counter()
                    pinches = pinch.update(shared, stamp)
                    profile.add("pinch_processing", time.perf_counter()-before)
                if manager is not None:
                    before = time.perf_counter()
                    state = manager.update(shared, stamp, static, pinches)
                    profile.add("state_management", time.perf_counter()-before)
                    profile.add("swipe_processing", manager.last_swipe_seconds)
            if controller is not None:
                before = time.perf_counter()
                controller.update(state, shared, pinches)
                if index == 0:
                    controller.arm()  # Purely virtual; this tool cannot construct a Windows backend.
                profile.add("controller_processing", time.perf_counter()-before)
            profile.add("synthetic_processing", time.perf_counter() - before_processing)
            if profile.enabled:
                profile.finish_frame(hand_count)
        wall, cpu = time.perf_counter()-start, time.process_time()-cpu_start
        return {"workload": workload, "hands": hand_count, "frames": frames, "warmup_frames": warmup,
                "track_ids_enabled": tracked is not None,
                "synthetic_iterations_per_second": frames/wall, "timings": profile.summary(),
                "resources": process_cpu_usage(cpu, wall, frames), "virtual_actions": dict(backend.counts),
                "control_settings": asdict(controller.settings) if controller else None}
    finally:
        if controller is not None:
            controller.close()
        if manager is not None:
            manager.reset()
        if pinch is not None:
            pinch.reset()
        smoother.reset()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-hands", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--track-ids", action="store_true", help="benchmark the observation ID path also for 0–2 hands")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.warmup < 0 or args.repeats <= 0:
        parser.error("frames/repeats must be positive; warmup must be nonnegative")
    if args.report.exists():
        parser.error("Report already exists; choose a fresh path")
    runs = []
    for repeat in range(args.repeats):
        for count in range(args.max_hands + 1):
            for workload in WORKLOADS:
                if workload.startswith("simulate-") and (count > 2 or args.track_ids):
                    continue
                result = measure(workload, count, args.frames, args.warmup, track_ids=args.track_ids)
                runs.append(dict(result, repeat=repeat+1))
    write_report(args.report, {"kind": "synthetic_only", "python": platform.python_version(), "runs": runs,
                 "max_hands_requested": args.max_hands, "track_ids_requested": args.track_ids,
                 "excluded": "capture, conversion, MediaPipe, GUI, Windows input, emergency thread; NOT webcam FPS",
                 "protocol": "120-frame fixture cycle; deterministic 33 ms timestamps; perf_counter wall time; virtual_actions include warmup; track-ID mode uses identical scale .022 and the first N of four fixed palm positions"})
    print(f"Saved {len(runs)} synthetic runs to {args.report}; no hardware performance claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
