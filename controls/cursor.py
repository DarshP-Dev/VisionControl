"""Independent relative and absolute index-tip strategies with screen-space EMA."""

import math

from .models import ControlSettings, Screen
from .region import ActiveRegion


class RelativeCursor:
    def __init__(self, settings: ControlSettings, screen: Screen):
        self.settings, self.screen = settings, screen
        self.reset()

    def reset(self):
        self.previous = self.target = self.filtered = self.size = None

    def update(self, point, size, current):
        if size is None or not all(math.isfinite(v) for v in point) or not all(0 <= v <= 1 for v in point):
            raise ValueError("Cursor requires finite in-frame landmarks and camera dimensions")
        aspect = size.height / size.width
        margin = self.settings.margin
        # Clamp the tip to an active camera region. Both axes use image-width units.
        common = (max(margin, min(1-margin, point[0])),
                  max(margin, min(1-margin, point[1]))*aspect)
        if self.previous is None or self.size != size:
            if self.screen.clamp(*current) != tuple(current):
                raise ValueError("Place the cursor on the selected monitor before activation")
            self.previous, self.size = common, size
            self.target = self.filtered = self.screen.clamp(*current)
            return None  # Acquisition anchors to the existing cursor; never teleports.
        gain = self.settings.sensitivity * min((self.screen.width-1)/(1-2*margin),
                                               (self.screen.height-1)/(aspect*(1-2*margin)))
        dx, dy = common[0]-self.previous[0], common[1]-self.previous[1]
        if self.settings.invert_x:
            dx = -dx  # Invert displacement, never the anchor or recognition coordinates.
        self.target = self.screen.clamp(self.target[0]+dx*gain, self.target[1]+dy*gain)
        self.previous = common
        alpha = self.settings.alpha
        self.filtered = tuple(alpha*self.target[i]+(1-alpha)*self.filtered[i] for i in (0, 1))
        return self.screen.clamp(*self.filtered)


class AbsoluteCursor:
    """Map normalized camera position to physical pixels; no accumulated displacement.

    First acquisition confirms a fresh sample without moving. The next sample
    applies the existing screen EMA from the current cursor. Pinch anchors use
    a constant screen offset, cleared on release/reset. Reacquisition blends
    back to absolute positioning rather than replaying stale drag coordinates.
    """

    def __init__(self, settings: ControlSettings, screen: Screen):
        self.settings, self.screen = settings, screen
        self.region = ActiveRegion(settings.region_width, settings.region_height)
        self.reset()

    def reset(self):
        self.previous = self.filtered = self.size = self.drag_offset = None
        self.drag_pending = False

    def map_point(self, point, size):
        x, y = self.region.normalize(point, size)
        if self.settings.invert_x:
            x = 1-x  # Mirror position once, within the selected display.
        return (self.screen.left+x*(self.screen.width-1),
                self.screen.top+y*(self.screen.height-1))

    def begin_drag(self, point, size, current):
        mapped = self.map_point(point, size)
        if self.screen.clamp(*current) != tuple(current):
            raise ValueError("Place the cursor on the selected monitor before activation")
        self.drag_offset = (current[0]-mapped[0], current[1]-mapped[1])
        self.filtered, self.previous, self.size = tuple(current), tuple(point), size
        self.drag_pending = True

    def update(self, point, size, current):
        target = self.map_point(point, size)
        if self.drag_pending and self.size == size:
            self.drag_pending = False
            return None  # Mouse-down preserves the cursor; HELD remains responsive.
        if self.previous is None or self.size != size:
            if self.drag_offset is not None:
                raise ValueError("Camera geometry changed during drag")
            if self.screen.clamp(*current) != tuple(current):
                raise ValueError("Place the cursor on the selected monitor before activation")
            self.previous, self.size, self.filtered = tuple(point), size, tuple(current)
            return None
        if self.drag_offset is not None:
            target = (target[0]+self.drag_offset[0], target[1]+self.drag_offset[1])
        # Clamp before EMA to avoid windup; retain fractional EMA state until delivery.
        target = (max(self.screen.left, min(self.screen.left+self.screen.width-1, target[0])),
                  max(self.screen.top, min(self.screen.top+self.screen.height-1, target[1])))
        alpha = self.settings.alpha
        self.filtered = tuple(alpha*target[i]+(1-alpha)*self.filtered[i] for i in (0, 1))
        self.previous = tuple(point)
        return self.screen.clamp(*self.filtered)
