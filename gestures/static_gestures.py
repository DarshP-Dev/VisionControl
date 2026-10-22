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
    pointing_index_joint_min_degrees: float = 145
    pointing_curled_tip_to_wrist_max: float = 1.65
    pointing_tip_separation_min: float = .25
    unsupported_thumb_tip_to_wrist_min: float = 1.35

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
class PointingCheck:
    finger: Finger | None
    measurement: str
    value: float | None
    comparison: str
    threshold: float
    passed: bool


@dataclass(frozen=True, slots=True)
class GestureResult:
    gesture: Gesture
    timestamp_ms: int
    handedness: tuple[HandednessPrediction, ...] = ()
    matched_rules: tuple[Gesture, ...] = ()
    reason: str = ""
    pointing_checks: tuple[PointingCheck, ...] = ()
    track_id: int | None = None  # Optional caller-assigned observation namespace, not recognition evidence.

    def __post_init__(self) -> None:
        if self.track_id is not None and (isinstance(self.track_id, bool) or not isinstance(self.track_id, int)
                                          or self.track_id <= 0):
            raise ValueError("Track ID must be a positive integer or None")
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


def _pointing_evaluation(values: tuple[tuple[float, ...], ...] | None,
                         features: HandFeatures | None, thresholds: StaticThresholds,
                         collect: bool) -> tuple[bool, tuple[PointingCheck, ...]]:
    """The same comparisons drive classification and optional sampled diagnostics."""
    if values is None and not collect:
        return False, ()
    checks = [] if collect else None
    matched = values is not None

    def require(finger: Finger | None, name: str, value: float | None,
                comparison: str, bound: float) -> None:
        nonlocal matched
        try:
            actual = finite_number(value, name)
        except ValueError:
            actual = None
        if collect and actual is not None:
            if ("degrees" in name and not 0 <= actual <= 180
                    or name == "straightness" and not 0 <= actual <= 1
                    or name == "tip_to_wrist" and actual < 0):
                actual = None
        passed = actual is not None and (actual >= bound if comparison == ">=" else
                                        actual <= bound if comparison == "<=" else actual > bound)
        matched = matched and passed
        if checks is not None:
            checks.append(PointingCheck(finger, name, actual, comparison, bound, passed))

    if values is None:
        rows = []
        for finger in LONG_FINGERS:
            try:
                item = features.finger(finger)
                rows.append((item.joint_angle_degrees, item.distal_angle_degrees,
                             item.straightness_ratio, item.tip_to_wrist_ratio))
            except (ValueError, AttributeError, TypeError):
                rows.append((None,) * 4)
        require(None, "required_features_valid", 0, ">=", 1)
        require(None, "palm_scale", getattr(features, "palm_scale", None), ">", 0)
    else:
        rows = values
    index_tip = rows[0][3]
    for index, (finger, row) in enumerate(zip(LONG_FINGERS, rows)):
        joint, distal, straight, tip = row
        if index == 0:
            require(finger, "PIP_degrees", joint, ">=", thresholds.pointing_index_joint_min_degrees)
            require(finger, "DIP_degrees", distal, ">=", thresholds.extended_distal_min_degrees)
            require(finger, "straightness", straight, ">=", thresholds.extended_straightness_min)
            require(finger, "tip_to_wrist", tip, ">=", thresholds.extended_tip_to_wrist_min)
        else:
            require(finger, "PIP_degrees", joint, "<=", thresholds.curled_joint_max_degrees)
            # A folded PIP and short chord establish curl even with a relaxed,
            # straight distal segment. DIP validity is still checked above;
            # the strict FIST definition retains its independent DIP bound.
            if collect:
                require(finger, "DIP_degrees_valid", distal, "<=", 180)
            require(finger, "straightness", straight, "<=", thresholds.curled_straightness_max)
            require(finger, "tip_to_wrist", tip, "<=", thresholds.pointing_curled_tip_to_wrist_max)
            try:
                gap = finite_number(index_tip, "Index tip ratio") - finite_number(tip, "Other tip ratio")
            except ValueError:
                gap = None
            require(finger, "index_tip_separation", gap, ">=", thresholds.pointing_tip_separation_min)
    return matched, tuple(checks) if checks is not None else ()


def _clearly_extended_thumb(features: HandFeatures, thresholds: StaticThresholds) -> bool:
    """Exclude unsupported thumb-only extension from FIST; do not gate POINTING."""
    try:
        thumb = features.finger(Finger.THUMB)
        return (finite_number(thumb.joint_angle_degrees, "Thumb joint") >= thresholds.extended_joint_min_degrees
                and finite_number(thumb.distal_angle_degrees, "Thumb distal") >= thresholds.extended_distal_min_degrees
                and finite_number(thumb.straightness_ratio, "Thumb straightness") >= thresholds.extended_straightness_min
                and finite_number(thumb.tip_to_wrist_ratio, "Thumb tip") >= thresholds.unsupported_thumb_tip_to_wrist_min)
    except (ValueError, AttributeError, TypeError):
        return False


def classify_hand(features: HandFeatures | None, timestamp_ms: int,
                  *, thresholds: StaticThresholds = DEFAULT_THRESHOLDS,
                  diagnostics: bool = False, track_id: int | None = None) -> GestureResult:
    """Classify cached 2D features; thumb posture does not gate POINTING.

    Supply aspect-correct features for camera inputs. A detected hand with invalid
    required features is UNKNOWN; no observation is represented by no call/result.
    Optional track_id is caller-assigned metadata and never changes the rules.
    """
    handedness = (features.observation.handedness
                  if isinstance(features, HandFeatures) and isinstance(features.observation, HandObservation)
                  else ())
    values = _required_measurements(features)
    pointing, checks = _pointing_evaluation(values, features, thresholds, diagnostics)
    if values is None:
        return GestureResult(Gesture.UNKNOWN, timestamp_ms, handedness,
                             reason="invalid_or_missing_features", pointing_checks=checks, track_id=track_id)
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
    thumb_veto = all(curled) and _clearly_extended_thumb(features, thresholds)
    if all(curled) and not thumb_veto:
        matches.append(Gesture.FIST)
    if pointing:
        matches.append(Gesture.POINTING)
    if len(matches) == 1:
        return GestureResult(matches[0], timestamp_ms, handedness, tuple(matches), "unique_rule_match", checks, track_id)
    return GestureResult(Gesture.UNKNOWN, timestamp_ms, handedness, tuple(matches),
                         "conflicting_rules" if matches else "unsupported_thumb_extension" if thumb_veto
                         else "ambiguous_or_unsupported_pose", checks, track_id)


def classify_frame(features: FrameFeatures,
                   *, thresholds: StaticThresholds = DEFAULT_THRESHOLDS) -> tuple[GestureResult, ...]:
    """Frame-local results only; order and handedness must not become persistent IDs."""
    return tuple(classify_hand(hand, features.observation.timestamp_ms, thresholds=thresholds)
                 for hand in features.hands)
