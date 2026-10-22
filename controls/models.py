"""Small immutable configuration and backend contract; no Windows imports."""

from dataclasses import dataclass
import math
from typing import Callable, Protocol

from gestures.models import HandSide
from .region import ActiveRegion
from .hotkeys import DEFAULT_EMERGENCY_HOTKEY, display_hotkey, normalize_hotkey
from .profiles import PROFILES


@dataclass(frozen=True, slots=True)
class Screen:
    left: int = 0
    top: int = 0
    width: int = 1920
    height: int = 1080

    def __post_init__(self):
        if any(isinstance(v, bool) or not isinstance(v, int)
               for v in (self.left, self.top, self.width, self.height)) or min(self.width, self.height) < 2:
            raise ValueError("Screen requires integer physical-pixel bounds of at least 2 x 2")

    def clamp(self, x, y):
        if not all(math.isfinite(v) for v in (x, y)):
            raise ValueError("Cursor coordinates must be finite")
        return (round(max(self.left, min(self.left+self.width-1, x))),
                round(max(self.top, min(self.top+self.height-1, y))))


@dataclass(frozen=True, slots=True)
class ControlSettings:
    mode: str = "simulate"
    hand: HandSide = HandSide.RIGHT
    mouse: bool = False  # Click/drag; cursor movement is available when armed.
    tabs: bool = False
    sensitivity: float = 1.5
    alpha: float = .6
    margin: float = .10
    monitor: int = 0
    debug: bool = False
    browsers: tuple[str, ...] = ("chrome.exe", "msedge.exe", "firefox.exe")
    invert_x: bool | None = None  # None selects the mapping-specific default.
    mapping: str = "relative"
    region_width: float = .80
    region_height: float = .80
    emergency_hotkey: str = DEFAULT_EMERGENCY_HOTKEY
    gesture_rearm: bool = False
    rearm_hold_ms: int = 800
    rearm_stable_ms: int = 300
    rearm_debug: bool = False
    gesture_profile: str = "legacy"
    cursor_resume: str = "automatic"

    def __post_init__(self):
        if self.gesture_profile not in PROFILES or self.cursor_resume not in ("automatic", "left-pinch"):
            raise ValueError("Invalid control gesture profile or cursor resume mode")
        if self.gesture_profile == "palm-cursor" and self.hand != HandSide.RIGHT:
            raise ValueError("Palm cursor requires --control-hand right")
        if self.cursor_resume == "left-pinch" and (self.gesture_profile != "palm-cursor" or not self.gesture_rearm):
            raise ValueError("Left-pinch cursor resume requires palm-cursor and --control-gesture-rearm")
        object.__setattr__(self, "emergency_hotkey", normalize_hotkey(self.emergency_hotkey))
        if not isinstance(self.gesture_rearm, bool) or not isinstance(self.rearm_debug, bool):
            raise ValueError("Gesture rearm/debug settings must be booleans")
        if self.gesture_rearm and self.hand != HandSide.RIGHT:
            raise ValueError("--control-gesture-rearm requires --control-hand right; Left is reserved for rearming")
        for name, lo, hi in (("rearm_hold_ms", 500, 3000), ("rearm_stable_ms", 150, 2000)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ValueError(f"Control {name} must be an integer in [{lo}, {hi}] milliseconds")
        if self.mode not in ("simulate", "live") or self.hand not in (HandSide.LEFT, HandSide.RIGHT):
            raise ValueError("Controls require simulate/live mode and left/right hand")
        if self.mapping not in ("relative", "absolute"):
            raise ValueError("Control mapping must be relative or absolute")
        if self.invert_x is None:
            object.__setattr__(self, "invert_x", self.mapping == "absolute")
        elif not isinstance(self.invert_x, bool):
            raise ValueError("Control invert_x must be a boolean or None (mapping default)")
        ActiveRegion(self.region_width, self.region_height)
        for name, lo, hi in (("sensitivity", .1, 5.), ("alpha", .01, 1.), ("margin", 0., .4)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"Control {name} must be finite in [{lo}, {hi}]")
        if isinstance(self.monitor, bool) or not isinstance(self.monitor, int) or self.monitor < 0:
            raise ValueError("Control monitor must be a nonnegative integer")
        if not self.browsers or any(not isinstance(s, str) or not s.endswith(".exe")
                                    or any(c in s for c in "/\\ :") for s in self.browsers):
            raise ValueError("Browser allowlist must contain executable basenames ending in .exe")


class InputBackend(Protocol):
    screen: Screen
    is_live: bool
    input_allowed: Callable[[], bool]  # Controller-installed guard for normal input; never blocks cleanup UP.

    def cursor_position(self) -> tuple[int, int]: ...
    def move(self, x: int, y: int) -> None: ...
    def left_down(self) -> None: ...
    def left_up(self) -> None: ...
    def switch_tab(self, previous: bool, allowed: tuple[str, ...]) -> bool: ...
    def close(self) -> None:
        """Idempotently release owned inputs; remains reusable after disarm."""
        ...


@dataclass(frozen=True, slots=True)
class ControlStatus:
    mode: str
    armed: bool
    hand: str
    gesture: str
    button_down: bool
    last_action: str
    reason: str
    mapping: str = "relative"
    region: ActiveRegion | None = None
    emergency_hotkey: str = DEFAULT_EMERGENCY_HOTKEY
    rearm_status: str = ""
    profile: str = "legacy"
    cursor_state: str = ""

    def lines(self):
        return (f"{self.mode.upper()} | {self.mapping.upper()} | {'ARMED' if self.armed else 'DISARMED'} | {self.hand} | "
                f"{self.gesture} | LEFT {'DOWN' if self.button_down else 'UP'} | A: Arm D: Disarm",
                f"Last: {self.last_action} | {self.reason}" + (" | PROFILE: LEGACY" if self.profile == "legacy" else "") +
                (f" | STOP: {display_hotkey(self.emergency_hotkey)}" if self.mode == "live" else "")) + \
               ((f"PROFILE: PALM CURSOR | CURSOR: {self.cursor_state}",) if self.profile == "palm-cursor"
                else ()) + ((self.rearm_status,) if self.rearm_status else ())
