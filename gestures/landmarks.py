"""Structural Tasks-result adapter and explicit coordinate conversion; no SDK import."""

from collections.abc import Sequence

from .models import (
    FrameObservation, HandednessPrediction, HandObservation, ImageSize, Landmark, LANDMARK_COUNT, MAX_HANDS,
    finite_number,
)


def _predictions(categories: object) -> tuple[HandednessPrediction, ...]:
    if not isinstance(categories, Sequence) or isinstance(categories, (str, bytes)):
        return ()
    predictions = []
    for category in categories:
        try:
            prediction = HandednessPrediction(getattr(category, "category_name", None),
                                              getattr(category, "score", None))
        except ValueError:
            # Bad optional metadata must not discard a valid geometric observation.
            continue
        if prediction.category_name is not None or prediction.score is not None:
            predictions.append(prediction)
    return tuple(predictions)


def from_mediapipe(result: object, timestamp_ms: int,
                   image_size: ImageSize | None = None) -> FrameObservation:
    """Snapshot raw or existing EMA Tasks results, pairing metadata within this frame.

    Reject malformed geometry instead of silently truncating/skipping hands. Missing
    handedness becomes an empty tuple; invalid optional categories are discarded.
    Returned tuple order is frame-local only and does not establish track identity.
    """
    hands = getattr(result, "hand_landmarks", None)
    if not isinstance(hands, Sequence) or isinstance(hands, (str, bytes)):
        raise ValueError("Result must provide a hand_landmarks sequence (empty for zero hands)")
    if len(hands) > MAX_HANDS:
        raise ValueError(f"Expected at most {MAX_HANDS} hands; refusing to truncate")
    handedness = getattr(result, "handedness", None)
    if not isinstance(handedness, Sequence) or isinstance(handedness, (str, bytes)):
        handedness = ()
    observations = []
    for hand_index, points in enumerate(hands):
        if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
            raise ValueError(f"Hand {hand_index}: landmarks must be a sequence")
        if len(points) != LANDMARK_COUNT:
            raise ValueError(f"Hand {hand_index}: expected exactly {LANDMARK_COUNT} landmarks")
        converted = []
        for point_index, point in enumerate(points):
            try:
                converted.append(Landmark(
                    getattr(point, "x", None), getattr(point, "y", None), getattr(point, "z", None),
                    getattr(point, "visibility", None), getattr(point, "presence", None)))
            except ValueError as exc:
                raise ValueError(f"Hand {hand_index}, landmark {point_index}: {exc}") from exc
        categories = handedness[hand_index] if hand_index < len(handedness) else ()
        observations.append(HandObservation(tuple(converted), _predictions(categories)))
    return FrameObservation(timestamp_ms, tuple(observations), image_size)


def to_image_coordinates(point: Landmark, image_size: ImageSize,
                         *, clip: bool = False) -> tuple[float, float]:
    """Continuous image x/y = normalized x*width, y*height; no rounding by default.

    clip=True explicitly clamps to valid pixel-center bounds [0, width-1]/[0, height-1].
    Geometry should use unclipped coordinates; z is not a pixel-space depth.
    """
    if not isinstance(point, Landmark) or not isinstance(image_size, ImageSize):
        raise ValueError("Image conversion requires Landmark and ImageSize instances")
    if not isinstance(clip, bool):
        raise ValueError("clip must be a boolean")
    x = finite_number(point.x * image_size.width, "Image x")
    y = finite_number(point.y * image_size.height, "Image y")
    if clip:
        x = max(0.0, min(image_size.width - 1.0, x))
        y = max(0.0, min(image_size.height - 1.0, y))
    return x, y
