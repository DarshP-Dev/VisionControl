"""Conservative per-frame static rules; no probabilities, identity matching or history."""

from dataclasses import dataclass, fields
from enum import StrEnum

from .features import FrameFeatures, HandFeatures
from .models import Finger, HandednessPrediction, HandObservation, finite_number


class Gesture(StrEnum):
    OPEN_PALM = "OPEN_PALM"
    FIST = "FIST"
    POINTING = "POINTING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StaticThresholds:
    extended_joint_min_degrees: float = 155
    extended_distal_min_degrees: float = 145
    extended_straightness_min: float = .88
    extended_tip_to_wrist_min: float = 1.15
    curled_joint_max_degrees: float = 110
    curled_distal_max_degrees: float = 160
    curled_straightness_max: float = .75
    curled_tip_to_wrist_max: float = 1.25

    def __post_init__(self) -> None:
        for field in fields(self):
            value = finite_number(getattr(self, field.name), field.name)
            maximum = 180 if field.name.endswith("degrees") else 1 if "straightness" in field.name else None
            if value < 0 or (maximum is not None and value > maximum):
                raise ValueError(f"Invalid threshold {field.name}: {value}")
            object.__setattr__(self, field.name, value)


DEFAULT_THRESHOLDS = StaticThresholds()
LONG_FINGERS = (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY)


@dataclass(frozen=True, slots=True)
class GestureResult:
    gesture: Gesture
    timestamp_ms: int
    handedness: tuple[HandednessPrediction, ...] = ()
    matched_rules: tuple[Gesture, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if (not isinstance(self.timestamp_ms, int) or isinstance(self.timestamp_ms, bool)
                or self.timestamp_ms < 0):
            raise ValueError("Timestamp must be a nonnegative integer number of milliseconds")

    @property
    def unique_rule_match(self) -> bool:
        """A logical rule indicator, never a calibrated confidence probability."""
        return len(self.matched_rules) == 1 and self.gesture == self.matched_rules[0]


def _required_measurements(features: HandFeatures | None) -> tuple[tuple[float, ...], ...] | None:
    if not isinstance(features, HandFeatures) or not isinstance(features.observation, HandObservation):
        return None
    try:
        if finite_number(features.palm_scale, "Palm scale") <= 0:
            return None
        measured = {}
        for finger in features.fingers:
            if finger.finger not in LONG_FINGERS:
                continue
            if finger.finger in measured:
                return None
            joint = finite_number(finger.joint_angle_degrees, "Joint angle")
            distal = finite_number(finger.distal_angle_degrees, "Distal angle")
            straight = finite_number(finger.straightness_ratio, "Straightness")
            tip = finite_number(finger.tip_to_wrist_ratio, "Tip/palm ratio")
            if not (0 <= joint <= 180 and 0 <= distal <= 180 and 0 <= straight <= 1 and tip >= 0):
                return None
            measured[finger.finger] = (joint, distal, straight, tip)
        return tuple(measured[name] for name in LONG_FINGERS)
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


def classify_hand(features: HandFeatures | None, timestamp_ms: int,
                  *, thresholds: StaticThresholds = DEFAULT_THRESHOLDS) -> GestureResult:
    """Classify cached 2D features; thumb posture is deliberately not a rule gate.

    Supply aspect-correct features for camera inputs. A detected hand with invalid
    required features is UNKNOWN; no observation is represented by no call/result.
    """
    handedness = (features.observation.handedness
                  if isinstance(features, HandFeatures) and isinstance(features.observation, HandObservation)
                  else ())
    values = _required_measurements(features)
    if values is None:
        return GestureResult(Gesture.UNKNOWN, timestamp_ms, handedness, reason="invalid_or_missing_features")
    extended, curled = [], []
    for joint, distal, straight, tip in values:
        extended.append(joint >= thresholds.extended_joint_min_degrees
                        and distal >= thresholds.extended_distal_min_degrees
                        and straight >= thresholds.extended_straightness_min
                        and tip >= thresholds.extended_tip_to_wrist_min)
        curled.append(joint <= thresholds.curled_joint_max_degrees
                      and distal <= thresholds.curled_distal_max_degrees
                      and straight <= thresholds.curled_straightness_max
                      and tip <= thresholds.curled_tip_to_wrist_max)
    matches = []
    if all(extended):
        matches.append(Gesture.OPEN_PALM)
    if all(curled):
        matches.append(Gesture.FIST)
    if extended[0] and all(curled[1:]):  # LONG_FINGERS starts with the index finger.
        matches.append(Gesture.POINTING)
    if len(matches) == 1:
        return GestureResult(matches[0], timestamp_ms, handedness, tuple(matches), "unique_rule_match")
    return GestureResult(Gesture.UNKNOWN, timestamp_ms, handedness, tuple(matches),
                         "conflicting_rules" if matches else "ambiguous_or_unsupported_pose")


def classify_frame(features: FrameFeatures,
                   *, thresholds: StaticThresholds = DEFAULT_THRESHOLDS) -> tuple[GestureResult, ...]:
    """Frame-local results only; order and handedness must not become persistent IDs."""
    return tuple(classify_hand(hand, features.observation.timestamp_ms, thresholds=thresholds)
                 for hand in features.hands)
