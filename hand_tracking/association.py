"""Bounded geometric observation tracks; IDs do not identify people or ownership."""

from collections import Counter
from dataclasses import dataclass
import math

from gestures.geometry import distance_2d, palm_scale
from gestures.models import ImageSize, LandmarkIndex as I


ANCHORS = (I.WRIST, I.INDEX_FINGER_MCP, I.MIDDLE_FINGER_MCP, I.RING_FINGER_MCP, I.PINKY_MCP)
MAX_LOST_MS = 500
ASSIGNMENT_MARGIN = .20


@dataclass(frozen=True, slots=True)
class Association:
    track_id: int | None
    certain: bool
    reason: str
    cost: float | None = None  # Geometric cost, never a confidence probability.


@dataclass(frozen=True, slots=True)
class Descriptor:
    center: tuple[float, float]
    wrist: tuple[float, float]
    scale: float
    shape: tuple[float, ...]
    bounds: tuple[float, float, float, float]
    label: str | None
    score: float


def describe(hand, size):
    if hand is None or not isinstance(size, ImageSize):
        return None
    aspect = size.height / size.width
    scale = palm_scale(hand, image_size=size)
    if scale <= 1e-9:
        return None
    points = tuple((hand[i].x, hand[i].y * aspect) for i in ANCHORS)
    if not all(math.isfinite(v) and 0 <= v <= (1 if axis == 0 else aspect)
               for point in points for axis, v in enumerate(point)):
        return None
    center = tuple(math.fsum(point[i] for point in points) / 5 for i in (0, 1))
    shape = tuple(distance_2d(hand[I.WRIST], hand[i], image_size=size) / scale for i in ANCHORS[1:])
    predictions = hand.handedness
    prediction = max(predictions, key=lambda p: p.score or 0, default=None)
    return Descriptor(center, points[0], scale, shape,
                      (min(p[0] for p in points), min(p[1] for p in points),
                       max(p[0] for p in points), max(p[1] for p in points)),
                      prediction.category_name if prediction else None, prediction.score or 0 if prediction else 0)


def overlap(a, b):
    if math.dist(a.center, b.center) < .65 * min(a.scale, b.scale):
        return True
    x = max(0., min(a.bounds[2], b.bounds[2]) - max(a.bounds[0], b.bounds[0]))
    y = max(0., min(a.bounds[3], b.bounds[3]) - max(a.bounds[1], b.bounds[1]))
    areas = ((p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1]) for p in (a, b))
    return x * y > .15 * max(1e-12, min(areas))


@dataclass(slots=True)
class _Track:
    descriptor: Descriptor
    stamp: int
    velocity: tuple[float, float] = (0., 0.)
    visible: bool = True


class HandAssociator:
    def __init__(self, max_hands=4):
        if isinstance(max_hands, bool) or not isinstance(max_hands, int) or max_hands not in (1, 2, 3, 4):
            raise ValueError("Maximum hands must be 1, 2, 3 or 4")
        self.max_hands = max_hands
        self.tracks = {}
        self.next_id = 1
        self.last_stamp = self.size = None
        self.counts = Counter()

    def _retire(self, key):
        if self.tracks.pop(key, None) is not None:
            self.counts["retired"] += 1

    def _cost(self, track, current, stamp):
        elapsed = (stamp - track.stamp) / 1000
        gate = min(.16, .025 + 1.8 * elapsed)
        if (elapsed <= 0 or math.dist(track.descriptor.center, current.center) > gate
                or math.dist(track.descriptor.wrist, current.wrist) > gate * 1.3):
            return None
        scale_change = abs(math.log(current.scale / track.descriptor.scale))
        shape_change = math.sqrt(sum((a - b) ** 2 for a, b in zip(current.shape, track.descriptor.shape)) / 4)
        if scale_change > min(.6, .40 + elapsed * .6) or shape_change > .40:
            return None
        predicted = tuple(track.descriptor.center[i] + track.velocity[i] * min(.1, elapsed) for i in (0, 1))
        handedness = (.03 if track.descriptor.label != current.label
                      and min(track.descriptor.score, current.score) >= .8 else 0.)
        return (math.dist(predicted, current.center) / max(.025, current.scale, track.descriptor.scale)
                + .35 * scale_change + .15 * shape_change + handedness + (.12 if not track.visible else 0))

    def update(self, observations, stamp, size):
        if len(observations) > self.max_hands:
            raise ValueError("Detector returned more observations than the requested maximum")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
            raise ValueError("Association timestamp must be a nonnegative integer")
        bad_time = self.last_stamp is not None and stamp <= self.last_stamp
        if bad_time or self.last_stamp is not None and stamp - self.last_stamp > 250 or self.size != size:
            for key in tuple(self.tracks):
                self._retire(key)
        self.last_stamp = max(stamp, self.last_stamp or 0)
        self.size = size
        if bad_time:
            return tuple(Association(None, False, "invalid_time") for _ in observations)
        for key, track in tuple(self.tracks.items()):
            if stamp - track.stamp > MAX_LOST_MS:
                self._retire(key)
        descriptors = tuple(describe(hand, size) for hand in observations)
        track_ids = sorted(self.tracks)
        costs = [{key: cost for key in track_ids
                  if (cost := self._cost(self.tracks[key], item, stamp)) is not None and cost < 2.4}
                 if item is not None else {} for item in descriptors]
        # At most four observations and eight active/lost tracks. Exhaustive
        # global assignment with explicit births avoids order-dependent greed.
        choices = tuple(tuple(sorted(row)) + (None,) for row in costs)
        best_cost, best = math.inf, None
        alternatives = [{} for _ in observations]
        assignment = []
        def visit(index, used, total):
            nonlocal best_cost, best
            if index == len(observations):
                if total < best_cost:
                    best_cost, best = total, tuple(assignment)
                for i, key in enumerate(assignment):
                    alternatives[i][key] = min(total, alternatives[i].get(key, math.inf))
                return
            for key in choices[index]:
                if key is not None and key in used:
                    continue
                assignment.append(key)
                visit(index + 1, used | {key} if key is not None else used,
                      total + (2.4 if key is None else costs[index][key]))
                assignment.pop()
        visit(0, set(), 0.)
        uncertain = set()
        for i, item in enumerate(descriptors):
            if item is None:
                uncertain.add(i)
            if any(key != best[i] and value - best_cost < ASSIGNMENT_MARGIN
                   for key, value in alternatives[i].items()):
                uncertain.add(i)
            for j in range(i):
                if item is not None and descriptors[j] is not None and overlap(item, descriptors[j]):
                    uncertain.update((i, j))
        # An uncertain observation retires every plausible implicated track.
        # Separated reacquisition gets fresh IDs; no guessed crossing continuity.
        implicated = {key for i in uncertain for key in costs[i]}
        uncertain.update(i for i, key in enumerate(best) if key in implicated)
        for key in implicated:
            self._retire(key)
        output, visible = [], set()
        for i, item in enumerate(descriptors):
            if i in uncertain:
                self.counts["uncertain_observations"] += 1
                output.append(Association(None, False, "invalid_geometry" if item is None else "ambiguous_or_overlapping"))
                continue
            key = best[i]
            previous = self.tracks.get(key)
            reason = "matched" if previous is not None and previous.visible else "reacquired" if previous else "new"
            if reason == "reacquired":
                self.counts["reacquired"] += 1
            cost = costs[i].get(key)
            if previous is None:
                key, self.next_id = self.next_id, self.next_id + 1
                self.counts["created"] += 1
                velocity = (0., 0.)
            else:
                elapsed = (stamp - previous.stamp) / 1000
                velocity = tuple(.5 * previous.velocity[k] + .5 * (item.center[k] - previous.descriptor.center[k]) / elapsed
                                 for k in (0, 1))
                if previous.descriptor.label != item.label:
                    self.counts["handedness_changes"] += 1
            self.tracks[key] = _Track(item, stamp, velocity)
            visible.add(key)
            output.append(Association(key, True, reason, cost))
        for key, track in self.tracks.items():
            if key not in visible and track.visible:
                self.counts["temporarily_lost"] += 1
                track.visible = False
        while len(self.tracks) > self.max_hands * 2:
            missing = [key for key in self.tracks if key not in visible]
            self._retire(min(missing, key=lambda key: (self.tracks[key].stamp, key)))
        return tuple(output)
