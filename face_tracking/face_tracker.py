"""Bounded spatial continuity, conservative target locking, independent temporal EMA.

No camera, native input, model, or hand-controller dependencies. Ambiguous IDs
are quarantined until expiration: spatial evidence cannot establish identity.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
import math
from numbers import Integral, Real
import time

from .face_geometry import convert_box, dimensions
from .face_models import FaceDetection
from .track_models import FaceTrack, TrackedFaces, TrackState


@dataclass(frozen=True, slots=True)
class TrackerConfig:
    confirmation_hits: int = 3
    confirmation_seconds: float = .06
    lost_timeout: float = .8
    smoothing_tau: float = .07
    max_tracks: int = 8
    confirmation_gap: float = .25
    smoothing_reset_gap: float = .25

    def __post_init__(self):
        for name, maximum in (("confirmation_hits", 100), ("max_tracks", 8)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer within [1,{maximum}]")
        for name in ("confirmation_seconds", "lost_timeout", "smoothing_tau",
                     "confirmation_gap", "smoothing_reset_gap"):
            value = getattr(self, name)
            if not _finite(value) or value < 0 or (name in ("lost_timeout", "confirmation_gap") and value == 0):
                raise ValueError(f"{name} must be finite and nonnegative (timeouts/gaps positive)")


def _finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _center(face):
    return face.normalized_center_x, face.normalized_center_y


def _size(face):
    b = face.box_normalized
    return b.x_max-b.x_min, b.y_max-b.y_min


def _iou(a, b):
    a, b = a.box_normalized, b.box_normalized
    intersection = max(0., min(a.x_max, b.x_max)-max(a.x_min, b.x_min)) * max(0., min(a.y_max, b.y_max)-max(a.y_min, b.y_min))
    return intersection / max(1e-12, a.area+b.area-intersection)


def _geometry_key(face):
    b = face.box_normalized
    return b.x_min, b.y_min, b.x_max, b.y_max, -(face.confidence if face.confidence is not None else -1.)


@dataclass(slots=True)
class _Track:
    key: int
    raw: FaceDetection
    smooth: FaceDetection
    first_seen: float
    last_detected: float
    streak_started: float
    matches: int = 1
    misses: int = 0
    confirmed: bool = False
    visible: bool = True
    uncertain: bool = False


class FaceTracker:
    def __init__(self, config=None):
        self.config = config or TrackerConfig()
        self._tracks = {}
        self._next_id = 1
        self._primary = None
        self._after_lock_loss = False
        self._last_stamp = self._last_now = self._last_observed = self._size = None
        self.counts = Counter()

    def reset(self):
        """Drop histories, retaining the session ID allocator and clock fences."""
        self._tracks.clear()
        self._primary = None
        self._after_lock_loss = True
        self._size = None
        self.counts["resets"] += 1

    def metadata(self):
        return {"enabled": True, "config": asdict(self.config), "counters": dict(self.counts),
                "counter_scope": "whole session including warmup", "active_tracks": len(self._tracks),
                "primary_id": self._primary, "ids_allocated": self._next_id-1,
                "identity_switches": None,
                "identity_switches_reason": "No real-person identity ground truth; see synthetic sequence benchmark",
                "ambiguity_policy": "quarantine involved IDs until expiration; no spatial identity guarantee"}

    def _cost(self, track, face, observed):
        dt = observed-track.last_detected
        if dt <= 0 or track.uncertain:
            return None
        distance = math.dist(_center(track.raw), _center(face))
        # Speed gate expands with elapsed time, but lost-target recovery is stricter.
        gate = min(.18 if track.visible and dt <= self.config.confirmation_gap else .08, .035+1.5*dt)
        sizes = tuple(zip(_size(track.raw), _size(face)))
        scale = max(max(a/b, b/a) for a, b in sizes)
        if distance > gate or scale > 2.:
            return None
        return .55*(1-_iou(track.raw, face)) + .35*distance/gate + .10*math.log(scale)/math.log(2)

    @staticmethod
    def _solve(costs, detections, forbidden=None):
        # At most 8x8; O(tracks * 2**detections * detections). Maximize valid
        # matches, then minimize total cost; deterministic lexicographic ties.
        @lru_cache(None)
        def solve(row, used):
            if row == len(costs):
                return 0, 0., ()
            n, c, path = solve(row+1, used)
            best = n, c, (-1,)+path
            for col in range(detections):
                value = costs[row][col]
                if value is None or used & (1 << col) or forbidden == (row, col):
                    continue
                n, c, path = solve(row+1, used | (1 << col))
                candidate = n+1, c+value, (col,)+path
                if (-candidate[0], candidate[1], candidate[2]) < (-best[0], best[1], best[2]):
                    best = candidate
            return best
        return solve(0, 0)

    def _associate(self, tracks, faces, observed):
        costs = [[self._cost(track, face, observed) for face in faces] for track in tracks]
        count, cost, assignment = self._solve(costs, len(faces))
        uncertain_rows, uncertain_cols = set(), set()
        # A near-equal complete assignment is evidence of uncertainty. Also
        # detect collapsed/duplicate boxes even when only one old track exists.
        for row, col in enumerate(assignment):
            if col < 0:
                continue
            n, alternative_cost, alternative = self._solve(costs, len(faces), (row, col))
            if n == count and alternative_cost-cost < .10:
                for i, (a, b) in enumerate(zip(assignment, alternative)):
                    if a != b:
                        uncertain_rows.add(i)
                        uncertain_cols.update(c for c in (a, b) if c >= 0)
        for i, face in enumerate(faces):
            for j in range(i):
                if _iou(face, faces[j]) > .35 or math.dist(_center(face), _center(faces[j])) < .5*min(*_size(face), *_size(faces[j])):
                    uncertain_cols.update((i, j))
        # Do not create replacements near quarantined tracks before expiration.
        for track in tracks:
            if track.uncertain:
                uncertain_cols.update(i for i, face in enumerate(faces)
                                      if math.dist(_center(track.raw), _center(face)) <= .18 or _iou(track.raw, face) > 0)
        # Close the whole competing component, including unmatched columns.
        # Otherwise an ambiguous row's second detection could acquire a new ID
        # in the very frame in which its old ID was withheld.
        while True:
            previous = len(uncertain_rows), len(uncertain_cols)
            for row, values in enumerate(costs):
                if row in uncertain_rows:
                    uncertain_cols.update(col for col, value in enumerate(values) if value is not None)
                if any(values[col] is not None for col in uncertain_cols):
                    uncertain_rows.add(row)
            if previous == (len(uncertain_rows), len(uncertain_cols)):
                break
        return assignment, uncertain_rows, uncertain_cols

    def _snapshot(self, track, now, expired=False):
        state = (TrackState.EXPIRED if expired else TrackState.LOST if not track.visible else
                 TrackState.TRACKED if track.confirmed else TrackState.TENTATIVE)
        current = track.visible and not expired
        return FaceTrack(track.key, state, track.raw if current else None, track.smooth if current else None,
                         track.raw.confidence, track.first_seen, track.last_detected,
                         max(0., now-track.last_detected), track.matches, track.misses,
                         track.key == self._primary and not expired, track.uncertain)

    def _miss(self, track):
        if track.visible and track.key == self._primary:
            self.counts["primary_loss_events"] += 1
        track.visible = False
        track.matches = 0
        track.misses += 1

    def update(self, frame, *, observed_at=None, now=None, profile=None):
        """Host monotonic seconds for freshness; source milliseconds for replay fencing.

        Defaults to source time for deterministic offline callers. In the app,
        observed_at is camera read completion, now is post-inference host time.
        """
        profiled = profile is not None and profile.enabled
        started = time.perf_counter() if profiled else None
        stamp = frame.timestamp_ms
        stamp_valid = isinstance(stamp, Integral) and not isinstance(stamp, bool) and 0 <= stamp <= 2**63-1
        observed = observed_at if observed_at is not None else stamp/1000 if stamp_valid else None
        current = now if now is not None else observed
        valid = (stamp_valid and _finite(observed) and _finite(current) and 0 <= observed <= current
                 and (self._last_stamp is None or stamp > self._last_stamp)
                 and (self._last_observed is None or observed > self._last_observed)
                 and (self._last_now is None or current >= self._last_now))
        clock = max(self._last_now or 0., current if _finite(current) and current >= 0 else 0.)
        size = dimensions(frame.frame_size)
        expired = []
        for key, track in tuple(self._tracks.items()):
            if clock-track.last_detected > self.config.lost_timeout or self._size not in (None, size):
                expired.append(self._snapshot(track, clock, expired=True))
                del self._tracks[key]
                self.counts["expired"] += 1
                if self._primary == key:
                    self._primary = None
                    self._after_lock_loss = True
                    self.counts["primary_expirations"] += 1
        self._last_now = clock
        self._size = size
        faces = ()
        status = "valid"
        if valid:
            self._last_stamp, self._last_observed = int(stamp), observed
            # Canonicalize/validate public inputs; never ingest corrupt geometry.
            try:
                if len(frame.faces) > self.config.max_tracks:
                    status = "capacity_exceeded"
                elif frame.status != "expired" and clock-observed <= .25:
                    faces = tuple(sorted((self._canonical(face, size) for face in frame.faces), key=_geometry_key))
                else:
                    status = "stale_frame"
            except (ValueError, TypeError, AttributeError, OverflowError):
                status = "invalid_geometry"
        else:
            status = "invalid_timestamp"
        tracks = list(self._tracks.values())
        before_association = time.perf_counter() if profiled else None
        assignment, uncertain_rows, uncertain_cols = self._associate(tracks, faces, observed) if valid else ((-1,)*len(tracks), set(), set())
        if profiled:
            after_association = time.perf_counter()
            profile.add("face_association", after_association-before_association)
        smoothing_seconds = 0.
        used = set()
        for row, track in enumerate(tracks):
            col = assignment[row]
            if row in uncertain_rows:
                if not track.uncertain:
                    self.counts["quarantined_tracks"] += 1
                track.uncertain = True
            if col < 0 or row in uncertain_rows or col in uncertain_cols:
                self._miss(track)
                continue
            face = faces[col]
            used.add(col)
            dt = observed-track.last_detected
            recovering = not track.visible
            if recovering:
                self.counts["plausible_reacquisitions"] += 1
                if track.key == self._primary:
                    self.counts["primary_reacquisitions"] += 1
            if recovering or dt > self.config.confirmation_gap:
                track.matches = 0
                track.streak_started = observed
            track.matches += 1
            before_smoothing = time.perf_counter() if profiled else None
            if recovering or dt > self.config.smoothing_reset_gap or self.config.smoothing_tau == 0:
                track.smooth = face
            else:
                alpha = -math.expm1(-dt/self.config.smoothing_tau)
                previous, current_box = track.smooth.box_normalized, face.box_normalized
                edges = tuple(a+alpha*(b-a) for a, b in zip(
                    (previous.x_min, previous.y_min, previous.x_max, previous.y_max),
                    (current_box.x_min, current_box.y_min, current_box.x_max, current_box.y_max)))
                track.smooth = convert_box(edges[0], edges[1], edges[2]-edges[0], edges[3]-edges[1], (1, 1), size, face.confidence)
            if profiled:
                smoothing_seconds += time.perf_counter()-before_smoothing
            track.raw = face
            track.last_detected = observed
            track.visible = True
            track.misses = 0
            self._confirm(track, observed)
        unassigned = []
        for col, face in enumerate(faces):
            if col in used:
                continue
            if col in uncertain_cols or len(self._tracks) >= self.config.max_tracks:
                unassigned.append(face)
                continue
            key = self._next_id
            self._next_id += 1
            track = _Track(key, face, face, observed, observed, observed)
            self._confirm(track, observed)
            self._tracks[key] = track
            self.counts["created"] += 1
        if self._primary is None:
            candidates = [t for t in self._tracks.values() if t.visible and t.confirmed and not t.uncertain]
            # After expiration/reset, all visible detections (even tentative or
            # unassigned) must agree there is just one candidate in the scene.
            if candidates and (not self._after_lock_loss or len(faces) == 1 and len(candidates) == 1 and not unassigned):
                chosen = min(candidates, key=lambda t: (-(t.raw.confidence if t.raw.confidence is not None else -1.),
                                                       -t.raw.box_normalized.area, _geometry_key(t.raw), t.key))
                self._primary = chosen.key
                self.counts["primary_acquisitions"] += 1
        if uncertain_rows or uncertain_cols:
            status = "uncertain"
            self.counts["ambiguous_frames"] += 1
        if status != "valid":
            self.counts[status] += 1
        snapshots = tuple(self._snapshot(track, clock) for track in self._tracks.values())+tuple(expired)
        output = TrackedFaces(int(stamp) if stamp_valid else -1, size, snapshots, self._primary, tuple(unassigned), status)
        if profiled:
            ended = time.perf_counter()
            profile.add("face_smoothing", smoothing_seconds)
            profile.add("face_tracking", ended-started)
            for track in snapshots:
                if track.detected:
                    profile.add("face_observation_age", track.observation_age)
        return output

    def _confirm(self, track, observed):
        if track.matches >= self.config.confirmation_hits and observed-track.streak_started+1e-12 >= self.config.confirmation_seconds:
            track.confirmed = True

    @staticmethod
    def _canonical(face, size):
        if not isinstance(face, FaceDetection):
            raise ValueError("Expected a FaceDetection")
        b = face.box_normalized
        if not all(_finite(v) and 0 <= v <= 1 for v in (b.x_min, b.y_min, b.x_max, b.y_max)):
            raise ValueError("Invalid normalized bounding box")
        return convert_box(b.x_min, b.y_min, b.x_max-b.x_min, b.y_max-b.y_min, (1, 1), size, face.confidence)
