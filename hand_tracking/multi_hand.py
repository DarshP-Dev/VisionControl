"""Observation-only track-ID bridge; reuse the existing feature and event engines."""

from copy import copy
import logging
import time
from types import SimpleNamespace

from gestures.features import extract_features
from gestures.landmarks import from_mediapipe
from gestures.static_gestures import classify_hand

from .association import HandAssociator
from .smoothing import TrackLandmarkSmoother


LOGGER = logging.getLogger("hand_tracking")


class MultiHandDebug:
    def __init__(self):
        self.next_ms = 0
        self.previous_ids = set()

    def log(self, associations, associator, stamp):
        if stamp < self.next_ms:
            return
        self.next_ms = stamp + 2000
        current_ids = set(associator.tracks)
        LOGGER.info("Multi-hand visible=%d/%d | tracks=%s | retired_since_sample=%s | transitions=%s",
                    len(associations), associator.max_hands,
                    ", ".join(f"{a.track_id or '?'}:{a.reason}:cost={a.cost:.2f}" if a.cost is not None else
                              f"{a.track_id or '?'}:{a.reason}" for a in associations) or "none",
                    sorted(self.previous_ids - current_ids),
                    dict(associator.counts))
        self.previous_ids = current_ids


class TrackedPipeline:
    def __init__(self, args, pinch_tracker=None, state_manager=None):
        self.args = args
        self.associator = HandAssociator(args.max_hands)
        self.smoother = TrackLandmarkSmoother(args.smoothing, args.smoothing_alpha)
        self.pinch_tracker, self.state_manager = pinch_tracker, state_manager
        self.associations = ()
        self.features = ()
        self.debug = MultiHandDebug() if args.multi_hand_debug else None

    def update(self, result, stamp, size, timings, *, diagnostics=False):
        before = time.perf_counter()
        hands = getattr(result, "hand_landmarks", None) or []
        if len(hands) > self.args.max_hands:
            raise ValueError("Detector exceeded configured maximum; refusing silent truncation")
        labels = getattr(result, "handedness", None) or []
        observations = []
        for i, points in enumerate(hands):
            single = SimpleNamespace(hand_landmarks=[points], handedness=[labels[i] if i < len(labels) else []])
            try:
                observations.append(from_mediapipe(single, stamp, size).hands[0])
            except ValueError:
                observations.append(None)
        timings.add("observation_adaptation", time.perf_counter() - before)
        before = time.perf_counter()
        self.associations = self.associator.update(observations, stamp, size)
        timings.add("association", time.perf_counter() - before)
        before = time.perf_counter()
        smoothed = self.smoother.apply(observations, self.associations, stamp, size)
        displayed = copy(result)
        displayed.hand_landmarks = [hand.landmarks if hand is not None else hands[i] for i, hand in enumerate(smoothed)]
        timings.add("smoothing", time.perf_counter() - before)
        classifications = pinches = state_frame = None
        self.features = ()
        if self.args.gestures or self.args.pinch:
            before = time.perf_counter()
            feature_start = before
            prepared = []
            for hand in smoothed:
                try:
                    prepared.append(extract_features(hand, image_size=size) if hand else None)
                except ValueError:
                    prepared.append(None)
            self.features = tuple(prepared)
            timings.add("gesture_features", time.perf_counter() - before)
            if self.args.gestures:
                before = time.perf_counter()
                classifications = tuple(classify_hand(item, stamp, diagnostics=diagnostics,
                                                       track_id=a.track_id if a.certain else None)
                                        for item, a in zip(self.features, self.associations))
                timings.add("gesture_classification", time.perf_counter() - before)
            timings.add("gesture_total", time.perf_counter() - feature_start)
            keys = tuple(a.track_id if a.certain else None for a in self.associations)
            if self.pinch_tracker is not None:
                before = time.perf_counter()
                pinches = self.pinch_tracker.update(self.features, stamp, identities=keys)
                timings.add("pinch_processing", time.perf_counter() - before)
            if self.state_manager is not None:
                before = time.perf_counter()
                state_frame = self.state_manager.update(self.features, stamp, classifications, pinches, identities=keys)
                timings.add("state_management", time.perf_counter() - before)
                if self.args.swipes:
                    timings.add("swipe_processing", self.state_manager.last_swipe_seconds)
        if self.debug:
            self.debug.log(self.associations, self.associator, stamp)
        return displayed, classifications, pinches, state_frame
