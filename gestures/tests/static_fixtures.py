"""Articulated synthetic chains with distinct palm bases and curled knuckles."""

import math
from types import SimpleNamespace

from gestures.features import FINGER_CHAINS
from gestures.models import Finger, HandednessPrediction, HandObservation, ImageSize, Landmark, LandmarkIndex


SIZE = ImageSize(1920, 1080)
I = LandmarkIndex


def pose_hand(*, curled: tuple[Finger, ...] = (), partial: tuple[Finger, ...] = (),
              side: str | None = "Left", thumb: str = "relaxed", scale: float = .07,
              rotation: float = 0, image_size: ImageSize = SIZE,
              chain_angles: dict[Finger, tuple[float, float, float]] | None = None) -> HandObservation:
    # Geometry lives in a common-axis plane; convert to normalized image coordinates last.
    positions = {I.WRIST: (0, 0)}
    bases = {Finger.INDEX: (-.8, 1.6), Finger.MIDDLE: (0, 1.8),
             Finger.RING: (.5, 1.7), Finger.PINKY: (.9, 1.5)}
    lengths = {Finger.INDEX: (.9, .65, .45), Finger.MIDDLE: (1, .75, .5),
               Finger.RING: (.9, .65, .45), Finger.PINKY: (.7, .5, .35)}
    fan = {Finger.INDEX: -8, Finger.MIDDLE: 0, Finger.RING: 5, Finger.PINKY: 12}
    thumbs = {
        "relaxed": ((-.6, .7), (-1, .9), (-1.35, 1.2), (-1.55, 1.4)),
        "extended": ((-.6, .7), (-1.2, 1), (-1.8, 1.3), (-2.3, 1.55)),
        "tucked": ((-.6, .7), (-.4, 1.1), (0, 1.25), (.35, 1.2)),
        "collapsed": ((-.6, .7),) * 4,
    }
    for finger, chain in FINGER_CHAINS:
        if finger == Finger.THUMB:
            positions.update(zip(chain, thumbs[thumb]))
            continue
        x, y = bases[finger]
        positions[chain[0]] = (x, y)
        angles = (90, -25, -120) if finger in curled else (90, 20, -20) if finger in partial else (90, 78, 70)
        if chain_angles and finger in chain_angles:
            angles = chain_angles[finger]
        for index, length, angle in zip(chain[1:], lengths[finger], angles):
            radians = math.radians(angle + fan[finger])
            x, y = x + length * math.cos(radians), y + length * math.sin(radians)
            positions[index] = (x, y)
    theta = math.radians(rotation)
    cosine, sine = math.cos(theta), math.sin(theta)
    points = []
    for index in I:
        x, y = positions[index]
        x, y = x * cosine - y * sine, x * sine + y * cosine
        if side == "Right":
            x = -x
        points.append(Landmark(.5 + scale * x, .6 - scale * y * image_size.width / image_size.height, 0))
    predictions = () if side is None else (HandednessPrediction(side, .93),)
    return HandObservation(tuple(points), predictions)


def as_result(*hands: HandObservation) -> SimpleNamespace:
    return SimpleNamespace(
        hand_landmarks=[[SimpleNamespace(x=p.x, y=p.y, z=p.z) for p in hand.landmarks] for hand in hands],
        handedness=[[SimpleNamespace(category_name=p.category_name, score=p.score) for p in hand.handedness]
                    for hand in hands],
    )
