"""Immutable session-local observations. IDs describe continuity, never identity."""

from dataclasses import dataclass
from enum import StrEnum

from .face_models import FaceDetection


class TrackState(StrEnum):
    TENTATIVE = "TENTATIVE"
    TRACKED = "TRACKED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class FaceTrack:
    track_id: int
    state: TrackState
    raw: FaceDetection | None
    smoothed: FaceDetection | None
    confidence: float | None
    first_seen: float
    last_detected: float
    observation_age: float
    consecutive_matches: int
    consecutive_misses: int
    primary: bool
    uncertain: bool

    @property
    def detected(self):
        return self.raw is not None


@dataclass(frozen=True, slots=True)
class TrackedFaces:
    timestamp_ms: int
    frame_size: tuple[int, int]
    tracks: tuple[FaceTrack, ...]
    primary_id: int | None
    unassigned: tuple[FaceDetection, ...] = ()
    status: str = "valid"

    @property
    def primary(self):
        return next((track for track in self.tracks if track.track_id == self.primary_id), None)
