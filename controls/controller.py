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
from .rearm import INVALID_ASSOCIATION_REASONS, LeftPinchRearm


LOGGER = logging.getLogger("controls")


class DesktopController:
    def __init__(self, backend, settings=ControlSettings(), *, clock=time.monotonic):
        if bool(backend.is_live) != (settings.mode == "live"):
            raise ValueError("Control mode and input backend must agree")
        self.backend, self.settings, self.clock = backend, settings, clock
        strategy = AbsoluteCursor if settings.mapping == "absolute" else RelativeCursor
        self.cursor = strategy(settings, backend.screen)
        self.lock = threading.RLock()  # Only global emergency/watchdog runs outside the camera loop.
        self._stop_lock = threading.Lock()  # Never held while waiting for the controller/backend.
        self._stop_requested = threading.Event()
        self._stop_requested.set()
        self._pending_stops = 0
        self._stop_generation = 0
        self._hard_stopped = True
        self._manual_armed_once = self._routine_rearm = False
        self.rearm = LeftPinchRearm(settings) if settings.gesture_rearm else None
        self.last_rearm_seconds = 0.
        self.safety_ready = settings.mode == "simulate"
        self.armed = self.button_down = self.open_seen = False
        self.closed = self.faulted = False
        self.last_stamp = None
        self.last_good = None
        self.last_heartbeat = self.clock()
        self.arm_after = None
        self.gesture, self.last_action, self.reason = "--", "No action", "Press A to arm"
        self._last_debug = -math.inf
        self._cleanup_remaining = 0
        self._cleanup_due = 0.
        self.backend.input_allowed = self._input_allowed

    def arm(self):
        """Explicit keyboard recovery. Gesture requests use the same checked path."""
        return self._arm()

    def _can_gesture_rearm(self):
        return (self.settings.gesture_rearm and self._manual_armed_once and self._routine_rearm
                and not self._hard_stopped and not self.armed and not self._pending_stops
                and self.safety_ready and not self.closed and not self.faulted
                and not self.button_down and not self._cleanup_remaining)

    def _arm(self, *, gesture_generation=None):
        with self.lock:
            if gesture_generation is not None:
                with self._stop_lock:
                    if not self._can_gesture_rearm() or gesture_generation != self._stop_generation:
                        return False
            if self.closed or self.faulted or not self.safety_ready:
                self.reason = "Safety unavailable; restart required"
                return False
            if self.last_good is None or self.clock()-self.last_good > .25:
                self.reason = "Show selected hand with separated thumb/index before arming"
                return False
            if self.armed:
                return self._input_allowed()
            with self._stop_lock:
                arming_generation = self._stop_generation
            try:
                position = self.backend.cursor_position()
                if self.backend.screen.clamp(*position) != tuple(position):
                    self.reason = "Move cursor onto selected monitor before arming"
                    return False
            except Exception:
                self.faulted = True
                self.disarm("Cursor query failed; restart required")
                return False
            with self._stop_lock:
                if (self._pending_stops or self._stop_generation != arming_generation
                        or self.closed or self.faulted or not self.safety_ready
                        or gesture_generation is not None and (gesture_generation != self._stop_generation
                                                                or not self._can_gesture_rearm())):
                    self.reason = "Disarm pending; arm again after cleanup"
                    return False
                self._stop_requested.clear()
                self.armed, self.open_seen = True, False
                self._hard_stopped = self._routine_rearm = False
                if gesture_generation is None:
                    self._manual_armed_once = True
            self.arm_after = self.last_stamp
            self.cursor.reset()
            if self.rearm is not None:
                self.rearm.reset()
            self.reason = "Armed; open thumb/index to enable a fresh pinch"
            return True

    def _release(self):
        if self.button_down:
            # Keep ownership until the backend confirms UP; cleanup may retry a failed release.
            self.backend.left_up()
            self.button_down = False
            self.last_action = "LEFT_BUTTON_UP"

    def disarm(self, reason="Manual disarm"):
        self._disarm(reason, safety_unavailable=False)

    def _disarm(self, reason, safety_unavailable, *, routine=False):
        # Latch before waiting for a frame's lock. A slow cursor query must not
        # be followed by a new DOWN/MOVE/shortcut after an emergency request.
        with self._stop_lock:
            self._pending_stops += 1
            self._stop_generation += 1
            self._stop_requested.set()
            # Critical/manual stops latch before waiting, so an older gesture
            # request cannot become eligible while cleanup is blocked.
            if not routine:
                self._hard_stopped, self._routine_rearm = True, False
            elif (not self._hard_stopped and self._manual_armed_once
                  and (self.armed or self._routine_rearm)):
                self._routine_rearm = self.settings.gesture_rearm
        with self.lock:
            try:
                if safety_unavailable:
                    self.safety_ready = False
                self.armed = self.open_seen = False
                self.cursor.reset()
                self.gesture, self.reason = "--", reason
                if self.rearm is not None:
                    self.rearm.reset()
                errors = []
                try:
                    self._release()
                except Exception as exc:
                    errors.append(exc)
                try:
                    self.backend.close()  # Independently retry partial mouse/keyboard deliveries.
                except Exception as exc:
                    errors.append(exc)
                    self._cleanup_remaining = 3
                    self._cleanup_due = self.clock()+.1
                else:
                    if self.button_down:
                        self.last_action = "LEFT_BUTTON_UP"
                    self.button_down = False
                    self._cleanup_remaining = 0
                if errors:
                    self.faulted = True
                    self.reason = "Input release failed; restart required"
                    LOGGER.error("Cannot release owned input: %s", errors[-1])
            finally:
                with self._stop_lock:
                    self._pending_stops -= 1

    def safety_failure(self, reason):
        self._disarm(reason, safety_unavailable=True)

    def check_timeout(self):
        # Do not wait for the frame lock before latching an overdue stop.
        if self.armed and self.clock()-self.last_heartbeat > .5:
            self.disarm("Capture/processing stalled (>500 ms); rearm manually")
        with self.lock:
            if self._cleanup_remaining and self.clock() >= self._cleanup_due:
                self._cleanup_remaining -= 1
                self._cleanup_due = self.clock()+.1
                try:
                    self.backend.close()
                    if self.button_down:
                        self.last_action = "LEFT_BUTTON_UP"
                    self.button_down = False
                    self._cleanup_remaining = 0
                except Exception:
                    if not self._cleanup_remaining:
                        LOGGER.error("Owned input cleanup retries exhausted; physical release may be required")

    def _input_allowed(self):
        return (self.armed and not self._stop_requested.is_set() and self.safety_ready
                and not self.closed and not self.faulted)

    def _unsafe(self, reason, *, routine=False):
        self.last_good = None
        self._disarm(reason, safety_unavailable=False, routine=routine)

    def update(self, frame, features, pinches):
        self.last_rearm_seconds = 0.
        self.check_timeout()
        with self.lock:
            if self.closed or self.faulted:
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
        if len(features) != len(frame.hands) or len(pinches) != len(features) or len(features) > 2:
            self._unsafe("Invalid control channels; rearm manually")
            return
        if not features:
            self._unsafe("Selected hand lost; rearm manually", routine=True)
            return
        sides = tuple(reliable_side(item) for item in features)
        if (HandSide.UNKNOWN in sides or len(set(sides)) != len(sides)
                or self.settings.hand not in sides or len(features) == 2 and hands_overlap(*features)):
            self._unsafe("Missing/ambiguous/overlapping hand; rearm manually", routine=True)
            return
        index = sides.index(self.settings.hand)
        item, state, pinch = features[index], frame.hands[index], pinches[index]
        if state.side != self.settings.hand or state.reason in INVALID_ASSOCIATION_REASONS:
            # A simultaneous side mismatch must not downgrade a known critical
            # manager error (bad time/geometry/channels) into routine recovery.
            self._unsafe("Invalid hand association; rearm manually", routine=state.reason in (
                "ambiguous_handedness", "overlapping_hands", "tracking_gap", "wrist_jump") or
                state.side != self.settings.hand and state.reason not in INVALID_ASSOCIATION_REASONS)
            return
        if (item.image_size is None or not math.isfinite(item.palm_scale) or item.palm_scale <= 1e-9
                or pinch.timestamp_ms != stamp or pinch.handedness != item.observation.handedness
                or not pinch.measurement.valid):
            self._unsafe("Invalid hand association/pinch; rearm manually")
            return
        if pinch.status == PinchStatus.UNAVAILABLE:
            self._unsafe("Selected pinch unavailable; rearm manually", routine=True)
            return
        point = item.observation[8]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (point.x, point.y)):
            self._unsafe("Invalid index fingertip; rearm manually")
            return
        # Cancellations of static poses for pinch/swipe precedence are normal arbitration.
        events = tuple(e for e in frame.events if e.side == self.settings.hand)
        if any(not e.metadata.association_current or
               e.event_type == E.GESTURE_CANCELED and e.gesture == PINCH for e in events):
            self._unsafe("Tracking/gesture cancellation; rearm manually", routine=True)
            return
        self.last_good = now
        self.gesture = str(state.confirmed or state.candidate or "--")
        if not self._input_allowed():
            if self.rearm is not None:
                before = time.perf_counter()
                with self._stop_lock:
                    generation = self._stop_generation if self._can_gesture_rearm() else None
                if generation is None:
                    self.rearm.reset("GESTURE REARM BLOCKED - MANUAL ARM REQUIRED")
                elif self.rearm.update(frame, features, pinches):
                    if self._arm(gesture_generation=generation):
                        self.rearm.mark_rearmed(stamp)
                self.last_rearm_seconds = time.perf_counter() - before
                if self.settings.rearm_debug and now-self._last_debug >= 2:
                    LOGGER.info("Gesture rearm: %s | %s", self.rearm.feedback, self.reason)
                    self._last_debug = now
            # Includes a successful gesture rearm: never dispatch on its completion frame.
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
            # Prepare the fallible position query/anchor while the button is UP.
            if self.settings.mapping == "absolute":
                current = self.backend.cursor_position()
                if not self._input_allowed():
                    return
                self.cursor.begin_drag((point.x, point.y), item.image_size, current)
            else:
                self.cursor.reset()  # Curling to pinch must not jerk the cursor/object.
            if not self._input_allowed():
                return
            # Mark ownership before DOWN: a backend may partially deliver then raise.
            self.button_down = True
            self.backend.left_down()
            if not self._input_allowed():
                return
            self.last_action = "LEFT_BUTTON_DOWN"
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
                if not self._input_allowed():
                    return
                sent = self.backend.switch_tab(previous, self.settings.browsers)
                if not self._input_allowed():
                    return
                if sent:
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
            current = self.backend.cursor_position() if self.cursor.previous is None else (0, 0)
            if not self._input_allowed():
                return
            target = self.cursor.update((point.x, point.y), item.image_size, current)
            if target is not None:
                if not self._input_allowed():
                    return
                self.backend.move(*target)
                if not self._input_allowed():
                    return
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
            rearm_status = ""
            if self.rearm is not None:
                with self._stop_lock:
                    available = self._can_gesture_rearm()
                if not self.armed:
                    rearm_status = (self.rearm.feedback if available else
                                    "GESTURE REARM BLOCKED - MANUAL ARM REQUIRED")
                elif self.rearm.rearmed_until is not None and (self.last_stamp or 0) <= self.rearm.rearmed_until:
                    rearm_status = "REARMED"
            return ControlStatus(self.settings.mode, self.armed, self.settings.hand.value,
                                 self.gesture, self.button_down, self.last_action, self.reason,
                                 self.settings.mapping, getattr(self.cursor, "region", None),
                                 self.settings.emergency_hotkey, rearm_status)

    def close(self):
        with self.lock:
            self.disarm("Shutdown")
            try:
                self.backend.close()  # Independent release retry on backend failure.
            finally:
                self.closed = True
