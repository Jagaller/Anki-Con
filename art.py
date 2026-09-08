"""
Joy-Con artwork: pure geometry, no Qt.

Each half is described once in its own local coordinate box (LOCAL_W x LOCAL_H
units, y growing downward). The view scales that box to whatever room it has and
applies an orientation transform, so nothing here has to know about widget
sizes, rotation or DPI.

Element ids are the bare button names ("A", "ZL", "StickUp"); the view prefixes
them with "L:" / "R:" to get the binding ids used by joycon.protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .joycon import protocol as P

LOCAL_W = 120.0
LOCAL_H = 344.0

# Shell body. The outer edge (away from the other Joy-Con) is heavily rounded,
# the rail edge is nearly square -- that contrast is what makes the silhouette
# read as a Joy-Con rather than a phone.
BODY_TOP = 38.0
BODY_BOT = 336.0
BODY_L = 12.0
BODY_R = 108.0
OUTER_R = 36.0
INNER_R = 9.0

STICK_R = 27.0


@dataclass(frozen=True)
class Element:
    """One drawn feature. Decorative parts have id ""."""

    id: str
    kind: str          # circle | rrect | stick | plus | minus | capture | rail | tab | band
    x: float = 0.0     # centre for circle/stick, top-left for rrect-likes
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    r: float = 0.0     # radius: circle radius, or corner radius for rrects
    label: str = ""

    # -- geometry ------------------------------------------------------------

    def anchor(self) -> Tuple[float, float]:
        """Where a callout leader line should land."""
        if self.kind in ("circle", "stick"):
            return self.x, self.y
        return self.x + self.w / 2.0, self.y + self.h / 2.0

    def bounds(self) -> Tuple[float, float, float, float]:
        """(x, y, w, h) in local units."""
        if self.kind in ("circle", "stick"):
            return self.x - self.r, self.y - self.r, self.r * 2, self.r * 2
        return self.x, self.y, self.w, self.h

    def hit_radius(self) -> float:
        """Click tolerance, so small features stay reachable."""
        x, y, w, h = self.bounds()
        return max(11.0, min(w, h) / 2.0 + 3.0)


def _stick(cx: float, cy: float, click_id: str) -> List[Element]:
    """A stick plus its four direction pseudo-buttons.

    The directions have no plastic of their own, so they anchor just outside the
    stick's rim in the direction they represent -- the leader line then points
    the way you'd actually push.
    """
    d = STICK_R + 6.0
    return [
        Element(click_id, "stick", cx, cy, r=STICK_R, label="Stick click"),
        Element("StickUp", "dir", cx, cy - d, r=7, label="Stick ▲"),
        Element("StickDown", "dir", cx, cy + d, r=7, label="Stick ▼"),
        Element("StickLeft", "dir", cx - d, cy, r=7, label="Stick ◀"),
        Element("StickRight", "dir", cx + d, cy, r=7, label="Stick ▶"),
    ]


# --------------------------------------------------------------------------
# Left Joy-Con
# --------------------------------------------------------------------------

LEFT: List[Element] = [
    # Shoulder: ZL is the rear cap, L the band across the top face. Both sit
    # over the shell's flat top edge -- the outer corner is too rounded to
    # carry them.
    Element("ZL", "tab", 48, 10, 54, 38, r=14, label="ZL"),
    Element("L", "band", 14, 34, 92, 26, r=12, label="L"),

    Element("Minus", "minus", 76, 68, 18, 6, r=3, label="− Minus"),

    *_stick(56, 124, "LStick"),

    Element("Up", "circle", 56, 198, r=14, label="▲ Up"),
    Element("Left", "circle", 29, 226, r=14, label="◀ Left"),
    Element("Right", "circle", 83, 226, r=14, label="▶ Right"),
    Element("Down", "circle", 56, 254, r=14, label="▼ Down"),

    Element("Capture", "capture", 45, 290, 22, 22, r=5, label="Capture"),

    # rail buttons live on the flat inner edge
    Element("SL", "rrect", 98, 132, 12, 34, r=5, label="SL (rail)"),
    Element("SR", "rrect", 98, 214, 12, 34, r=5, label="SR (rail)"),
]

# --------------------------------------------------------------------------
# Right Joy-Con -- mirrored, but the face cluster and Home are its own
# --------------------------------------------------------------------------

RIGHT: List[Element] = [
    Element("ZR", "tab", 18, 10, 54, 38, r=14, label="ZR"),
    Element("R", "band", 14, 34, 92, 26, r=12, label="R"),

    Element("Plus", "plus", 26, 64, 16, 16, r=3, label="+ Plus"),

    Element("X", "circle", 64, 98, r=15, label="X"),
    Element("Y", "circle", 38, 130, r=15, label="Y"),
    Element("A", "circle", 90, 130, r=15, label="A"),
    Element("B", "circle", 64, 162, r=15, label="B"),

    *_stick(64, 236, "RStick"),

    Element("Home", "home", 64, 302, r=14, label="Home"),

    # The rail is mirrored on this half, and so is the order of its buttons.
    # Held sideways the right Joy-Con turns *clockwise* (its left-edge rail
    # goes to the top), so the LOWER rail button is the one that ends up under
    # your left index finger: SR is the upper button here, SL the lower --
    # the opposite of the left Joy-Con above.
    Element("SR", "rrect", 10, 132, 12, 34, r=5, label="SR (rail)"),
    Element("SL", "rrect", 10, 214, 12, 34, r=5, label="SL (rail)"),
]


def elements_for(side: str) -> List[Element]:
    return LEFT if side == P.SIDE_LEFT else RIGHT


def bindable(side: str) -> List[Element]:
    """Drawn features that can carry a binding, sorted top-to-bottom.

    Callout slots are handed out in this order, which is what keeps the leader
    lines from crossing each other.
    """
    els = [e for e in elements_for(side) if e.id]
    return sorted(els, key=lambda e: (e.anchor()[1], e.anchor()[0]))


def binding_id(side: str, element_id: str) -> str:
    """Element id -> the "L:"/"R:" id used by settings and protocol."""
    return ("L:" if side == P.SIDE_LEFT else "R:") + element_id


def element_label(side: str, element_id: str) -> str:
    for e in elements_for(side):
        if e.id == element_id:
            return e.label
    return element_id


# --------------------------------------------------------------------------
# Default colours
# --------------------------------------------------------------------------

# Neutral grey shells with dark buttons, matching how a stock Joy-Con is
# usually pictured; every one of these can be overridden per button.
DEFAULT_SHELL_LEFT = "#7d838b"
DEFAULT_SHELL_RIGHT = "#7d838b"
DEFAULT_BUTTON = "#33363c"
DEFAULT_STICK = "#2b2e33"
DEFAULT_RAIL = "#5c626a"


def default_button_color(side: str, element_id: str) -> str:
    if element_id in ("LStick", "RStick"):
        return DEFAULT_STICK
    if element_id in ("SL", "SR"):
        return DEFAULT_RAIL
    return DEFAULT_BUTTON
