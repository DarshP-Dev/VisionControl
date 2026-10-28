"""Opt-in, bounded numeric capture/consumer timeline; no camera or GUI APIs.

Events belong to their endpoint bucket. Reads spanning a bucket/state transition
are deliberately not claimed to have occurred entirely within that population.
Percentiles/JSON construction run on detached data, never on the producer lock.
"""

from collections import Counter, deque
import copy
import math
import threading
import time

from hand_tracking.diagnostics import STATES
from hand_tracking.performance import Profile


COUNTS = frozenset(("capture_attempts", "successful_frames", "consumed_frames", "processed_frames",
    "overwritten_unconsumed_frames", "read_failures", "worker_exceptions", "invalid_frames",
    "consumer_wait_timeouts", "delivery_timeouts", "startup_timeouts", "stale_frames_rejected",
    "stale_results_rejected", "shutdown_timeouts", "release_failures",
    "duplicate_packets_suppressed", "consumer_waits", "millisecond_timestamp_collisions_suppressed"))
STAGES = frozenset(("camera_read", "snapshot_copy", "publication_interval", "consumer_wait",
    "handoff_age", "post_publication_to_next_read", "publication_lock_wait", "copy_to_publication",
    "frame_interval", "inference", "frame_age_at_controller_update", "gui_events",
    "preview_rendering", "cursor_update_interval", "host_frame_age_at_dispatch",
    "read_thread_cpu", "producer_thread_cpu", "main_thread_cpu"))


class CaptureTimeline:
    def __init__(self, enabled=False, *, bucket_seconds=2., capacity=300, sample_capacity=256,
                 clock=time.perf_counter, cpu_clock=time.process_time, producer_mode="latest-thread"):
        if not math.isfinite(bucket_seconds) or bucket_seconds <= 0 or capacity <= 0 or sample_capacity <= 0:
            raise ValueError("Timeline bounds must be positive and finite")
        self.enabled, self.width, self.capacity = enabled, bucket_seconds, capacity
        self.sample_capacity, self.clock, self.cpu_clock = sample_capacity, clock, cpu_clock
        if producer_mode not in ("sync", "latest-thread"):
            raise ValueError("Unknown capture mode")
        self.producer_mode = producer_mode
        self.lock = threading.Lock()
        self.buckets = deque(maxlen=capacity)
        self.active = self.ended = False
        self.origin = self.last = self.end = None
        self.state = "visible_unknown"
        self.hands = None
        self.total_buckets = 0
        self.read_started = None
        self.last_frame = self.last_cursor = self.last_main_cpu = None

    def begin(self):
        if not self.enabled:
            return
        with self.lock:
            self.origin = self.last = self.clock()
            self.end = None
            self.last_process_cpu = self.cpu_clock()
            self.buckets.clear()
            self.total_buckets = 0
            self.active, self.ended = True, False
            self.last_frame = self.last_cursor = self.last_main_cpu = None
            self._new(0, self.origin)

    def _new(self, index, start):
        self.total_buckets += 1
        self.buckets.append({"index": index, "start_monotonic": start, "end_monotonic": start,
            "counts": Counter(), "preview_state_seconds": Counter(), "hand_count_frames": Counter(),
            "profile": Profile(capacity=self.sample_capacity), "process_cpu_seconds": 0.,
            "last_observed_hand_count": self.hands,
            "read_in_progress_at_end": self.read_started is not None})

    def _advance(self):
        # Timestamp inside the lock: concurrent event calls cannot reorder buckets.
        now = max(self.last, self.clock())
        cpu = self.cpu_clock()
        cpu_delta = max(0., cpu-self.last_process_cpu)
        wall_delta = now-self.last
        cpu_rate = cpu_delta/wall_delta if wall_delta else 0.
        self.last_process_cpu = cpu
        while now >= self.origin + (self.buckets[-1]["index"] + 1) * self.width:
            b = self.buckets[-1]
            boundary = self.origin + (b["index"] + 1) * self.width
            b["preview_state_seconds"][self.state] += boundary-self.last
            b["process_cpu_seconds"] += cpu_rate*(boundary-self.last)
            b["end_monotonic"] = boundary
            b["read_in_progress_at_end"] = self.read_started is not None
            self.last = boundary
            self._new(b["index"] + 1, boundary)
            # A machine suspend / debugger pause must not create unbounded work.
            target = int((now-self.origin)//self.width)
            skip = max(0, target-self.buckets[-1]["index"]-self.capacity)
            if skip:
                self.total_buckets += skip-1  # _new below accounts for the final skipped index.
                self.last = self.origin+(self.buckets[-1]["index"]+skip)*self.width
                self.buckets.clear()
                self._new(target-self.capacity, self.last)
        b = self.buckets[-1]
        b["preview_state_seconds"][self.state] += now-self.last
        b["process_cpu_seconds"] += cpu_rate*(now-self.last) if wall_delta else cpu_delta
        b["end_monotonic"] = now
        b["last_observed_hand_count"] = self.hands
        b["read_in_progress_at_end"] = self.read_started is not None
        self.last = now
        return b

    def record(self, *, counts=None, timings=None, state=None, hands=None, processed=False,
               read_started=None, read_finished=False, main_cpu=None, cursor_at=None):
        if not self.enabled:
            return
        if state is not None and state not in STATES:
            raise ValueError("Unknown preview state")
        if hands is not None and (type(hands) is not int or hands not in range(5)):
            raise ValueError("Hand count must be 0–4")
        if (counts and not counts.keys() <= COUNTS) or (timings and not timings.keys() <= STAGES):
            raise ValueError("Unknown bounded timeline metric")
        if timings and any(not math.isfinite(v) or v < 0 for v in timings.values()):
            raise ValueError("Timings must be finite and nonnegative")
        with self.lock:
            if self.ended:
                return
            if not self.active:
                if state is not None:
                    self.state = state
                if hands is not None:
                    self.hands = hands
                if read_started is not None:
                    self.read_started = read_started
                if read_finished:
                    self.read_started = None
                return
            b = self._advance()
            if state is not None:
                self.state = state
            if hands is not None:
                self.hands = hands
            if counts:
                b["counts"].update(counts)
            if timings:
                for name, value in timings.items():
                    b["profile"].add(name, value)
            if read_started is not None:
                self.read_started = read_started
            if read_finished:
                self.read_started = None
            if processed:
                b["counts"]["processed_frames"] += 1
                if self.hands is not None:
                    b["hand_count_frames"][str(self.hands)] += 1
                if self.last_frame is not None:
                    b["profile"].add("frame_interval", max(0., self.last-self.last_frame))
                self.last_frame = self.last
            if cursor_at is not None:
                if self.last_cursor is not None:
                    b["profile"].add("cursor_update_interval", max(0., cursor_at-self.last_cursor))
                self.last_cursor = cursor_at
            if main_cpu is not None:
                if self.last_main_cpu is not None:
                    b["profile"].add("main_thread_cpu", max(0., main_cpu-self.last_main_cpu))
                self.last_main_cpu = main_cpu
            b["last_observed_hand_count"] = self.hands
            b["read_in_progress_at_end"] = self.read_started is not None

    def finish(self):
        if not self.enabled or not self.active:
            return
        with self.lock:
            if not self.ended:
                self._advance()
                self.end, self.ended = self.last, True

    def summary(self):
        if not self.enabled:
            return {"enabled": False, "buckets": []}
        with self.lock:
            # Completed buckets are immutable; detach only the current bounded bucket.
            buckets = list(self.buckets)
            if buckets:
                buckets[-1] = copy.deepcopy(buckets[-1])
            origin, end = self.origin, self.end
            total = self.total_buckets
            read_started = self.read_started
        output = []
        for b in buckets:
            elapsed = max(0., b["end_monotonic"]-b["start_monotonic"])
            counts = {name: b["counts"][name] for name in sorted(COUNTS)}
            states = dict(b["preview_state_seconds"])
            present = [state for state, seconds in states.items() if seconds > 0]
            cpu = b["process_cpu_seconds"]
            output.append({"index": b["index"], "start_monotonic": b["start_monotonic"],
                "end_monotonic": b["end_monotonic"], "elapsed_seconds": elapsed,
                "offset_seconds": b["start_monotonic"]-origin,
                "preview_state": present[0] if len(present) == 1 else "mixed" if present else None,
                "preview_state_seconds": states, "counts": counts,
                "capture_worker_delivery_fps": (counts["successful_frames"]/elapsed
                                                if elapsed and self.producer_mode == "latest-thread" else None),
                "host_read_or_publication_fps": counts["successful_frames"]/elapsed if elapsed else None,
                "consumed_frames_per_second": counts["consumed_frames"]/elapsed if elapsed else None,
                "processed_application_fps": counts["processed_frames"]/elapsed if elapsed else None,
                "hand_count_frames": dict(b["hand_count_frames"]),
                "last_observed_hand_count": b["last_observed_hand_count"],
                "read_in_progress_at_end": b["read_in_progress_at_end"],
                "process_cpu_seconds_estimated": cpu,
                "process_cpu_percent_of_one_core_estimated": 100*cpu/elapsed if elapsed else None,
                "capture_thread_cpu_percent_of_one_core_estimated": (
                    100*b["profile"].stages["producer_thread_cpu"]["total"]/elapsed
                    if elapsed and "producer_thread_cpu" in b["profile"].stages else None),
                "main_thread_cpu_percent_of_one_core_estimated": (
                    100*b["profile"].stages["main_thread_cpu"]["total"]/elapsed
                    if elapsed and "main_thread_cpu" in b["profile"].stages else None),
                "timings": b["profile"].summary()})
        return {"enabled": True, "producer_mode": self.producer_mode,
            "bucket_seconds": self.width, "bucket_capacity": self.capacity,
            "percentile_capacity_per_bucket_series": self.sample_capacity,
            "buckets_discarded": max(0, total-len(output)), "start_monotonic": origin,
            "end_monotonic": end, "read_started_monotonic": read_started, "buckets": output,
            "semantics": "Endpoint attribution; read wall time includes native execution, GIL reacquisition and OS scheduling. "
                "State is last main-thread observation; intervals can span states. Process CPU deltas spanning bucket boundaries "
                "are allocated in proportion to elapsed wall time (estimates, not scheduler traces); "
                "thread CPU excludes native helper threads. No sensor exposure or foreign-application data."}
