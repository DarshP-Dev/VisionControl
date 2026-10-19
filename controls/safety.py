"""One live-only emergency/watchdog thread; capture and inference stay synchronous."""

import logging
import threading


LOGGER = logging.getLogger("controls")


class GlobalSafety:
    def __init__(self, controller, api):
        self.controller, self.api = controller, api
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="VisionControl emergency stop", daemon=True)
        self.thread.start()
        if not self.ready.wait(2) or self.error is not None:
            self.close()
            raise OSError(f"Global emergency stop unavailable: {self.error or 'initialization timed out'}")
        return self

    def _run(self):
        registered = False
        try:
            self.api.register_stop()
            registered = True
            with self.controller.lock:
                if not self.stop.is_set():
                    self.controller.safety_ready = True
            self.ready.set()
            while not self.stop.wait(.01):
                if self.api.stop_requested():
                    self.controller.disarm("GLOBAL EMERGENCY STOP; rearm manually")
                self.controller.check_timeout()
        except Exception as exc:
            self.error = str(exc)
            self.controller.safety_failure("Emergency monitor failed; restart required")
            LOGGER.exception("Emergency monitoring failed closed")
        finally:
            self.controller.safety_failure("Emergency monitor stopped")
            self.ready.set()
            if registered:
                try:
                    self.api.unregister_stop()
                except Exception:
                    LOGGER.exception("Emergency shortcut cleanup failed")

    def close(self):
        self.controller.safety_failure("Safety shutdown")
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
