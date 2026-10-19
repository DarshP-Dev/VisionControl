"""Relative, aspect-correct index-tip displacement with screen-space EMA."""

import math

from .models import ControlSettings, Screen


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
