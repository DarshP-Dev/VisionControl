"""Synthetic observations and virtual input only; production recognizers reused."""

from dataclasses import replace
from functools import lru_cache

from controls.backends import SimulationBackend
from controls.controller import DesktopController
from controls.models import ControlSettings
from controls.rearm import LeftPinchRearm
from gestures.events import PINCH, EventType as E, GestureEvent, GestureState as S, HandState, StateFrame
from gestures.features import extract_features
from gestures.models import HandSide as H
from gestures.pinch import PinchMeasurement, PinchResult, PinchStatus as P, PinchTracker
from gestures.state_machine import GestureStateManager
from gestures.static_gestures import Gesture as G, classify_hand
from gestures.swipe import SwipeSettings
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE


@lru_cache(maxsize=32)
def feature(side="Left", ratio=.8, offset=None):
    offset = (-.22 if side == "Left" else .22) if offset is None else offset
    return extract_features(pinch_hand(ratio, side=side, scale=.04, offset=offset), image_size=SIZE)


def observation(stamp, left=P.OPEN, right=P.OPEN, *, features=None, events=None):
    features = (feature(), feature("Right")) if features is None else tuple(features)
    states, pinches = [], []
    for item in features:
        side = item.observation.handedness[0].side if item.observation.handedness else H.UNKNOWN
        status = left if side == H.LEFT else right
        active = status in (P.STARTED, P.HELD)
        states.append(HandState(side, S.ACTIVE, PINCH if active else G.POINTING))
        pinches.append(PinchResult(status, PinchMeasurement(.1 if active else .8, True), stamp,
                                  item.observation.handedness))
    if events is None:
        events = ((GestureEvent(PINCH, E.GESTURE_STARTED, stamp, H.LEFT, S.ACTIVE),) if left == P.STARTED else
                  (GestureEvent(PINCH, E.GESTURE_ENDED, stamp, H.LEFT, S.IDLE),) if left == P.RELEASED else ())
    return StateFrame(stamp, tuple(states), tuple(events)), features, tuple(pinches)


class ValidatorRun:
    def __init__(self, **settings):
        self.settings = ControlSettings(gesture_rearm=True, **settings)
        self.validator = LeftPinchRearm(self.settings)
        self.stamp = 0

    def step(self, left=P.OPEN, *, dt=100, **kwargs):
        self.stamp += dt
        return self.validator.update(*observation(self.stamp, left, **kwargs))

    def ready(self):
        for _ in range(self.settings.rearm_stable_ms // 100 + 1):
            assert not self.step()
        assert self.validator.phase == "READY_FOR_PINCH"

    def held(self, milliseconds=800):
        assert not self.step(P.STARTED)
        for _ in range(milliseconds // 100):
            assert not self.step(P.HELD)


class ControllerRun:
    def __init__(self, *, live=False, **settings):
        self.now, self.stamp = 0., 0
        self.backend = SimulationBackend()
        self.backend.is_live = live  # Still a purely virtual sink.
        self.controller = DesktopController(self.backend, ControlSettings(mode="live" if live else "simulate",
                                            gesture_rearm=True, **settings), clock=lambda: self.now)
        self.pinch = PinchTracker()
        self.manager = GestureStateManager(swipe_settings=SwipeSettings())
        self.last = None

    def step(self, left=.8, right=.8, *, dt=100, features=None, reverse=False, events=()):
        self.stamp += dt
        self.now = self.stamp / 1000
        if features is None:
            features = tuple(feature(side, ratio) for side, ratio in (("Left", left), ("Right", right)) if ratio is not None)
        if reverse:
            features = tuple(reversed(features))
        pinches = self.pinch.update(features, self.stamp)
        static = tuple(classify_hand(item, self.stamp) for item in features)
        frame = self.manager.update(features, self.stamp, static, pinches)
        if events:
            frame = replace(frame, events=frame.events+tuple(events))
        self.last = frame, tuple(features), pinches
        self.controller.update(*self.last)
        return self.last

    def initial_arm(self):
        for _ in range(3):
            self.step()
        assert self.controller.arm()
        self.step()

    def routine_loss(self):
        self.step(right=None)
        assert not self.controller.armed

    def ready(self, **kwargs):
        for _ in range(self.controller.settings.rearm_stable_ms // 100 + 2):
            self.step(**kwargs)
        assert self.controller.rearm.phase == "READY_FOR_PINCH"

    def hold(self, milliseconds=800, **kwargs):
        self.step(left=.08, **kwargs)
        for _ in range(milliseconds // 100):
            self.step(left=.08, **kwargs)

    def complete(self, **kwargs):
        self.ready(**kwargs)
        self.hold(**kwargs)
        return self.step(**kwargs)
