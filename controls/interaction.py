"""Cursor interaction latch only; system arming and intent events stay elsewhere."""

import math

from gestures.events import GestureState as S
from gestures.arbitration import SWIPE_POSES
from gestures.static_gestures import Gesture

from .profiles import PROFILES


PINCH_APPROACH_MS = 250  # Admission only: UNKNOWN never moves the cursor.


class PalmInteraction:
    def __init__(self, settings, screen):
        self.manual = settings.cursor_resume == "left-pinch"
        self.profile = PROFILES[settings.gesture_profile]
        self.swipe_gestures = SWIPE_POSES[self.profile.swipe_pose]
        self.screen = screen
        self.reset()

    def reset(self):
        self.active = self.paused = self.ready = False
        self.label = "WAITING FOR OPEN PALM"
        self.blend_position = self.blend_stamp = None
        self.last_open_stamp = None

    def observe(self, state, motion, pinch_admitted, stamp):
        """Pause on pending POINTING immediately; latch only deliberate swipe intent.

        Existing static confirmation supplies stabilization. No second debounce
        clock or swipe cooldown is added to cursor resumption.
        """
        swipe_busy = motion is not None and (motion.state == S.CANDIDATE or motion.confirmed)
        self.ready = (state.confirmed == self.profile.cursor_gesture and state.state == S.ACTIVE
                      and state.candidate is None and not swipe_busy and not pinch_admitted)
        if pinch_admitted:
            # Closing the index can pass through UNKNOWN before pinch STARTED.
            # A brief, continuously associated approach can admit a fresh PINCH;
            # it never permits input on the intermediate UNKNOWN observations.
            if (not self.paused and self.last_open_stamp is not None
                    and 0 <= stamp - self.last_open_stamp <= PINCH_APPROACH_MS):
                self.active = True
            return self.active and not self.paused
        if state.confirmed in self.swipe_gestures or swipe_busy:
            self.paused = True
        if self.ready and (not self.paused or not self.manual):
            self.active, self.paused = True, False
            self.last_open_stamp = stamp
            return True
        if (self.paused or state.confirmed == Gesture.FIST or state.candidate == Gesture.FIST
                or state.candidate in self.swipe_gestures):
            self.last_open_stamp = None
        self.active = False
        self.blend_position = self.blend_stamp = None
        self.label = ("WAITING FOR LEFT PINCH" if self.paused and self.manual else
                      "PAUSED - SWIPE MODE" if state.confirmed in self.swipe_gestures or swipe_busy
                      or state.candidate in self.swipe_gestures else "WAITING FOR OPEN PALM")
        return False

    def resume(self):
        self.active, self.paused = True, False
        self.label = "RESUMING"
        self.blend_position = self.blend_stamp = None
        self.last_open_stamp = None

    def acquired(self, current, stamp, absolute):
        self.label = "RESUMING" if absolute else "ACTIVE"
        self.blend_position = tuple(current) if absolute else None
        self.blend_stamp = stamp if absolute else None

    def bound_target(self, target, stamp):
        """Bound absolute reacquisition speed; never keep a permanent position offset.

        A stationary target anywhere on the monitor is reached within 600 ms of
        delivered sample time at <=50 ms cadence (plus existing cursor EMA).
        At sparse cadence cap each step to prevent a large single-frame jump.
        """
        if self.blend_position is None:
            self.label = "ACTIVE"
            return target
        elapsed = min(50, max(0, stamp - self.blend_stamp))
        limit = math.hypot(self.screen.width - 1, self.screen.height - 1) * elapsed / 600
        dx, dy = target[0] - self.blend_position[0], target[1] - self.blend_position[1]
        distance = math.hypot(dx, dy)
        if distance <= limit:
            self.blend_position = self.blend_stamp = None
            self.label = "ACTIVE"
            return target
        fraction = limit / distance
        self.blend_position = (self.blend_position[0] + dx * fraction,
                               self.blend_position[1] + dy * fraction)
        self.blend_stamp = stamp
        self.label = "RESUMING"
        return self.screen.clamp(*self.blend_position)
