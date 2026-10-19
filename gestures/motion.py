"""Aspect-correct palm-anchor samples and bounded-trajectory measurements."""

from dataclasses import dataclass
import math

from .features import HandFeatures
from .models import ImageSize, LandmarkIndex as I, finite_number


PALM_ANCHORS = (I.WRIST, I.INDEX_FINGER_MCP, I.MIDDLE_FINGER_MCP, I.RING_FINGER_MCP, I.PINKY_MCP)


@dataclass(frozen=True, slots=True)
class MotionSample:
    timestamp_ms: int
    x: float  # Normalized image-width units.
    y: float  # Normalized image y * height/width.
    scale: float


@dataclass(frozen=True, slots=True)
class MotionMetrics:
    dx: float
    dy: float
    travel: float
    duration_ms: int
    velocity_x: float
    consistency: float
    dominance: float
    scale_change: float
    recent_velocity_x: float


def palm_sample(features: HandFeatures | None, timestamp_ms: int) -> MotionSample | None:
    """Reuse cached palm scale; use no fingertips or normalized-position/scale division."""
    try:
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            return None
        if not isinstance(features, HandFeatures) or not isinstance(features.image_size, ImageSize):
            return None
        scale = finite_number(features.palm_scale, "Palm scale")
        if scale <= 1e-9:
            return None
        points = [features.observation[index] for index in PALM_ANCHORS]
        x = math.fsum(finite_number(p.x, "Palm x") for p in points) / len(points)
        y = math.fsum(finite_number(p.y, "Palm y") for p in points) / len(points)
        y *= features.image_size.height / features.image_size.width
        return MotionSample(timestamp_ms, finite_number(x, "Anchor x"), finite_number(y, "Anchor y"), scale)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def trajectory_metrics(samples: tuple[MotionSample, ...]) -> MotionMetrics:
    """Displacements/path are normalized to the first sample's fixed palm scale.

    Dominance uses total vertical travel, so an up/down zigzag cannot cancel out.
    The ratio has a 0.01-palm floor rather than producing infinity for flat paths.
    """
    if len(samples) < 2:
        raise ValueError("A trajectory needs at least two samples")
    for sample in samples:
        if (not isinstance(sample, MotionSample) or isinstance(sample.timestamp_ms, bool)
                or not isinstance(sample.timestamp_ms, int) or sample.timestamp_ms < 0
                or finite_number(sample.scale, "Scale") <= 1e-9):
            raise ValueError("Invalid motion sample")
        finite_number(sample.x, "Anchor x")
        finite_number(sample.y, "Anchor y")
    if any(b.timestamp_ms <= a.timestamp_ms for a, b in zip(samples, samples[1:])):
        raise ValueError("Trajectory time must strictly increase")
    first, last = samples[0], samples[-1]
    scale = first.scale
    dx, dy = (last.x-first.x)/scale, (last.y-first.y)/scale
    steps = [((b.x-a.x)/scale, (b.y-a.y)/scale) for a, b in zip(samples, samples[1:])]
    horizontal = math.fsum(abs(x) for x, _ in steps)
    vertical = math.fsum(abs(y) for _, y in steps)
    travel = math.fsum(math.hypot(x, y) for x, y in steps)
    duration = last.timestamp_ms-first.timestamp_ms
    recent = next((sample for sample in samples if sample.timestamp_ms >= last.timestamp_ms-80), first)
    if recent.timestamp_ms == last.timestamp_ms:
        recent = samples[-2]  # Sparse observations still require an actual time interval.
    recent_velocity = (last.x-recent.x)/scale*1000/(last.timestamp_ms-recent.timestamp_ms)
    values = (dx, dy, travel, dx*1000/duration, abs(dx)/horizontal if horizontal else 0.,
              abs(dx)/max(vertical, .01), max(abs(s.scale/scale-1) for s in samples), recent_velocity)
    for value in values:
        finite_number(value, "Motion metric")
    return MotionMetrics(values[0], values[1], values[2], duration, *values[3:])
