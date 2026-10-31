"""Immutable output viewport geometry; coordinates are original-frame pixels."""

from dataclasses import dataclass
from enum import StrEnum

from .centering_geometry import finite


class ReframeStatus(StrEnum):
    TRACKING = "TRACKING"
    HOLDING = "HOLDING"


@dataclass(frozen=True, slots=True)
class CropRectangle:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def size(self):
        return self.right-self.left, self.bottom-self.top

    @property
    def center(self):
        return (self.left+self.right)/2, (self.top+self.bottom)/2


@dataclass(frozen=True, slots=True)
class ReframeResult:
    primary_id: int | None
    status: ReframeStatus
    reason: str
    source_size: tuple[int, int]
    crop_size: tuple[int, int]
    rectangle: CropRectangle
    center: tuple[float, float]  # Continuous animation state, not rounded slice origin.
    desired_center: tuple[float, float] | None
    target_in_crop: tuple[float, float] | None
    composition_error: tuple[float, float] | None
    horizontal_active: bool
    vertical_active: bool
    boundaries: tuple[str, ...]
    observation_timestamp: float | None
    observation_age: float | None
    updated_at: float | None
    fresh_target: bool
    moving: bool

    def fresh_at(self, now):
        return (self.fresh_target and finite(now) and self.updated_at is not None and now >= self.updated_at
                and self.observation_timestamp is not None and 0 <= now-self.observation_timestamp <= .25)
