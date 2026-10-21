"""Small, stateless geometric operations; angles use degrees, distances use input units."""

from collections.abc import Sequence
import math
from typing import Literal

from .models import HandObservation, ImageSize, Landmark, LandmarkIndex, finite_number


Dimensions = Literal[2, 3]
Vector = tuple[float, ...]


def _coordinates(point: Landmark, dimensions: Dimensions, image_size: ImageSize | None) -> Vector:
    if not isinstance(point, Landmark):
        raise ValueError("Geometry requires a validated Landmark; adapt SDK results first")
    if not isinstance(dimensions, int) or dimensions not in (2, 3) or isinstance(dimensions, bool):
        raise ValueError("Dimensions must be 2 or 3")
    if image_size is not None and not isinstance(image_size, ImageSize):
        raise ValueError("Image size must be ImageSize or None")
    # In this optional common-axis space, x and z retain image-width units.
    y_scale = image_size.height / image_size.width if image_size is not None else 1.0
    values = (point.x, point.y * y_scale) if dimensions == 2 else (point.x, point.y * y_scale, point.z)
    return tuple(finite_number(value, "Coordinate") for value in values)


def _vector(values: Sequence[float]) -> Vector:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) not in (2, 3):
        raise ValueError("A vector must have two or three components")
    return tuple(finite_number(value, "Vector component") for value in values)


def vector_between(start: Landmark, end: Landmark, *, dimensions: Dimensions = 2,
                   image_size: ImageSize | None = None) -> Vector:
    """Return end-start; supply image_size for aspect-correct image geometry."""
    first, second = _coordinates(start, dimensions, image_size), _coordinates(end, dimensions, image_size)
    return _vector(tuple(b - a for a, b in zip(first, second)))


def magnitude(vector: Sequence[float]) -> float:
    return finite_number(math.hypot(*_vector(vector)), "Vector magnitude")


def normalize(vector: Sequence[float]) -> Vector:
    """Return a unit vector; zero length has no direction and raises ValueError."""
    return _normalize_values(_vector(vector))


def _normalize_values(values: Vector) -> Vector:
    """Internal path for already validated finite vectors; keep scaled arithmetic."""
    scale = max(abs(value) for value in values)
    if scale == 0:
        raise ValueError("Cannot normalize a zero-length vector")
    scaled = tuple(value / scale for value in values)
    length = math.hypot(*scaled)
    return tuple(value / length for value in scaled)


def dot(first: Sequence[float], second: Sequence[float]) -> float:
    a, b = _vector(first), _vector(second)
    if len(a) != len(b):
        raise ValueError("Dot product vectors must have the same dimensions")
    try:
        value = math.fsum(x * y for x, y in zip(a, b))
    except (OverflowError, ValueError) as exc:
        raise ValueError("Dot product is not finite") from exc
    return finite_number(value, "Dot product")


def distance_2d(first: Landmark, second: Landmark, *, image_size: ImageSize | None = None) -> float:
    a, b = _coordinates(first, 2, image_size), _coordinates(second, 2, image_size)
    return finite_number(math.dist(a, b), "Vector magnitude")


def distance_3d(first: Landmark, second: Landmark, *, image_size: ImageSize | None = None) -> float:
    """Estimated normalized depth is not metric world-space distance."""
    return magnitude(vector_between(first, second, dimensions=3, image_size=image_size))


def landmark_distance(hand: HandObservation, first: LandmarkIndex | int, second: LandmarkIndex | int,
                      *, dimensions: Dimensions = 2, image_size: ImageSize | None = None) -> float:
    return magnitude(vector_between(hand[first], hand[second], dimensions=dimensions, image_size=image_size))


def angle_degrees(first: Landmark, vertex: Landmark, last: Landmark, *, dimensions: Dimensions = 2,
                  image_size: ImageSize | None = None) -> float | None:
    """Interior angle at vertex in [0, 180]; None if either edge has zero length."""
    # Convert the shared vertex once. Edges are validated once, then reused by
    # magnitude/normalization/dot arithmetic without repeating public API guards.
    origin = _coordinates(vertex, dimensions, image_size)
    ends = (_coordinates(first, dimensions, image_size), _coordinates(last, dimensions, image_size))
    a, b = (_vector(tuple(value-base for value, base in zip(end, origin))) for end in ends)
    if (finite_number(math.hypot(*a), "Vector magnitude") == 0
            or finite_number(math.hypot(*b), "Vector magnitude") == 0):
        return None
    cosine = finite_number(math.fsum(x*y for x, y in zip(_normalize_values(a), _normalize_values(b))), "Dot product")
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def palm_scale(hand: HandObservation, *, dimensions: Dimensions = 2,
               image_size: ImageSize | None = None) -> float:
    """Mean of wrist-to-middle-MCP and index-MCP-to-pinky-MCP distances."""
    length = landmark_distance(hand, LandmarkIndex.WRIST, LandmarkIndex.MIDDLE_FINGER_MCP,
                               dimensions=dimensions, image_size=image_size)
    width = landmark_distance(hand, LandmarkIndex.INDEX_FINGER_MCP, LandmarkIndex.PINKY_MCP,
                              dimensions=dimensions, image_size=image_size)
    return length / 2 + width / 2


def normalized_distance(hand: HandObservation, first: LandmarkIndex | int, second: LandmarkIndex | int,
                        *, dimensions: Dimensions = 2, image_size: ImageSize | None = None) -> float:
    """Landmark distance / palm scale; zero palm scale raises ValueError."""
    scale = palm_scale(hand, dimensions=dimensions, image_size=image_size)
    if scale == 0:
        raise ValueError("Cannot normalize distance by zero palm scale")
    return finite_number(landmark_distance(hand, first, second, dimensions=dimensions,
                                           image_size=image_size) / scale, "Normalized distance")
