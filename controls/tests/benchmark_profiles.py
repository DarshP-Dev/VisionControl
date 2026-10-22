"""Isolated controller timings with cached synthetic features and a virtual sink.

Run: python -m controls.tests.benchmark_profiles
No webcam, inference, GUI, hotkey registration or real desktop input is used.
"""

from dataclasses import replace
import json
import statistics
import time

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.events import GestureState as S, HandState, StateFrame
from gestures.models import HandSide as H
from gestures.pinch import PinchMeasurement, PinchResult, PinchStatus as P
from gestures.static_gestures import Gesture as G
from gestures.tests.test_swipe import sample_hand
from .rearm_fixtures import feature


def main():
    variants = (("legacy", "legacy", "automatic", False),
                ("palm_automatic", "palm-cursor", "automatic", False),
                ("palm_manual_active", "palm-cursor", "left-pinch", False),
                ("palm_manual_paused_validator", "palm-cursor", "left-pinch", True))
    cases = []
    for name, profile, resume, paused in variants:
        clock = [0.]
        backend = SimulationBackend()
        settings = ControlSettings(gesture_profile=profile, cursor_resume=resume,
                                   gesture_rearm=resume == "left-pinch", mapping="absolute")
        controller = DesktopController(backend, settings, clock=lambda clock=clock: clock[0])
        items = (feature(), sample_hand(side="Right", offset=.22, pose="point" if profile == "legacy" else "open"))
        gesture = G.POINTING if profile == "legacy" else G.OPEN_PALM
        hands = (HandState(H.LEFT, S.ACTIVE, G.UNKNOWN), HandState(H.RIGHT, S.ACTIVE, gesture))
        channels = tuple(PinchResult(P.OPEN, PinchMeasurement(.8, True), 0, f.observation.handedness) for f in items)
        controller.update(StateFrame(0, hands), items, channels)
        assert controller.arm()
        if paused:
            controller.interaction.paused = True
        cases.append((name, controller, clock, items, hands, channels))
    timings = {name: [] for name, *_ in cases}
    for iteration in range(2200):
        stamp = (iteration + 1) * 33
        for name, controller, clock, items, hands, channels in (cases if iteration % 2 else reversed(cases)):
            frame = StateFrame(stamp, hands)
            pinches = tuple(replace(p, timestamp_ms=stamp) for p in channels)
            clock[0] = stamp / 1000
            start = time.perf_counter_ns()
            controller.update(frame, items, pinches)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            assert controller.armed and not controller.faulted
            if iteration >= 200:
                timings[name].append(elapsed)
    print(json.dumps({"measured_frames_per_variant": 2000, "warmup_frames": 200,
                      "controller_only_ms": {name: {"mean": statistics.mean(values),
                                                    "p95": sorted(values)[1899]}
                                             for name, values in timings.items()}}, indent=2))
    for _, controller, *_ in cases:
        controller.close()


if __name__ == "__main__":
    main()
