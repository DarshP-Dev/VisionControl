"""Real recognition/arbitration with synthetic landmarks and a virtual input sink."""

from dataclasses import replace

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from gestures.features import extract_features
from gestures.pinch import PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.static_gestures import classify_hand
from gestures.swipe import SwipeSettings
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE
from gestures.tests.test_swipe import sample_hand
from .rearm_fixtures import feature


class ProfileRun:
    def __init__(self, *, swipes=True, mapping="absolute", **settings):
        self.stamp = 0
        self.backend = SimulationBackend()
        configured = ControlSettings(gesture_profile="palm-cursor", mapping=mapping, **settings)
        self.backend.is_live = configured.mode == "live"  # Still a virtual sink, never Win32.
        self.controller = DesktopController(self.backend, configured, clock=lambda: self.stamp / 1000)
        self.controller.safety_ready = True
        self.pinch = PinchTracker()
        self.manager = GestureStateManager(swipe_settings=SwipeSettings(pose="pointing") if swipes else None)
        self.last = None

    def features(self, pose="open", dx=0, left=.8, right=None):
        selected = sample_hand(dx, side="Right", pose=pose, offset=.22)
        if right is not None:
            selected = extract_features(pinch_hand(right, side="Right", scale=.04,
                                                  offset=.22 + dx * selected.palm_scale), image_size=SIZE)
        return ((feature(ratio=left),) if left is not None else ()) + (selected,)

    def step(self, pose="open", dx=0, left=.8, right=None, *, dt=50, features=None, reverse=False):
        self.stamp += dt
        items = self.features(pose, dx, left, right) if features is None else tuple(features)
        if reverse:
            items = tuple(reversed(items))
        pinches = self.pinch.update(items, self.stamp)
        static = tuple(classify_hand(item, self.stamp) for item in items)
        frame = self.manager.update(items, self.stamp, static, pinches)
        self.last = frame, items, pinches
        self.controller.update(*self.last)
        return frame

    def arm(self):
        for _ in range(4):
            self.step(dt=100)
        assert self.controller.arm()
        self.step(dt=100)  # acquisition, not movement
        self.step(dt=100)
        assert self.controller.interaction.active

    def pause(self):
        for _ in range(3):
            self.step("point", dt=100)
        assert self.controller.interaction.paused
        assert self.controller.armed

    def ready(self, **kwargs):
        for _ in range(5):
            self.step(dt=100, **kwargs)

    def hold(self, duration=800, **kwargs):
        self.step(left=.08, dt=100, **kwargs)
        for _ in range(duration // 100):
            self.step(left=.08, dt=100, **kwargs)

    def complete(self, **kwargs):
        self.ready(**kwargs)
        self.hold(**kwargs)
        return self.step(dt=100, **kwargs)
