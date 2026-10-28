"""Deterministic ownership/handoff tests; no webcam, HighGUI or Windows input."""

import queue
import threading
import time
import unittest

import numpy as np

from camera.latest_capture import CaptureError, CaptureShutdownError, CaptureTimestamp, LatestCapture, ensure_camera_available


class ScriptedCamera:
    def __init__(self):
        self.queue = queue.Queue(maxsize=16)
        self.unblock = threading.Event()
        self.read_entered = threading.Event()
        self.calls = []
        self.release_count = 0

    def read(self):
        self.calls.append(("read", threading.get_ident()))
        self.read_entered.set()
        while not self.unblock.is_set():
            try:
                item = self.queue.get(timeout=.01)
            except queue.Empty:
                continue
            if isinstance(item, BaseException):
                raise item
            return item
        return False, None

    def send(self, number=1):
        self.queue.put((True, np.full((12, 20, 3), number, np.uint8)), timeout=1)

    def release(self):
        self.calls.append(("release", threading.get_ident()))
        self.release_count += 1


class LatestCaptureTest(unittest.TestCase):
    def test_timeline_producer_counts_and_state_transitions_without_gui_on_owner(self):
        source, camera, owner = self.source()
        for n, state in enumerate(("focused", "unfocused", "minimized", "focused"), 1):
            source.timeline.record(state=state)
            camera.send(n)
            self.assertIsNotNone(source.take(1))
            source.timeline.record(processed=True, hands=2)
        source.request_stop()
        camera.unblock.set()
        source.close(1)
        d = source.snapshot()
        buckets = d["timeline"]["buckets"]
        for name in ("successful_frames", "consumed_frames"):
            self.assertEqual(sum(b["counts"][name] for b in buckets), d["measurement_counts"][name])
        timings = buckets[0]["timings"]
        self.assertEqual(timings["camera_read"]["count"], 4)
        self.assertIn("post_publication_to_next_read", timings)
        self.assertIn("publication_lock_wait", timings)
        self.assertIn("read_thread_cpu", timings)
        self.assertIn("producer_thread_cpu", timings)
        self.assertIn("handoff_age", timings)
        self.assertTrue(all(tid == owner[0] for _, tid in camera.calls))
        self.assertFalse(d["worker_alive"])

    def test_timeline_accepts_minimize_restore_updates_during_blocked_native_read(self):
        source, camera, _ = self.source(startup_timeout=.03)
        for state in ("focused", "unfocused", "minimized", "focused"):
            source.timeline.record(state=state)
        self.assertFalse(source.input_allowed())
        time.sleep(.04)
        with self.assertRaisesRegex(CaptureError, "first-frame timeout"):
            source.check_deadline()
        b = source.timeline.summary()["buckets"][0]
        self.assertEqual(b["counts"]["successful_frames"], 0)
        self.assertEqual(b["counts"]["startup_timeouts"], 1)
        self.assertTrue(b["read_in_progress_at_end"])

    def test_disabled_timeline_never_receives_producer_or_consumer_events(self):
        from unittest.mock import patch
        source, camera, _ = self.source(profile=False)
        with patch.object(source.timeline, "record", side_effect=AssertionError("disabled instrumentation")):
            camera.send()
            self.assertIsNotNone(source.take(1))
            source.request_stop()
            camera.unblock.set()
            source.close(1)
        self.assertEqual(source.snapshot()["timeline"], {"enabled": False, "buckets": []})

    def source(self, *, configure=None, device_key=None, profile=True, **kwargs):
        camera = ScriptedCamera()
        owner = []
        def factory():
            owner.append(threading.get_ident())
            return camera
        source = LatestCapture(factory, configure, device_key=device_key, profile=profile, **kwargs).start()
        def cleanup():
            source.request_stop()
            camera.unblock.set()
            source.close(1)
            self.assertFalse(source.thread.is_alive())
        self.addCleanup(cleanup)
        self.assertTrue(camera.read_entered.wait(1))
        return source, camera, owner

    def publication(self, source, count):
        with source.condition:
            self.assertTrue(source.condition.wait_for(lambda: source.counts["successful_frames"] >= count
                                                      or source.failed.is_set(), timeout=1))
        source.raise_if_failed()

    def test_factory_config_read_release_stay_on_one_non_main_thread(self):
        configured = []
        source, camera, owner = self.source(configure=lambda cap: configured.append(threading.get_ident()) or {"test": True})
        camera.send()
        packet = source.take(1)
        self.assertIsNotNone(packet)
        self.assertNotEqual(owner[0], threading.get_ident())
        source.request_stop()
        camera.unblock.set()
        source.close(1)
        self.assertTrue(all(tid == owner[0] for _, tid in camera.calls))
        self.assertEqual(configured, owner)
        self.assertEqual(camera.release_count, 1)
        source.close(1)
        self.assertEqual(camera.release_count, 1)

    def test_frame_metadata_and_no_replay_when_consumer_is_faster(self):
        source, camera, _ = self.source()
        camera.send(7)
        packet = source.take(1)
        self.assertEqual((packet.session, packet.sequence, packet.dimensions), (source.session, 1, (20, 12)))
        self.assertGreaterEqual(packet.published_at, packet.read_completed_at)
        self.assertGreaterEqual(packet.read_seconds, 0)
        self.assertIsNone(source.take(.005))
        camera.send(8)
        second = source.take(1)
        self.assertEqual(second.sequence, 2)
        self.assertGreater(second.read_completed_at, packet.read_completed_at)

    def test_producer_faster_than_consumer_keeps_only_latest(self):
        source, camera, _ = self.source()
        for index in range(8):
            camera.send(index)
            self.publication(source, index+1)
        packet = source.take(0)
        self.assertEqual(packet.sequence, 8)
        self.assertEqual(packet.image[0, 0, 0], 7)
        report = source.snapshot()
        self.assertEqual(report["buffer_capacity"], 1)
        self.assertEqual(report["max_buffer_occupancy"], 1)
        self.assertEqual(report["lifetime_counts"]["overwritten_unconsumed_frames"], 7)
        self.assertEqual(report["buffer_occupancy"], 0)

    def test_backend_reusing_mutable_storage_cannot_corrupt_consumed_snapshot(self):
        source, camera, _ = self.source()
        raw = np.full((12, 20, 3), 4, np.uint8)
        camera.queue.put((True, raw))
        first = source.take(1)
        raw[:] = 99
        camera.queue.put((True, raw))
        second = source.take(1)
        self.assertTrue(np.all(first.image == 4))
        self.assertTrue(np.all(second.image == 99))
        self.assertFalse(np.shares_memory(first.image, second.image))
        with self.assertRaises(ValueError):
            first.image[:] = 2

    def test_read_failure_clears_pending_frame_and_latches_fault(self):
        source, camera, _ = self.source()
        camera.send()
        self.publication(source, 1)
        camera.queue.put((False, None))
        self.assertTrue(source.failed.wait(1))
        self.assertFalse(source.input_allowed())
        with self.assertRaises(CaptureError):
            source.take(0)
        self.assertEqual(source.snapshot()["buffer_occupancy"], 0)
        self.assertEqual(source.counts["read_failures"], 1)

    def test_worker_exception_is_reported_and_releases_camera(self):
        source, camera, _ = self.source()
        camera.queue.put(RuntimeError("injected camera error"))
        self.assertTrue(source.finished.wait(1))
        with self.assertRaisesRegex(CaptureError, "injected camera error"):
            source.take(0)
        self.assertEqual(source.counts["worker_exceptions"], 1)
        self.assertEqual(camera.release_count, 1)

    def test_invalid_decoded_frame_fails_closed_and_counts_validation_failure(self):
        source, camera, _ = self.source()
        camera.queue.put((True, np.zeros((12, 20, 4), np.uint8)))
        self.assertTrue(source.finished.wait(1))
        self.assertFalse(source.input_allowed())
        self.assertEqual(source.counts["invalid_frames"], 1)
        self.assertEqual(camera.release_count, 1)
        with self.assertRaisesRegex(CaptureError, "decoded uint8 BGR"):
            source.take(0)

    def test_initialization_failure_releases_on_owner_and_never_publishes(self):
        camera = ScriptedCamera()
        def bad(cap):
            raise OSError("camera unavailable")
        source = LatestCapture(lambda: camera, bad).start()
        self.assertTrue(source.finished.wait(1))
        source.close(1)
        with self.assertRaisesRegex(CaptureError, "camera unavailable"):
            source.take(0)
        self.assertEqual(camera.release_count, 1)
        self.assertEqual(source.counts["successful_frames"], 0)

    def test_open_exception_and_release_exception_are_explicit(self):
        def fail():
            raise RuntimeError("open broke")
        source = LatestCapture(fail).start()
        self.assertTrue(source.finished.wait(1))
        source.close(1)
        self.assertTrue(source.failed.is_set())
        camera = ScriptedCamera()
        def release():
            raise OSError("release broke")
        camera.release = release
        source = LatestCapture(lambda: camera).start()
        self.assertTrue(camera.read_entered.wait(1))
        source.request_stop()
        camera.unblock.set()
        with self.assertRaisesRegex(CaptureShutdownError, "release broke"):
            source.close(1)
        self.assertFalse(source.thread.is_alive())

    def test_first_frame_timeout_is_bounded_and_owner_releases_when_read_returns(self):
        clock = [0.]
        source, camera, _ = self.source(clock=lambda: clock[0], startup_timeout=.05)
        clock[0] = .06
        with self.assertRaisesRegex(CaptureError, "first-frame timeout"):
            source.check_deadline()
        self.assertFalse(source.input_allowed())
        camera.unblock.set()
        self.assertTrue(source.finished.wait(1))
        self.assertEqual(camera.release_count, 1)

    def test_stall_timeout_fences_even_previously_fresh_frame(self):
        clock = [0.]
        source, camera, _ = self.source(clock=lambda: clock[0])
        clock[0] = .01
        camera.send()
        source.take(1)
        self.assertTrue(source.input_allowed())
        clock[0] = .261
        self.assertFalse(source.input_allowed())
        with self.assertRaisesRegex(CaptureError, "stopped delivering"):
            source.check_deadline()

    def test_stuck_read_bounded_join_never_calls_release_concurrently_or_reopens_device(self):
        key = ("fake-msmf", id(self))
        source, camera, _ = self.source(device_key=key)
        start = time.perf_counter()
        with self.assertRaises(CaptureShutdownError):
            source.close(.01)
        self.assertLess(time.perf_counter()-start, .5)
        self.assertEqual(camera.release_count, 0)
        self.assertFalse(source.input_allowed())
        with self.assertRaises(CaptureError):
            ensure_camera_available(key)  # Sync fallback is also fenced while native ownership remains.
        opened = []
        other = LatestCapture(lambda: opened.append(True) or ScriptedCamera(), device_key=key).start()
        self.assertTrue(other.finished.wait(1))
        self.assertTrue(other.failed.is_set())
        self.assertEqual(opened, [])
        other.close(1)
        camera.unblock.set()  # Every simulated native hang is explicitly unblocked.
        source.close(1)
        self.assertEqual(camera.release_count, 1)
        ensure_camera_available(key)

    def test_consumer_wait_unblocks_on_stop_and_worker_cannot_restart(self):
        source, camera, _ = self.source()
        result = []
        waiting = threading.Thread(target=lambda: result.append(source.take(1)))
        waiting.start()
        source.request_stop()
        waiting.join(1)
        self.assertFalse(waiting.is_alive())
        self.assertEqual(result, [None])
        with self.assertRaises(CaptureError):
            source.start()

    def test_profile_warmup_is_reset_and_disabled_profiles_store_no_samples(self):
        source, camera, _ = self.source(measuring=False)
        camera.send()
        source.take(1)
        self.assertEqual(source.snapshot()["timings"], {})
        source.begin_measurement()
        camera.send()
        source.take(1)
        report = source.snapshot()
        self.assertEqual(report["measurement_counts"]["successful_frames"], 1)
        self.assertEqual(report["lifetime_counts"]["successful_frames"], 2)
        self.assertEqual(report["timings"]["camera_read"]["count"], 1)

    def test_repeated_sessions_get_distinct_generation_and_no_orphan_worker(self):
        sessions = []
        for _ in range(3):
            source, camera, _ = self.source()
            camera.send()
            sessions.append(source.take(1).session)
            source.request_stop()
            camera.unblock.set()
            source.close(1)
        self.assertEqual(len(set(sessions)), 3)

    def test_capture_milliseconds_drop_collisions_without_future_timestamp_invention(self):
        clock = CaptureTimestamp(10.)
        self.assertEqual(clock.next(10.0001), 0)
        self.assertIsNone(clock.next(10.0002))
        self.assertEqual(clock.next(10.0105), 10)
        self.assertIsNone(clock.next(10.009))
        self.assertEqual(clock.next(10.3005), 300)
        with self.assertRaises(CaptureError):
            clock.next(float("nan"))

    def test_duplicate_sequence_and_wrong_session_are_not_delivered_again(self):
        from dataclasses import replace
        source, camera, _ = self.source()
        camera.send()
        first = source.take(1)
        for invalid in (first, replace(first, sequence=2, session="other")):
            with source.condition:
                source._slot = invalid
            self.assertIsNone(source.take(0))
        self.assertEqual(source.counts["duplicate_packets_suppressed"], 2)

    def test_capture_clock_regression_fails_and_releases_without_old_publication(self):
        clock = [0.]
        source, camera, _ = self.source(clock=lambda: clock[0])
        clock[0] = .02
        camera.send()
        source.take(1)
        clock[0] = .01
        camera.send()
        self.assertTrue(source.finished.wait(1))
        self.assertTrue(source.failed.is_set())
        self.assertFalse(source.input_allowed())
        self.assertEqual(source.counts["successful_frames"], 1)
        self.assertEqual(camera.release_count, 1)

    def test_disabled_profiles_keep_health_counters_but_no_sample_storage(self):
        source, camera, _ = self.source(profile=False)
        camera.send()
        source.take(1)
        self.assertEqual(source.snapshot()["timings"], {})
        self.assertEqual(source.counts["successful_frames"], 1)

    def test_stop_during_blocked_factory_releases_late_open_on_owner(self):
        entered, proceed = threading.Event(), threading.Event()
        camera = ScriptedCamera()
        owners = []
        def factory():
            owners.append(threading.get_ident())
            entered.set()
            proceed.wait(1)
            return camera
        source = LatestCapture(factory).start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(CaptureShutdownError):
                source.close(.01)
            self.assertEqual(camera.release_count, 0)
        finally:
            proceed.set()
            source.close(1)
        self.assertFalse(source.thread.is_alive())
        self.assertEqual(camera.calls, [("release", owners[0])])


if __name__ == "__main__":
    unittest.main()
