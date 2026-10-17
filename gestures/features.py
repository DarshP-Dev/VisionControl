"""Named geometry for future classifiers; no thresholds, labels, history or actions."""

from dataclasses import dataclass
import math

from .geometry import angle_degrees, distance_2d, palm_scale
from .models import Finger, FrameObservation, HandObservation, ImageSize, LandmarkIndex, finite_number


I = LandmarkIndex
FINGER_CHAINS = (
    (Finger.THUMB, (I.THUMB_CMC, I.THUMB_MCP, I.THUMB_IP, I.THUMB_TIP)),
    (Finger.INDEX, (I.INDEX_FINGER_MCP, I.INDEX_FINGER_PIP, I.INDEX_FINGER_DIP, I.INDEX_FINGER_TIP)),
    (Finger.MIDDLE, (I.MIDDLE_FINGER_MCP, I.MIDDLE_FINGER_PIP, I.MIDDLE_FINGER_DIP, I.MIDDLE_FINGER_TIP)),
    (Finger.RING, (I.RING_FINGER_MCP, I.RING_FINGER_PIP, I.RING_FINGER_DIP, I.RING_FINGER_TIP)),
    (Finger.PINKY, (I.PINKY_MCP, I.PINKY_PIP, I.PINKY_DIP, I.PINKY_TIP)),
)


@dataclass(frozen=True, slots=True)
class FingerFeatures:
    finger: Finger
    tip_to_wrist_ratio: float | None
    joint_angle_degrees: float | None
    distal_angle_degrees: float | None
    straightness_ratio: float | None


@dataclass(frozen=True, slots=True)
class HandFeatures:
    observation: HandObservation
    image_size: ImageSize | None
    palm_scale: float
    thumb_index_distance: float
    thumb_index_ratio: float | None
    fingers: tuple[FingerFeatures, ...]

    def finger(self, name: Finger) -> FingerFeatures:
        for item in self.fingers:
            if item.finger == name:
                return item
        raise ValueError(f"No feature measurements for finger {name!r}")


@dataclass(frozen=True, slots=True)
class FrameFeatures:
    """Classifier input contract: frame timestamp/observations plus cached geometry.

    A caller can retain successive records later; hand tuple positions and side
    predictions are not persistent identities. No temporal recognition runs here.
    """

    observation: FrameObservation
    hands: tuple[HandFeatures, ...]


def _ratio(numerator: float, denominator: float) -> float | None:
    return finite_number(numerator / denominator, "Feature ratio") if denominator > 0 else None


def extract_features(hand: HandObservation, *, image_size: ImageSize | None = None) -> HandFeatures:
    """2D features in raw normalized or explicit aspect-correct space; no smoothing.

    Undefined ratios/angles become None, never fabricated zero angles or infinities.
    Raw distance and palm scale remain available even when the scale is zero.
    """
    scale = palm_scale(hand, image_size=image_size)
    thumb_index = distance_2d(hand[I.THUMB_TIP], hand[I.INDEX_FINGER_TIP], image_size=image_size)
    fingers = []
    for finger, chain in FINGER_CHAINS:
        base, joint, distal, tip = (hand[index] for index in chain)
        try:
            path = math.fsum(distance_2d(hand[a], hand[b], image_size=image_size)
                             for a, b in zip(chain, chain[1:]))
        except OverflowError as exc:
            raise ValueError("Finger path length is not finite") from exc
        chord = distance_2d(base, tip, image_size=image_size)
        tip_distance = distance_2d(hand[I.WRIST], tip, image_size=image_size)
        fingers.append(FingerFeatures(
            finger=finger,
            tip_to_wrist_ratio=_ratio(tip_distance, scale),
            joint_angle_degrees=angle_degrees(base, joint, distal, image_size=image_size),
            distal_angle_degrees=angle_degrees(joint, distal, tip, image_size=image_size),
            straightness_ratio=min(1.0, chord / path) if path > 0 else None,
        ))
    return HandFeatures(hand, image_size, scale, thumb_index,
                        _ratio(thumb_index, scale), tuple(fingers))


def extract_frame_features(frame: FrameObservation) -> FrameFeatures:
    return FrameFeatures(frame, tuple(extract_features(hand, image_size=frame.image_size)
                                      for hand in frame.hands))
