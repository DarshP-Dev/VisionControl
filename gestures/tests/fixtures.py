"""Synthetic coordinates with known lengths and angles, not classified hand poses."""

from types import SimpleNamespace

from gestures.models import HandObservation, Landmark, LandmarkIndex


I = LandmarkIndex


def synthetic_hand() -> HandObservation:
    # An abstract coordinate plane: palm length=2, palm width=2, straight finger chains.
    coordinates = {
        I.WRIST: (0, 0),
        I.THUMB_CMC: (-1, 0), I.THUMB_MCP: (-2, 0), I.THUMB_IP: (-3, 0), I.THUMB_TIP: (-4, 0),
        I.INDEX_FINGER_MCP: (-1, 2), I.INDEX_FINGER_PIP: (-1, 3),
        I.INDEX_FINGER_DIP: (-1, 4), I.INDEX_FINGER_TIP: (-1, 5),
        I.MIDDLE_FINGER_MCP: (0, 2), I.MIDDLE_FINGER_PIP: (0, 3),
        I.MIDDLE_FINGER_DIP: (0, 4), I.MIDDLE_FINGER_TIP: (0, 5),
        I.RING_FINGER_MCP: (.5, 2), I.RING_FINGER_PIP: (.5, 3),
        I.RING_FINGER_DIP: (.5, 4), I.RING_FINGER_TIP: (.5, 5),
        I.PINKY_MCP: (1, 2), I.PINKY_PIP: (1, 3), I.PINKY_DIP: (1, 4), I.PINKY_TIP: (1, 5),
    }
    return HandObservation(tuple(Landmark(*coordinates[index], 0) for index in LandmarkIndex))


def transform(hand: HandObservation, scale: float = 1, offset: tuple = (0, 0, 0)) -> HandObservation:
    return HandObservation(tuple(Landmark(p.x * scale + offset[0], p.y * scale + offset[1],
                                           p.z * scale + offset[2]) for p in hand.landmarks),
                           hand.handedness)


def mediapipe_result(hands: tuple[HandObservation, ...] = (), handedness: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        hand_landmarks=[[SimpleNamespace(x=p.x, y=p.y, z=p.z) for p in hand.landmarks] for hand in hands],
        handedness=handedness,
    )


def category(name: str, score: float | None = .95) -> SimpleNamespace:
    return SimpleNamespace(category_name=name, score=score)
