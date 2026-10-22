"""Deterministic, synchronous per-hand intent state; independent of camera/actions."""

from dataclasses import dataclass, field, replace
import math
import time

from .arbitration import opposing_swipes, resolved_input, swipe_eligible
from .association import WRIST_CONTINUITY_DISTANCE, hands_overlap, reliable_side
from .association import valid_track_keys
from .events import (PINCH, SWIPES, EventMetadata, EventType, GestureEvent, GestureId,
                     GestureState as S, HandState, StateFrame)
from .features import HandFeatures
from .models import MAX_HANDS, HandSide, ImageSize, finite_number
from .pinch import MAX_HISTORY_GAP_MS, PinchResult, PinchStatus
from .static_gestures import Gesture, GestureResult
from .swipe import SwipeHistory, SwipeSettings


@dataclass(frozen=True, slots=True)
class StateSettings:
    activation_ms: int = 100
    transition_ms: int = 60
    cooldown_ms: int = 150
    update_ms: int = 250

    def __post_init__(self):
        for name in ("activation_ms", "transition_ms", "cooldown_ms", "update_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5000:
                raise ValueError(f"{name} must be an integer in [0, 5000] milliseconds")


@dataclass(slots=True)
class _Track:
    side: HandSide
    wrist: tuple[float, float]
    state: S = S.IDLE
    confirmed: GestureId | None = None
    candidate: GestureId | None = None
    candidate_since: int = 0
    pending: GestureId | None = None
    pending_since: int = 0
    cooldowns: dict[GestureId, int] = field(default_factory=dict)
    last_event: GestureEvent | None = None
    update_at: int = 0
    last_distance: float | None = None
    pinch_armed: bool = False
    reason: str = ""
    swipe: SwipeHistory | None = None
    last_swipe: GestureEvent | None = None
    track_id: int | None = None


def _valid_geometry(item: HandFeatures | None) -> bool:
    try:
        if not isinstance(item, HandFeatures) or not isinstance(item.image_size, ImageSize):
            return False
        if finite_number(item.palm_scale, "Palm scale") <= 1e-9:
            return False
        return all(math.isfinite(p.x) and math.isfinite(p.y) and math.isfinite(p.z)
                   for p in item.observation.landmarks)
    except (AttributeError, TypeError, ValueError):
        return False


class GestureStateManager:
    """One stream per legacy side or explicit observation ID, with static cooldowns.

    UNKNOWN/invalid input cancels immediately. A known static replacement must
    persist for transition_ms before END; its activation clock starts at the
    first changed frame. Pinch STARTED/RELEASED have no extra time delay/cooldown.
    Lost associations generate only historical CANCELED events, never release.
    """

    def __init__(self, settings: StateSettings = StateSettings(), *,
                 swipe_settings: SwipeSettings | None = None, swipe_diagnostics=False):
        self.settings = settings
        self.swipe_settings, self.swipe_diagnostics = swipe_settings, swipe_diagnostics
        self._tracks: dict[HandSide | int, _Track] = {}
        self._last_timestamp: int | None = None
        self._image_size: ImageSize | None = None
        self.last_swipe_seconds = 0.

    def _event(self, track, kind, timestamp, reason="", distance=None, current=True):
        event = GestureEvent(track.confirmed, kind, timestamp, track.side, track.state,
                             EventMetadata(reason, distance, current), track.track_id)
        track.last_event = event
        return event

    def _finish(self, track, kind, timestamp, reason, current=True, distance=None):
        if track.confirmed is None:
            track.candidate = track.pending = None
            track.state = S.IDLE
            return []
        is_static = track.confirmed != PINCH
        if is_static:
            track.cooldowns[track.confirmed] = timestamp + self.settings.cooldown_ms
        track.state = S.COOLDOWN if is_static and self.settings.cooldown_ms else S.IDLE
        event = self._event(track, kind, timestamp, reason, distance, current)
        track.confirmed = track.candidate = track.pending = None
        return [event]

    def _start(self, track, gesture, timestamp, distance=None):
        track.confirmed, track.state = gesture, S.ACTIVE
        track.candidate = track.pending = None
        track.update_at, track.last_distance = timestamp, distance
        return self._event(track, EventType.GESTURE_STARTED, timestamp, "confirmed", distance)

    def _cancel_all(self, timestamp, reason):
        events = []
        # Fixed namespace order makes output independent of detection order.
        for side in sorted(self._tracks, key=lambda value: str(value)):
            events.extend(self._finish(self._tracks[side], EventType.GESTURE_CANCELED,
                                       timestamp, reason, current=False))
        self._tracks.clear()
        return events

    def reset(self) -> tuple[GestureEvent, ...]:
        """Explicit reset/shutdown cancels active intents at the last known time."""
        events = self._cancel_all(self._last_timestamp or 0, "reset")
        self._last_timestamp = self._image_size = None
        return tuple(events)

    def _advance(self, track, static, pinch, timestamp):
        events = []
        track.reason = ""
        track.cooldowns = {name: until for name, until in track.cooldowns.items() if until > timestamp}
        selected = resolved_input(static, pinch)
        if pinch is not None:
            distance = pinch.measurement.normalized_distance
            if not pinch.measurement.valid or pinch.status == PinchStatus.UNAVAILABLE:
                track.pinch_armed = False
                events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp, "pinch_unavailable"))
                track.state, track.reason = S.IDLE, pinch.reason or "pinch_unavailable"
                return events
            if selected == PINCH:
                if track.confirmed != PINCH:
                    events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp, "pinch_precedence"))
                    if pinch.status == PinchStatus.STARTED and track.pinch_armed:
                        events.append(self._start(track, PINCH, timestamp, distance))
                    else:
                        track.reason, track.state = "pinch_open_to_rearm", S.IDLE
                    track.pinch_armed = False
                elif (self.settings.update_ms > 0 and timestamp - track.update_at >= self.settings.update_ms
                      and distance is not None and track.last_distance is not None
                      and abs(distance - track.last_distance) >= .02):
                    events.append(self._event(track, EventType.GESTURE_UPDATED, timestamp, "distance_changed", distance))
                    track.update_at, track.last_distance = timestamp, distance
                return events
            track.pinch_armed = True  # OPEN or RELEASED: existing detector has observed separation.
        if track.confirmed == PINCH:
            intentional = pinch is not None and pinch.status == PinchStatus.RELEASED
            events.extend(self._finish(track, EventType.GESTURE_ENDED if intentional else EventType.GESTURE_CANCELED,
                                       timestamp, "pinch_released" if intentional else "missing_pinch_transition",
                                       distance=pinch.measurement.normalized_distance if pinch else None))
        if selected is None:
            events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp, "unknown_or_invalid_classification"))
            track.state = S.IDLE
            return events
        if track.confirmed == selected:
            track.pending = None
            return events
        candidate_since = timestamp
        if track.confirmed is not None:
            if track.pending != selected:
                track.pending, track.pending_since = selected, timestamp
            if timestamp - track.pending_since < self.settings.transition_ms:
                return events
            candidate_since = track.pending_since
            events.extend(self._finish(track, EventType.GESTURE_ENDED, timestamp, "stable_static_transition"))
        if selected in track.cooldowns:
            track.candidate, track.state, track.reason = None, S.COOLDOWN, "reactivation_cooldown"
            return events
        if track.candidate != selected:
            track.candidate, track.candidate_since = selected, candidate_since
        track.state = S.CANDIDATE
        if timestamp - track.candidate_since >= self.settings.activation_ms:
            events.append(self._start(track, selected, timestamp))
        return events

    def update(self, features: tuple[HandFeatures | None, ...], timestamp_ms: int,
               static: tuple[GestureResult, ...] | None = None,
               pinches: tuple[PinchResult, ...] | None = None,
               *, identities: tuple[int | None, ...] | None = None) -> StateFrame:
        self.last_swipe_seconds = 0.
        valid_time = isinstance(timestamp_ms, int) and not isinstance(timestamp_ms, bool) and timestamp_ms >= 0
        clock_bad = not valid_time or (self._last_timestamp is not None and timestamp_ms <= self._last_timestamp)
        if clock_bad:
            stamp = self._last_timestamp or 0
            events = self._cancel_all(stamp, "invalid_or_non_monotonic_time")
            return StateFrame(stamp, tuple(HandState(HandSide.UNKNOWN, reason="invalid_time") for _ in features), tuple(events))
        previous_time = self._last_timestamp
        self._last_timestamp = timestamp_ms
        valid = tuple(_valid_geometry(item) for item in features)
        sides = tuple(reliable_side(item) if isinstance(item, HandFeatures) else HandSide.UNKNOWN for item in features)
        tracked = identities is not None
        keys = identities if tracked and valid_track_keys(identities, len(features)) else sides
        sizes = {item.image_size for item, ok in zip(features, valid) if ok}
        reason = ""
        if (len(features) > (4 if tracked else MAX_HANDS) or (static is None and pinches is None)
                or tracked and not valid_track_keys(identities, len(features))
                or (static is not None and len(static) != len(features))
                or (pinches is not None and len(pinches) != len(features))):
            reason = "invalid_channel_alignment"
        elif not tracked and (HandSide.UNKNOWN in sides or len(set(sides)) != len(sides)):
            reason = "ambiguous_handedness"
        elif len(sizes) > 1:
            reason = "conflicting_image_sizes"
        elif not tracked and len(features) == 2 and all(valid) and hands_overlap(*features):
            reason = "overlapping_hands"
        elif previous_time is not None and timestamp_ms - previous_time > MAX_HISTORY_GAP_MS:
            reason = "tracking_gap"
        elif sizes and self._image_size is not None and next(iter(sizes)) != self._image_size:
            reason = "image_size_changed"
        if sizes:
            self._image_size = next(iter(sizes)) if len(sizes) == 1 else None
        if reason:
            events = self._cancel_all(timestamp_ms, reason)
            return StateFrame(timestamp_ms, tuple(HandState(side, reason=reason) for side in sides), tuple(events))
        events, displayed, ready = [], {}, []
        for side in sorted(tuple(self._tracks), key=lambda value: str(value)):
            if side not in keys:
                events.extend(self._finish(self._tracks.pop(side), EventType.GESTURE_CANCELED,
                                           timestamp_ms, "tracking_lost", current=False))
        # Resolve in namespace order; snapshots still follow current detection slots.
        for index in sorted(range(len(keys)), key=lambda i: str(keys[i])):
            side, item = sides[index], features[index]
            key = keys[index]
            if key is None:
                displayed[index] = HandState(side, reason="uncertain_track_association")
                continue
            track = self._tracks.get(key)
            raw_static = static[index] if static is not None else None
            raw_pinch = pinches[index] if pinches is not None else None
            channel_bad = item is None
            for enabled, result, expected_type in ((static is not None, raw_static, GestureResult),
                                                   (pinches is not None, raw_pinch, PinchResult)):
                if enabled and (not isinstance(result, expected_type) or result.timestamp_ms != timestamp_ms
                                or item is None or result.handedness != item.observation.handedness
                                or tracked and result.track_id != key):
                    channel_bad = True
            if isinstance(raw_pinch, PinchResult):
                try:
                    if not isinstance(raw_pinch.status, PinchStatus):
                        channel_bad = True
                    if raw_pinch.measurement.valid:
                        if finite_number(raw_pinch.measurement.normalized_distance, "Pinch distance") < 0:
                            channel_bad = True
                except (ValueError, AttributeError):
                    channel_bad = True
            if not valid[index] or channel_bad:
                if track is not None:
                    events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp_ms,
                                               "invalid_geometry_or_channel", current=False))
                    del self._tracks[key]
                displayed[index] = HandState(side, reason="invalid_geometry_or_channel", track_id=key if tracked else None)
                continue
            wrist = (item.observation[0].x, item.observation[0].y * item.image_size.height / item.image_size.width)
            if track is not None and math.dist(track.wrist, wrist) > WRIST_CONTINUITY_DISTANCE:
                events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp_ms, "wrist_jump", current=False))
                del self._tracks[key]
                displayed[index] = HandState(side, reason="wrist_jump", track_id=key if tracked else None)
                continue
            if track is None:
                track = self._tracks[key] = _Track(side, wrist, track_id=key if tracked else None)
            track.wrist = wrist
            track.side = side
            ready.append((index, track, raw_static, raw_pinch))
        motion = [None]*len(features) if self.swipe_settings is not None else []
        if self.swipe_settings is not None:
            before_motion = time.perf_counter()
            for index, track, raw_static, raw_pinch in ready:
                if track.swipe is None:
                    track.swipe = SwipeHistory(self.swipe_settings, self.swipe_diagnostics)
                blocked_until = max((track.cooldowns.get(name, 0) for name in SWIPES), default=0)
                eligible = (track.confirmed != PINCH
                            and swipe_eligible(raw_static, raw_pinch, self.swipe_settings.pose))
                motion[index] = track.swipe.observe(features[index], timestamp_ms, eligible, blocked_until)
            recent = tuple(track.last_swipe.gesture for _, track, _, _ in ready
                           if track.last_swipe is not None and timestamp_ms-track.last_swipe.timestamp_ms
                           <= min(200, self.swipe_settings.cooldown_ms))
            conflict = opposing_swipes(motion, recent)
            self.last_swipe_seconds = time.perf_counter()-before_motion
        else:
            conflict = False
        for index, track, raw_static, raw_pinch in ready:
            side = track.side
            result = motion[index] if motion else None
            if conflict and result is not None and (result.confirmed or result.state == S.CANDIDATE):
                # Consume both directions, including a not-yet-confirmed opposite candidate.
                track.swipe.consume()
                for name in SWIPES:
                    track.cooldowns[name] = timestamp_ms+self.swipe_settings.cooldown_ms
                result = replace(result, admitted=False, reason="opposite_two_hand_motion", state=S.COOLDOWN,
                                 cooldown_ms=self.swipe_settings.cooldown_ms, trajectory=())
                track.swipe.outcome(result, False, result.reason)
                motion[index] = result
            if result is not None and result.confirmed and not conflict:
                # One atomic completed-motion lifecycle; no sustained swipe ACTIVE state.
                events.extend(self._finish(track, EventType.GESTURE_CANCELED, timestamp_ms, "swipe_precedence"))
                metadata = EventMetadata("swipe_confirmed", motion=result.metrics, direction=result.gesture)
                events.append(GestureEvent(result.gesture, EventType.GESTURE_STARTED, timestamp_ms,
                                           track.side, S.ACTIVE, metadata, track.track_id))
                terminal = GestureEvent(result.gesture, EventType.GESTURE_ENDED, timestamp_ms,
                                        track.side, S.COOLDOWN, metadata, track.track_id)
                events.append(terminal)
                track.last_event, track.state = terminal, S.COOLDOWN
                track.last_swipe = terminal
                for name in SWIPES:
                    track.cooldowns[name] = timestamp_ms+self.swipe_settings.cooldown_ms
                result = replace(result, admitted=True, state=S.COOLDOWN,
                                 cooldown_ms=self.swipe_settings.cooldown_ms)
                track.swipe.outcome(result, True, "swipe_confirmed")
                motion[index] = result
            else:
                events.extend(self._advance(track, raw_static, raw_pinch, timestamp_ms))
            displayed[index] = HandState(side, track.state, track.confirmed,
                                        track.candidate or track.pending, track.last_event, track.reason, track.track_id)
        return StateFrame(timestamp_ms, tuple(displayed[index] for index in range(len(features))), tuple(events), tuple(motion))
