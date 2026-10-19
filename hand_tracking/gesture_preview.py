"""Bridge displayed Tasks results to static rules; keep frame-local result slots."""

import time
from types import SimpleNamespace

from gestures.features import extract_features
from gestures.landmarks import from_mediapipe
from gestures.models import ImageSize
from gestures.static_gestures import GestureResult, classify_hand

from .performance import Profile
from .tracking_utils import MAX_HANDS


def classify_result(result: object, timestamp_ms: int, image_size: ImageSize,
                    timings: Profile, *, diagnostics: bool = False) -> tuple[GestureResult, ...]:
    """Include adaptation/features in gesture_features, rules in gesture_classification.

    The usual path snapshots the whole frame once. If a malformed hand makes
    strict adaptation fail, adapt individual slots so the other hand still works.
    Invalid slots become UNKNOWN; zero detections produce an empty tuple.
    """
    start = time.perf_counter()
    hands = (getattr(result, "hand_landmarks", None) or [])[:MAX_HANDS]
    try:
        observations = from_mediapipe(result, timestamp_ms, image_size).hands
    except ValueError:
        predictions = getattr(result, "handedness", None) or []
        observations = []
        for index, points in enumerate(hands):
            categories = predictions[index] if index < len(predictions) else []
            single = SimpleNamespace(hand_landmarks=[points], handedness=[categories])
            try:
                observations.append(from_mediapipe(single, timestamp_ms, image_size).hands[0])
            except ValueError:
                observations.append(None)
    prepared = []
    for hand in observations:
        try:
            prepared.append(extract_features(hand, image_size=image_size) if hand is not None else None)
        except ValueError:
            prepared.append(None)
    before_rules = time.perf_counter()
    classifications = tuple(classify_hand(hand, timestamp_ms, diagnostics=diagnostics) for hand in prepared)
    end = time.perf_counter()
    timings.add("gesture_features", before_rules - start)
    timings.add("gesture_classification", end - before_rules)
    timings.add("gesture_total", end - start)
    return classifications
