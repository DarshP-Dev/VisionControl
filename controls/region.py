"""Centered, normalized camera region shared by mapping and preview overlays."""

from dataclasses import dataclass

from gestures.models import ImageSize, finite_number


@dataclass(frozen=True, slots=True)
class ActiveRegion:
    width: float = .80
    height: float = .80

    def __post_init__(self):
        for name in ("width", "height"):
            value = finite_number(getattr(self, name), f"Region {name}")
            if not 0 < value <= 1:
                raise ValueError(f"Region {name} must be greater than 0 and at most 1")

    @property
    def left(self):
        return (1-self.width)/2

    @property
    def top(self):
        return (1-self.height)/2

    def geometry(self, size):
        """Return left, top, width, height in actual capture pixels (not a crop)."""
        if not isinstance(size, ImageSize):
            raise ValueError("Active region requires valid camera ImageSize")
        return (self.left*size.width, self.top*size.height,
                self.width*size.width, self.height*size.height)

    def normalize(self, point, size):
        if not isinstance(size, ImageSize):
            raise ValueError("Absolute cursor requires valid camera ImageSize")
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("Absolute cursor requires an x/y fingertip pair")
        x, y = (finite_number(v, "Fingertip") for v in point)
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Absolute cursor requires in-frame landmarks")
        # Tasks landmarks already use separate normalized image axes. No aspect factor.
        return (max(0., min(1., (x-self.left)/self.width)),
                max(0., min(1., (y-self.top)/self.height)))

    def preview_bounds(self, width, height):
        """Use the same normalized-to-pixel convention as hand skeleton rendering."""
        size = ImageSize(width, height)
        return ((round(self.left*(size.width-1)), round(self.top*(size.height-1))),
                (round((self.left+self.width)*(size.width-1)),
                 round((self.top+self.height)*(size.height-1))))
