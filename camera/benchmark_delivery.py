"""Camera delivery with optional diagnostic HighGUI. No model, image files or input.

Measures host BGR deliveries, not verified unique sensor frames or exposure age.
"""

import argparse
import platform
from pathlib import Path
import time

import cv2

from .camera_diagnostics import BACKENDS, capture_control_readbacks, capture_snapshot, configure_capture, read_frame
from .latest_capture import CaptureError, LatestCapture, ensure_camera_available
from .capture_timeline import CaptureTimeline
from .windows_timing import POLICIES, WindowsTimerPolicy
from hand_tracking.diagnostics import process_memory
from hand_tracking.gui import GuiEvents
from hand_tracking.preview_window import create_preview_window
from hand_tracking.tracking_utils import PreviewRenderer
from hand_tracking.performance import Profile, process_cpu_usage, write_report


def measure(args):
    cap = source = None
    preview_enabled = getattr(args, "preview", False)
    title = "VisionControl - Camera Delivery Diagnostic"
    window = gui = None
    renderer = PreviewRenderer() if preview_enabled else None
    timeline = CaptureTimeline(enabled=True, producer_mode=args.capture_pipeline)
    timer_policy = WindowsTimerPolicy(getattr(args, "windows_timer_policy", "system"))
    report = {"kind": "camera_highgui_host_delivery" if preview_enabled else "camera_only_host_delivery",
              "capture_pipeline_mode": args.capture_pipeline, "preview_enabled": preview_enabled,
              "python": platform.python_version(), "platform": platform.platform(), "opencv": cv2.__version__,
              "opencv_configured_threads": cv2.getNumThreads(),
              "requested_capture": {key: getattr(args, key) for key in
                                    ("camera_index", "backend", "width", "height", "fps", "fourcc")},
              "sensor_fps": None, "sensor_exposure_age_ms": None,
              "limitations": "No inference/controls; BGR read completions are not verified unique sensor frames."}
    def configure_owned(camera):
        if not camera.isOpened():
            raise CaptureError("Cannot open requested camera")
        accepted = configure_capture(camera, args)
        return {"driver_readback": capture_snapshot(camera, args, "Camera-only configuration"),
                "camera_control_readbacks": capture_control_readbacks(camera),
                "configuration_accepted": accepted}
    profile = Profile(enabled=False)
    first = start = cpu_start = last = None
    frames = 0
    skipped = 0
    def present(image, dimensions):
        nonlocal skipped
        if window is None:
            return
        if window.should_render(timeline.state):
            render = time.perf_counter()
            width, height = dimensions
            scale = min(1100/width, 650/height, 1.)
            cv2.imshow(title, renderer.resize(image, (max(1, round(width*scale)), max(1, round(height*scale)))))
            elapsed_render = time.perf_counter()-render
            profile.add("preview_rendering", elapsed_render)
            timeline.record(timings={"preview_rendering": elapsed_render})
        elif start is not None:
            skipped += 1

    def pump():
        if window is None:
            timeline.record(state="headless", main_cpu=time.thread_time())
            return False
        before = time.perf_counter()
        key = gui.read_key()
        state = window.state()
        timeline.record(state=state, timings={"gui_events": time.perf_counter()-before}, main_cpu=time.thread_time())
        if state == "closed" or key in (ord("q"), ord("Q")):
            report["status"] = "preview_closed" if state == "closed" else "stopped"
            return True
        return False
    try:
        timer_policy.start()
        if args.capture_pipeline == "latest-thread":
            source = LatestCapture(lambda: cv2.VideoCapture(args.camera_index, BACKENDS[args.backend]),
                                   configure_owned, device_key=(args.backend, args.camera_index),
                                   profile=True, measuring=False).start()
            timeline = source.timeline
        else:
            ensure_camera_available((args.backend, args.camera_index))
            cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
            report.update(configure_owned(cap))
        if preview_enabled:
            cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
            window = create_preview_window(title)
            gui = GuiEvents(getattr(args, "gui_mode", "auto"))
        while True:
            if pump():
                break
            before = time.perf_counter()
            if source is not None:
                packet = source.take(.01)
                source.check_deadline()
                if packet is None:
                    continue
                read_at, duration = packet.read_completed_at, packet.read_seconds
                dimensions = packet.dimensions
                image = packet.image
            else:
                timeline.record(counts={"capture_attempts": 1}, read_started=before)
                try:
                    image = read_frame(cap)
                except OSError:
                    timeline.record(counts={"read_failures": 1}, read_finished=True)
                    raise
                read_at = time.perf_counter()
                duration = read_at-before
                dimensions = (image.shape[1], image.shape[0])
                timeline.record(counts={"successful_frames": 1, "consumed_frames": 1},
                                timings={"camera_read": duration}, read_finished=True)
            now = time.perf_counter()
            if first is None:
                first = now
            if start is None:
                if now-first < args.warmup:
                    if pump():
                        break
                    present(image, dimensions)
                    continue
                start, cpu_start = now, time.process_time()
                profile.enabled = True
                if source is not None:
                    source.begin_measurement()
                else:
                    timeline.begin()
                print(f"Warm-up complete; starting {args.duration:g} s measurement.", flush=True)
                continue  # First fully measured delivery begins after this boundary.
            profile.add("camera_read", duration)
            profile.add("host_age_at_consumption", now-read_at)
            if last is not None:
                profile.add("consumer_delivery_interval", now-last)
            last = now
            frames += 1
            timeline.record(processed=True, hands=None)
            if pump():
                break
            present(image, dimensions)
            report["actual_dimensions"] = list(dimensions)
            if now-start >= args.duration:
                report["status"] = "completed"
                break
    except (OSError, RuntimeError, ValueError, cv2.error) as exc:
        report.update(status="error", error=str(exc))
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    finally:
        end, cpu_end = time.perf_counter(), time.process_time()
        timeline.finish()
        # Policy restoration must survive a second Ctrl+C or unexpected cleanup
        # exception as well as the ordinary reported native/GUI failures.
        try:
            try:
                if source is not None:
                    try:
                        source.close()
                    except CaptureError as exc:
                        report.update(status="error", shutdown_error=str(exc))
                    report["capture_pipeline"] = source.snapshot()
                    report.update(report["capture_pipeline"]["metadata"])
                elif cap is not None:
                    try:
                        cap.release()
                    except (OSError, RuntimeError, cv2.error) as exc:
                        report.update(status="error", shutdown_error=str(exc))
            finally:
                if preview_enabled:
                    try:
                        cv2.destroyAllWindows()
                    except cv2.error as exc:
                        report.update(status="error", preview_cleanup_error=str(exc))
        finally:
            try:
                timer_policy.close()
            except OSError as exc:
                report.update(status="error", timer_policy_cleanup_error=str(exc))
            report["windows_timer_policy"] = timer_policy.snapshot()
        elapsed = max(0., end-start) if start is not None else 0.
        report.update(frames=frames, measurement_seconds=elapsed,
                      warmup_seconds_requested=args.warmup, measurement_seconds_requested=args.duration,
                      capture_only_consumer_fps=frames/elapsed if elapsed else None,
                      timings=profile.summary(), memory=process_memory(),
                      capture_timeline=timeline.summary(), preview_renders_skipped=skipped,
                      gui=gui.metadata() if gui is not None else None,
                      resources=process_cpu_usage(cpu_end-cpu_start if cpu_start is not None else 0., elapsed, frames))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-pipeline", choices=("sync", "latest-thread"), default="sync")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="msmf")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.)
    parser.add_argument("--fourcc", choices=("MJPG", "YUY2"), default="MJPG")
    parser.add_argument("--warmup", type=float, default=3.)
    parser.add_argument("--duration", type=float, default=30.)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--preview", action="store_true", help="diagnostic HighGUI preview without MediaPipe or input; Q/X stops")
    parser.add_argument("--gui-mode", choices=("auto", "waitkey", "pollkey"), default="auto")
    parser.add_argument("--windows-timer-policy", choices=POLICIES, default="system",
                        help="system (default) or reversible Windows 11 honor-requests correction; no new timer period")
    args = parser.parse_args(argv)
    import math
    if (args.camera_index < 0 or min(args.width, args.height) <= 0 or args.warmup < 0
            or not all(math.isfinite(v) for v in (args.warmup, args.duration, args.fps))
            or min(args.duration, args.fps) <= 0 or args.report.exists()):
        parser.error("Use valid camera dimensions/rates, nonnegative warmup, positive duration and a fresh report path")
    report = measure(args)
    write_report(args.report, report)
    print(f"{report['status']}: {report['capture_only_consumer_fps']} host BGR deliveries/s; report: {args.report}")
    if report.get("error"):
        print(report["error"])
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
