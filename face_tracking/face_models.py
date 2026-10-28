"""Immutable observations. Face order/primary selection applies to this frame only."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def area(self):
        return (self.x_max-self.x_min)*(self.y_max-self.y_min)


@dataclass(frozen=True, slots=True)
class FaceDetection:
    box_pixels: BoundingBox
    box_normalized: BoundingBox
    center_x: float
    center_y: float
    confidence: float | None
    offset_x: float
    offset_y: float
    normalized_offset_x: float
    normalized_offset_y: float

    @property
    def normalized_center_x(self):
        return (self.box_normalized.x_min+self.box_normalized.x_max)/2

    @property
    def normalized_center_y(self):
        return (self.box_normalized.y_min+self.box_normalized.y_max)/2


@dataclass(frozen=True, slots=True)
class FaceFrame:
    timestamp_ms: int
    frame_size: tuple[int, int]
    inference_size: tuple[int, int]
    faces: tuple[FaceDetection, ...] = ()
    primary_index: int | None = None
    status: str = "no_face"

    @property
    def primary(self):
        return self.faces[self.primary_index] if self.primary_index is not None else None
