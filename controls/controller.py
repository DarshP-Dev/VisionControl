"""Consume current gesture events, not a second recognition state machine."""

import logging
import math
import threading
import time

from gestures.association import reliable_side, hands_overlap
from gestures.events import PINCH, SWIPES, SWIPE_LEFT, EventType as E, GestureState as S
from gestures.models import HandSide
from gestures.pinch import PinchStatus
from gestures.static_gestures import Gesture

from .cursor import AbsoluteCursor, RelativeCursor
from .models import ControlSettings, ControlStatus


LOGGER = logging.getLogger("controls")


class DesktopController:
    def __init__(self, backend, settings=ControlSettings(), *, clock=time.monotonic):
        if bool(backend.is_live) != (settings.mode == "live"):
            raise ValueError("Control mode and input backend must agree")
        self.backend, self.settings, self.clock = backend, settings, clock
        strategy = AbsoluteCursor if settings.mapping == "absolute" else RelativeCursor
        self.cursor = strategy(settings, backend.screen)
        self.lock = threading.RLock()  # Only global emergency/watchdog runs outside the camera loop.
        self.safety_ready = settings.mode == "simulate"
        self.armed = self.button_down = self.open_seen = False
        self.closed = self.faulted = False
        self.last_stamp = None
        self.last_good = None
        self.last_heartbeat = self.clock()
        self.arm_after = None
        self.gesture, self.last_action, self.reason = "--", "No action", "Press A to arm"
        self._last_debug = -math.inf

    def arm(self):
        with self.lock:
            if self.closed or self.faulted or not self.safety_ready:
                self.reason = "Safety unavailable; restart required"
                return False
            if self.last_good is None or self.clock()-self.last_good > .25:
                self.reason = "Show selected hand with separated thumb/index before arming"
                return False
            if self.armed:
                return True
            try:
                position = self.backend.cursor_position()
                if self.backend.screen.clamp(*position) != tuple(position):
                    self.reason = "Move cursor onto selected monitor before arming"
                    return False
            except Exception:
                self.faulted = True
                self.disarm("Cursor query failed; restart required")
                return False
            self.armed, self.open_seen = True, False
            self.arm_after = self.last_stamp
            self.cursor.reset()
            self.reason = "Armed; open thumb/index to enable a fresh pinch"
            return True

    def _release(self):
        if self.button_down:
            # Keep ownership until the backend confirms UP; cleanup may retry a failed release.
            self.backend.left_up()
            self.button_down = False
            self.last_action = "LEFT_BUTTON_UP"

    def disarm(self, reason="Manual disarm"):
        with self.lock:
            self.armed = self.open_seen = False
            self.cursor.reset()
            self.gesture, self.reason = "--", reason
            try:
                try:
                    self._release()
                finally:
                    self.backend.close()  # Independently retry partial mouse/keyboard deliveries.
            except Exception:
                self.faulted = True
                self.reason = "Input release failed; restart required"
                LOGGER.exception("Cannot release owned input")

    def safety_failure(self, reason):
        with self.lock:
            self.safety_ready = False
            self.disarm(reason)

    def check_timeout(self):
        with self.lock:
            if self.armed and self.clock()-self.last_heartbeat > .5:
                self.disarm("Capture/processing stalled (>500 ms); rearm manually")

    def _unsafe(self, reason):
        self.last_good = None
        self.disarm(reason)

    def update(self, frame, features, pinches):
        with self.lock:
            if self.closed:
                return
            try:
                self._update(frame, features, pinches)
            except Exception:
                self.faulted = True
                self.disarm("Input/geometry failure; restart required")
                LOGGER.exception("Desktop controls failed closed")

    def _update(self, frame, features, pinches):
        now = self.clock()
        if self.armed and now-self.last_heartbeat > .5:
            self.disarm("Capture/processing stalled; rearm manually")
        self.last_heartbeat = now
        stamp = frame.timestamp_ms
        if (not isinstance(stamp, int) or isinstance(stamp, bool) or stamp < 0
                or self.last_stamp is not None and (stamp <= self.last_stamp or stamp-self.last_stamp > 250)):
            if isinstance(stamp, int) and not isinstance(stamp, bool):
                self.last_stamp = max(stamp, self.last_stamp or 0)
            self._unsafe("Invalid timestamp/tracking gap; rearm manually")
            return
        self.last_stamp = stamp
        if len(features) != len(frame.hands) or len(pinches) != len(features) or not 1 <= len(features) <= 2:
            self._unsafe("Selected hand lost or invalid channels; rearm manually")
            return
        sides = tuple(reliable_side(item) for item in features)
        if (HandSide.UNKNOWN in sides or len(set(sides)) != len(sides)
                or self.settings.hand not in sides or len(features) == 2 and hands_overlap(*features)):
            self._unsafe("Missing/ambiguous/overlapping hand; rearm manually")
            return
        index = sides.index(self.settings.hand)
        item, state, pinch = features[index], frame.hands[index], pinches[index]
        if (state.side != self.settings.hand or state.reason in (
                "invalid_time", "ambiguous_handedness", "overlapping_hands", "tracking_gap", "image_size_changed",
                "invalid_geometry_or_channel", "wrist_jump", "conflicting_image_sizes", "invalid_channel_alignment")
                or item.image_size is None or not math.isfinite(item.palm_scale) or item.palm_scale <= 1e-9
                or pinch.timestamp_ms != stamp or pinch.handedness != item.observation.handedness
                or not pinch.measurement.valid or pinch.status == PinchStatus.UNAVAILABLE):
            self._unsafe("Invalid hand association/pinch; rearm manually")
            return
        point = item.observation[8]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (point.x, point.y)):
            self._unsafe("Invalid index fingertip; rearm manually")
            return
        # Cancellations of static poses for pinch/swipe precedence are normal arbitration.
        events = tuple(e for e in frame.events if e.side == self.settings.hand)
        if any(not e.metadata.association_current or
               e.event_type == E.GESTURE_CANCELED and e.gesture == PINCH for e in events):
            self._unsafe("Tracking/gesture cancellation; rearm manually")
            return
        self.last_good = now
        self.gesture = str(state.confirmed or state.candidate or "--")
        if not self.armed:
            return
        if self.arm_after is None or stamp <= self.arm_after:
            return
        # Only events produced now are actionable. A repeated frame is rejected above.
        events = tuple(e for e in events if e.timestamp_ms == stamp and e.metadata.association_current)
        opened = pinch.status in (PinchStatus.OPEN, PinchStatus.RELEASED)
        was_dragging = self.button_down
        if self.button_down:
            ended = any(e.gesture == PINCH and e.event_type == E.GESTURE_ENDED for e in events)
            if pinch.status == PinchStatus.RELEASED and ended:
                self._release()
                self.cursor.reset()
            elif state.confirmed != PINCH or pinch.status not in (PinchStatus.STARTED, PinchStatus.HELD):
                self._unsafe("Drag continuity lost; rearm manually")
                return
        start = any(e.gesture == PINCH and e.event_type == E.GESTURE_STARTED for e in events)
        if (self.settings.mouse and start and self.open_seen and state.confirmed == PINCH
                and pinch.status == PinchStatus.STARTED and not self.button_down):
            # Mark ownership before DOWN: a backend may partially deliver then raise.
            self.button_down = True
            self.backend.left_down()
            self.last_action = "LEFT_BUTTON_DOWN"
            if self.settings.mapping == "absolute":
                self.cursor.begin_drag((point.x, point.y), item.image_size, self.backend.cursor_position())
            else:
                self.cursor.reset()  # Curling to pinch must not jerk the cursor/object.
        if opened:
            self.open_seen = True
        pinch_active = state.confirmed == PINCH or pinch.status in (PinchStatus.STARTED, PinchStatus.HELD)
        swipes = tuple(e for e in events if e.gesture in SWIPES and e.event_type == E.GESTURE_STARTED and e.state == S.ACTIVE)
        all_swipes = {e.gesture for e in frame.events if e.gesture in SWIPES and e.event_type == E.GESTURE_STARTED}
        if swipes and self.settings.tabs and not pinch_active and not was_dragging and not self.button_down:
            if len(all_swipes) != 1 or len(swipes) != 1:
                self.reason = "Conflicting swipe events suppressed"
            else:
                previous = swipes[0].gesture == SWIPE_LEFT
                if self.backend.switch_tab(previous, self.settings.browsers):
                    self.last_action = "CTRL+SHIFT+TAB" if previous else "CTRL+TAB"
                    self.reason = "Confirmed swipe"
                else:
                    self.reason = "Tab blocked by foreground/physical-key safety check"
            self.cursor.reset()
        elif swipes:
            self.reason = "Tab actions disabled" if not self.settings.tabs else "Tab suppressed during pinch/drag"
        move = self.button_down or (state.confirmed == Gesture.POINTING and state.state == S.ACTIVE
                                  and state.candidate is None and not pinch_active and not swipes)
        if move:
            target = self.cursor.update((point.x, point.y), item.image_size,
                                        self.backend.cursor_position() if self.cursor.previous is None else (0, 0))
            if target is not None:
                self.backend.move(*target)
                self.last_action = f"Move ({target[0]}, {target[1]})"
            self.reason = "Dragging" if self.button_down else f"{self.settings.mapping.title()} pointing"
        else:
            self.cursor.reset()
            if not swipes:
                self.reason = ("Await fresh pinch STARTED after opening thumb/index" if self.settings.mouse
                               else "Mouse actions disabled") if pinch_active else "No actionable gesture"
        if self.settings.debug and now-self._last_debug >= 2:
            LOGGER.info("%s", self.status())
            self._last_debug = now

    def status(self):
        with self.lock:
            return ControlStatus(self.settings.mode, self.armed, self.settings.hand.value,
                                 self.gesture, self.button_down, self.last_action, self.reason,
                                 self.settings.mapping, getattr(self.cursor, "region", None))

    def close(self):
        with self.lock:
            self.disarm("Shutdown")
            try:
                self.backend.close()  # Independent release retry on backend failure.
            finally:
                self.closed = True
