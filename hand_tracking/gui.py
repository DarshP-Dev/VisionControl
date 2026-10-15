"""One HighGUI event-pump call per processed frame, without a polling spin loop."""

import logging

import cv2


LOGGER = logging.getLogger("hand_tracking")


class GuiEvents:
    def __init__(self, mode="auto"):
        if mode not in ("auto", "waitkey", "pollkey"):
            raise ValueError("GUI mode must be auto, waitkey or pollkey")
        self.requested = mode
        self.fallback_reason = None
        framework = getattr(cv2, "currentUIFramework", None)
        try:
            self.backend = (framework() if callable(framework) else "") or "unknown"
        except cv2.error:
            self.backend = "unknown"
        native_poll = self.backend.upper() == "WIN32" and callable(getattr(cv2, "pollKey", None))
        self.mode = "pollkey" if mode != "waitkey" and native_poll else "waitkey"
        self.api = "pollKey" if self.mode == "pollkey" else "waitKey"
        if mode == "pollkey" and not native_poll:
            self.fallback_reason = "Native Win32 pollKey is not available"
            LOGGER.warning("%s; using waitKey(1).", self.fallback_reason)

    def read_key(self):
        if self.mode == "pollkey":
            try:
                self.api = "pollKey"
                return cv2.pollKey() & 0xFF
            except cv2.error as exc:
                self.mode = "waitkey"
                self.fallback_reason = str(exc)
                LOGGER.warning("pollKey failed; falling back to waitKey(1): %s", exc)
        self.api = "waitKey"
        return cv2.waitKey(1) & 0xFF

    def metadata(self):
        return {"requested": self.requested, "effective": self.mode,
                "backend": self.backend, "fallback_reason": self.fallback_reason}
