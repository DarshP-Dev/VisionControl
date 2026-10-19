"""Articulated thumb approach to a bent index, in an aspect-correct palm plane."""

from dataclasses import replace
import math

from gestures.geometry import palm_scale
from gestures.models import HandObservation, LandmarkIndex as I
from .static_fixtures import SIZE, pose_hand


def pinch_hand(ratio, *, side="Left", scale=.07, rotation=0, image_size=SIZE, offset=0):
    hand = pose_hand(scale=scale, image_size=image_size)
    points = list(hand.landmarks)
    palm_units = palm_scale(hand, image_size=image_size) / scale
    thumb_tip = (-.9 - ratio * palm_units, 2.15)
    positions = {I.INDEX_FINGER_PIP: (-.45, 2.3), I.INDEX_FINGER_DIP: (-.65, 2.5),
                 I.INDEX_FINGER_TIP: (-.9, 2.15), I.THUMB_MCP: (-1.05, 1.15),
                 I.THUMB_IP: ((-1.05 + thumb_tip[0]) / 2, 1.8), I.THUMB_TIP: thumb_tip}
    aspect = image_size.height / image_size.width
    for index, (x, y) in positions.items():
        points[index] = replace(points[index], x=.5 + scale*x, y=.6 - scale*y/aspect)
    theta = math.radians(rotation)
    cosine, sine = math.cos(theta), math.sin(theta)
    for index, point in enumerate(points):
        x, y = point.x - .5, (point.y - .6) * aspect
        x, y = x*cosine - y*sine, x*sine + y*cosine
        if side == "Right":
            x = -x
        points[index] = replace(point, x=.5 + x + offset, y=.6 + y/aspect)
    metadata = pose_hand(side=side).handedness
    return HandObservation(tuple(points), metadata)
