"""Original, unmirrored image pixels and normalized half-frame errors only."""

from dataclasses import dataclass
import math
from numbers import Real

from .face_geometry import dimensions


def finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def point(value, bounds):
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or any(not finite(v) or not 0 <= v <= maximum for v, maximum in zip(value, bounds))):
        raise ValueError("Coordinates must be finite in-frame X/Y values")
    return tuple(map(float, value))


@dataclass(frozen=True, slots=True)
class PositionError:
    target_center: tuple[float, float]
    pixel_error: tuple[float, float]
    normalized_error: tuple[float, float]


def calculate_offsets(center, frame_size, *, target=(.5, .5)):
    """Positive X means pan right; positive Y means tilt down, not servo polarity.

    Target is a normalized [0,1] image point. Errors divide by W/2,H/2 even
    for custom targets, so off-center targets can have errors outside [-1,1].
    """
    width, height = dimensions(frame_size)
    x, y = point(center, (width, height))
    tx, ty = point(target, (1, 1))
    desired = tx*width, ty*height
    pixels = x-desired[0], y-desired[1]
    return PositionError(desired, pixels, (pixels[0]/(width/2), pixels[1]/(height/2)))
