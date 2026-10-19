"""Simulation backend. The Windows backend is imported only for explicit live mode."""

from collections import Counter

from .models import Screen


class SimulationBackend:
    is_live = False

    def __init__(self, screen=Screen(), foreground="chrome.exe"):
        self.screen, self.foreground = screen, foreground
        self.position = screen.clamp(screen.left+screen.width/2, screen.top+screen.height/2)
        self.button_down = False
        self.counts = Counter()
        self.last_keys = ()

    def cursor_position(self):
        return self.position

    def move(self, x, y):
        self.position = self.screen.clamp(x, y)
        self.counts["move"] += 1

    def left_down(self):
        self.button_down = True
        self.counts["down"] += 1

    def left_up(self):
        self.button_down = False
        self.counts["up"] += 1

    def switch_tab(self, previous, allowed):
        if self.foreground.casefold() not in allowed:
            return False
        self.last_keys = ("CTRL", "SHIFT", "TAB") if previous else ("CTRL", "TAB")
        self.counts["tab"] += 1
        return True

    def close(self):
        if self.button_down:
            self.left_up()
