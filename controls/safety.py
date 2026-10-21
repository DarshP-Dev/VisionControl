"""One live-only emergency/watchdog thread; capture and inference stay synchronous."""

import logging
import threading

from .hotkeys import display_hotkey


LOGGER = logging.getLogger("controls")


class GlobalSafety:
    def __init__(self, controller, api):
        self.controller, self.api = controller, api
        self.hotkey = controller.settings.emergency_hotkey
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.thread = None

    def start(self):
        if self.thread is not None or self.stop.is_set():
            raise RuntimeError("Emergency monitor is single-use; create a new monitor after shutdown")
        self.thread = threading.Thread(target=self._run, name="VisionControl emergency stop", daemon=True)
        self.thread.start()
        if not self.ready.wait(2) or self.error is not None:
            self.close()
            raise OSError(f"Global emergency stop {display_hotkey(self.hotkey)} unavailable: "
                          f"{self.error or 'initialization timed out'}") from self.error
        return self

    def _run(self):
        registered = False
        try:
            self.api.register_stop(self.hotkey)
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
            self.error = exc
            self.controller.safety_failure("Emergency monitor failed; restart required")
            LOGGER.exception("Emergency monitoring failed closed")
        finally:
            try:
                self.controller.safety_failure("Emergency monitor stopped")
            finally:
                try:
                    if registered:
                        self.api.unregister_stop()
                except Exception:
                    LOGGER.exception("Emergency shortcut cleanup failed")
                finally:
                    self.ready.set()

    def close(self):
        self.stop.set()
        try:
            self.controller.safety_failure("Safety shutdown")
        finally:
            if self.thread is not None:
                self.thread.join(timeout=2)
