"""Immutable observations; normalized image coordinates are not world coordinates."""

from dataclasses import dataclass
from collections.abc import Sequence
from enum import IntEnum, StrEnum
import math
from numbers import Real


class LandmarkIndex(IntEnum):
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_FINGER_MCP = 5
    INDEX_FINGER_PIP = 6
    INDEX_FINGER_DIP = 7
    INDEX_FINGER_TIP = 8
    MIDDLE_FINGER_MCP = 9
    MIDDLE_FINGER_PIP = 10
    MIDDLE_FINGER_DIP = 11
    MIDDLE_FINGER_TIP = 12
    RING_FINGER_MCP = 13
    RING_FINGER_PIP = 14
    RING_FINGER_DIP = 15
    RING_FINGER_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


LANDMARK_COUNT = len(LandmarkIndex)
MAX_HANDS = 2


class HandSide(StrEnum):
    LEFT = "Left"
    RIGHT = "Right"
    UNKNOWN = "Unknown"


class Finger(StrEnum):
    THUMB = "thumb"
    INDEX = "index"
    MIDDLE = "middle"
    RING = "ring"
    PINKY = "pinky"


def finite_number(value: Real, name: str) -> float:
    """Reject strings, booleans, missing values and non-finite numeric inputs."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite real number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite real number")
    return number


def _typed_tuple(values: object, item_type: type, name: str) -> tuple:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of {item_type.__name__}")
    items = tuple(values)
    if any(not isinstance(item, item_type) for item in items):
        raise ValueError(f"{name} must contain only {item_type.__name__}")
    return items


@dataclass(frozen=True, slots=True)
class ImageSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Image {name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class Landmark:
    x: float
    y: float
    z: float
    # Preserve optional model values without assuming these are calibrated probabilities.
    visibility: float | None = None
    presence: float | None = None

    def __post_init__(self) -> None:
        for name in ("x", "y", "z", "visibility", "presence"):
            value = getattr(self, name)
            if value is not None or name in ("x", "y", "z"):
                object.__setattr__(self, name, finite_number(value, name))


@dataclass(frozen=True, slots=True)
class HandednessPrediction:
    category_name: str | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        if self.category_name is not None and not isinstance(self.category_name, str):
            raise ValueError("Handedness category name must be a string or None")
        if self.score is not None:
            score = finite_number(self.score, "Handedness score")
            if not 0 <= score <= 1:
                raise ValueError("Handedness score must be between zero and one")
            object.__setattr__(self, "score", score)

    @property
    def side(self) -> HandSide:
        """A prediction label only; neither an identity nor a confidence decision."""
        try:
            return HandSide(self.category_name)
        except ValueError:
            return HandSide.UNKNOWN


@dataclass(frozen=True, slots=True)
class HandObservation:
    landmarks: tuple[Landmark, ...]
    handedness: tuple[HandednessPrediction, ...] = ()

    def __post_init__(self) -> None:
        points = _typed_tuple(self.landmarks, Landmark, "Landmarks")
        if len(points) != LANDMARK_COUNT:
            raise ValueError(f"A hand must have exactly {LANDMARK_COUNT} landmarks")
        object.__setattr__(self, "landmarks", points)
        object.__setattr__(self, "handedness",
                           _typed_tuple(self.handedness, HandednessPrediction, "Handedness"))

    def __getitem__(self, index: LandmarkIndex | int) -> Landmark:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < LANDMARK_COUNT:
            raise ValueError(f"Landmark index must be an integer in [0, {LANDMARK_COUNT - 1}]")
        return self.landmarks[index]


@dataclass(frozen=True, slots=True)
class FrameObservation:
    timestamp_ms: int
    hands: tuple[HandObservation, ...] = ()
    image_size: ImageSize | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.timestamp_ms, bool) or not isinstance(self.timestamp_ms, int)
                or self.timestamp_ms < 0):
            raise ValueError("Timestamp must be a nonnegative integer number of milliseconds")
        hands = _typed_tuple(self.hands, HandObservation, "Hands")
        if len(hands) > MAX_HANDS:
            raise ValueError(f"A frame supports at most {MAX_HANDS} hands")
        if self.image_size is not None and not isinstance(self.image_size, ImageSize):
            raise ValueError("Image size must be ImageSize or None")
        object.__setattr__(self, "hands", hands)
