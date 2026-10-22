"""Deterministic synthetic observation fixtures; no SDK, camera or recorded data."""

from dataclasses import replace

from gestures.features import extract_features
from gestures.models import HandednessPrediction
from gestures.tests.pinch_fixtures import pinch_hand
from gestures.tests.static_fixtures import SIZE, pose_hand


def hand(x=.2, y=.65, *, side="Right", score=.93, pose="open", ratio=None, scale=.022):
    from gestures.models import Finger
    curled = () if pose == "open" else (Finger.MIDDLE, Finger.RING, Finger.PINKY) if pose == "point" else tuple(Finger)[1:]
    original = (pose_hand(side=side, scale=scale, curled=curled) if ratio is None else
                pinch_hand(ratio, side=side, scale=scale))
    return replace(original, landmarks=tuple(replace(p, x=p.x + x - .5, y=p.y + y - .6) for p in original.landmarks),
                   handedness=(HandednessPrediction(side, score),))


def four(**kwargs):
    return tuple(hand(x, **kwargs) for x in (.15, .37, .59, .81))


def features(observations):
    return tuple(extract_features(h, image_size=SIZE) for h in observations)
