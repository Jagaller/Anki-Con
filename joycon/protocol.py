"""
Nintendo Joy-Con / Pro Controller Bluetooth-HID protocol.

Pure data-in / bytes-out. No I/O here, so it can be unit-tested without hardware
and reused by any backend (IOKit on macOS, hidapi elsewhere).

Reference: the community reverse-engineering notes at
dekuNukem/Nintendo_Switch_Reverse_Engineering.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Device identification
# --------------------------------------------------------------------------

VENDOR_NINTENDO = 0x057E

PRODUCT_JOYCON_L = 0x2006
PRODUCT_JOYCON_R = 0x2007
PRODUCT_PRO = 0x2009
PRODUCT_GRIP = 0x200E

# side codes used throughout the add-on
SIDE_LEFT = "left"
SIDE_RIGHT = "right"
SIDE_PRO = "pro"

PRODUCTS: Dict[int, str] = {
    PRODUCT_JOYCON_L: SIDE_LEFT,
    PRODUCT_JOYCON_R: SIDE_RIGHT,
    PRODUCT_PRO: SIDE_PRO,
    PRODUCT_GRIP: SIDE_PRO,
}

PRODUCT_NAMES: Dict[int, str] = {
    PRODUCT_JOYCON_L: "Joy-Con (L)",
    PRODUCT_JOYCON_R: "Joy-Con (R)",
    PRODUCT_PRO: "Pro Controller",
    PRODUCT_GRIP: "Charging Grip",
}

# --------------------------------------------------------------------------
# Report IDs
# --------------------------------------------------------------------------

REPORT_STANDARD = 0x30  # full mode: buttons + analog sticks + IMU, 60 Hz
REPORT_NFC_IR = 0x31
REPORT_SUBCMD_REPLY = 0x21  # standard report + reply to our last subcommand
REPORT_SIMPLE = 0x3F  # the low-rate "sideways gamepad" report sent by default

OUT_RUMBLE_AND_SUBCMD = 0x01
OUT_RUMBLE_ONLY = 0x10

# 8 bytes (4 left motor, 4 right motor) meaning "no vibration"
NEUTRAL_RUMBLE = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])

# Subcommands
SUBCMD_SET_INPUT_MODE = 0x03
SUBCMD_SET_HCI_STATE = 0x06
SUBCMD_SET_PLAYER_LIGHTS = 0x30
SUBCMD_ENABLE_IMU = 0x40
SUBCMD_ENABLE_VIBRATION = 0x48

# --------------------------------------------------------------------------
# Button tables
#
# Every button id is prefixed with the physical half it lives on ("L:" / "R:")
# so a left and a right Joy-Con can be bound independently and a Pro Controller
# just reports both halves.
# --------------------------------------------------------------------------

# byte 3 of report 0x30 -- right half
_BITS_RIGHT = ["Y", "X", "B", "A", "SR", "SL", "R", "ZR"]
# byte 4 -- shared byte; each of these physically lives on one specific half
_BITS_SHARED = [
    ("L", "Minus"),
    ("R", "Plus"),
    ("R", "RStick"),
    ("L", "LStick"),
    ("R", "Home"),
    ("L", "Capture"),
    (None, None),
    (None, None),
]
# byte 5 -- left half
_BITS_LEFT = ["Down", "Up", "Right", "Left", "SR", "SL", "L", "ZL"]

STICK_DIRECTIONS = ["StickUp", "StickDown", "StickLeft", "StickRight"]


def buttons_for_side(side: str) -> List[str]:
    """Every bindable input id a controller of this type can produce."""
    ids: List[str] = []
    if side in (SIDE_LEFT, SIDE_PRO):
        ids += ["L:" + n for n in
                ["Up", "Down", "Left", "Right", "L", "ZL", "SL", "SR",
                 "Minus", "Capture", "LStick"]]
        ids += ["L:" + d for d in STICK_DIRECTIONS]
    if side in (SIDE_RIGHT, SIDE_PRO):
        ids += ["R:" + n for n in
                ["A", "B", "X", "Y", "R", "ZR", "SL", "SR",
                 "Plus", "Home", "RStick"]]
        ids += ["R:" + d for d in STICK_DIRECTIONS]
    return ids


# Human labels for the config UI.
BUTTON_LABELS: Dict[str, str] = {
    "L:Up": "▲ Up", "L:Down": "▼ Down", "L:Left": "◀ Left", "L:Right": "▶ Right",
    "L:L": "L", "L:ZL": "ZL", "L:SL": "SL (rail)", "L:SR": "SR (rail)",
    "L:Minus": "− Minus", "L:Capture": "Capture (□)", "L:LStick": "Stick click",
    "L:StickUp": "Stick ▲", "L:StickDown": "Stick ▼",
    "L:StickLeft": "Stick ◀", "L:StickRight": "Stick ▶",
    "R:A": "A", "R:B": "B", "R:X": "X", "R:Y": "Y",
    "R:R": "R", "R:ZR": "ZR", "R:SL": "SL (rail)", "R:SR": "SR (rail)",
    "R:Plus": "+ Plus", "R:Home": "Home (◯)", "R:RStick": "Stick click",
    "R:StickUp": "Stick ▲", "R:StickDown": "Stick ▼",
    "R:StickLeft": "Stick ◀", "R:StickRight": "Stick ▶",
}


# --------------------------------------------------------------------------
# Input report parsing
# --------------------------------------------------------------------------

def _decode_stick(data: bytes, off: int) -> Tuple[int, int]:
    """Three packed bytes -> two 12-bit raw axis values."""
    x = data[off] | ((data[off + 1] & 0x0F) << 8)
    y = (data[off + 1] >> 4) | (data[off + 2] << 4)
    return x, y


def parse_subcmd_ack(data: bytes) -> Optional[Tuple[int, bool]]:
    """From a 0x21 reply: (subcommand id, acknowledged).

    The controller answers each subcommand with byte 13 = ACK (bit 7 set) or
    NACK, and byte 14 = the subcommand being answered. Without reading this the
    handshake is fire-and-forget, and a dropped subcommand is invisible.
    """
    if not data or data[0] != REPORT_SUBCMD_REPLY or len(data) < 15:
        return None
    return data[14], bool(data[13] & 0x80)


def parse_standard(data: bytes) -> Optional[dict]:
    """Parse a 0x30 / 0x21 / 0x31 standard input report."""
    if len(data) < 12:
        return None

    pressed: Set[str] = set()

    b = data[3]
    for i, name in enumerate(_BITS_RIGHT):
        if b & (1 << i):
            pressed.add("R:" + name)

    b = data[5]
    for i, name in enumerate(_BITS_LEFT):
        if b & (1 << i):
            pressed.add("L:" + name)

    b = data[4]
    for i, (half, name) in enumerate(_BITS_SHARED):
        if half and (b & (1 << i)):
            pressed.add(half + ":" + name)

    battery_nibble = data[2] >> 4
    return {
        "buttons": pressed,
        "left_stick": _decode_stick(data, 6),
        "right_stick": _decode_stick(data, 9),
        "battery": battery_nibble >> 1,      # 0..4  (4 = full)
        "charging": bool(battery_nibble & 1),
        "full": True,
    }


# In the default 0x3F report the Joy-Con pretends to be a small gamepad held
# *sideways*, so everything arrives rotated. Bits 0..3 of the button byte are
# that imaginary gamepad's Down/Right/Left/Up, and byte 3 is its 8-way hat.
#
# Undoing the rotation is the whole job, and getting it wrong is invisible
# until someone presses Down and the reviewer answers Easy -- so the turn is
# written out once, here, rather than baked into four hand-copied tables.
_SIDEWAYS_ORDER = ["Down", "Right", "Left", "Up"]        # bits 0..3

# To be held sideways the left Joy-Con is turned anticlockwise and the right
# clockwise (both so the SL/SR rail ends up on top). These undo that.
_UNROTATE = {
    SIDE_LEFT: {"Up": "Right", "Right": "Down", "Down": "Left", "Left": "Up"},
    SIDE_RIGHT: {"Up": "Left", "Left": "Down", "Down": "Right", "Right": "Up"},
}

# What the upright direction is actually called on each half.
_FACE_NAMES = {
    SIDE_LEFT: {"Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right"},
    SIDE_RIGHT: {"Up": "X", "Down": "B", "Left": "Y", "Right": "A"},
}

_SIMPLE_HAT = {
    0: ["Up"], 1: ["Up", "Right"], 2: ["Right"], 3: ["Right", "Down"],
    4: ["Down"], 5: ["Down", "Left"], 6: ["Left"], 7: ["Left", "Up"], 8: [],
}


def _simple_side(side: str) -> str:
    return SIDE_RIGHT if side == SIDE_RIGHT else SIDE_LEFT


def simple_face_ids(side: str) -> List[str]:
    """Button ids for bits 0..3 of a 0x3F report, in the printed labels."""
    key = _simple_side(side)
    half = "R" if key == SIDE_RIGHT else "L"
    unrot, names = _UNROTATE[key], _FACE_NAMES[key]
    return [f"{half}:{names[unrot[d]]}" for d in _SIDEWAYS_ORDER]


def simple_hat_ids(side: str, hat: int) -> List[str]:
    """Stick directions for a 0x3F hat value, rotated back upright."""
    key = _simple_side(side)
    half = "R" if key == SIDE_RIGHT else "L"
    unrot = _UNROTATE[key]
    return [f"{half}:Stick{unrot[d]}" for d in _SIMPLE_HAT.get(hat, [])]


def parse_simple(data: bytes, side: str) -> Optional[dict]:
    """Parse a 0x3F simple input report (fallback if full mode never engages)."""
    if len(data) < 4:
        return None
    half = "R" if side == SIDE_RIGHT else "L"
    face = simple_face_ids(side)

    pressed: Set[str] = set()
    b = data[1]
    for i in range(4):
        if b & (1 << i):
            pressed.add(face[i])
    if b & (1 << 4):
        pressed.add(half + ":SL")
    if b & (1 << 5):
        pressed.add(half + ":SR")

    b = data[2]
    if b & 0x01:
        pressed.add("L:Minus")
    if b & 0x02:
        pressed.add("R:Plus")
    if b & 0x04:
        pressed.add("L:LStick")
    if b & 0x08:
        pressed.add("R:RStick")
    if b & 0x10:
        pressed.add("R:Home")
    if b & 0x20:
        pressed.add("L:Capture")
    if b & 0x40:
        pressed.add(half + ":" + ("R" if half == "R" else "L"))
    if b & 0x80:
        pressed.add(half + ":Z" + ("R" if half == "R" else "L"))

    pressed.update(simple_hat_ids(side, data[3]))

    return {
        "buttons": pressed,
        "left_stick": None,
        "right_stick": None,
        "battery": None,
        "charging": False,
        "full": False,
    }


# --------------------------------------------------------------------------
# Output reports
# --------------------------------------------------------------------------

def subcommand(counter: int, subcmd: int, args: bytes = b"",
               rumble: bytes = NEUTRAL_RUMBLE) -> bytes:
    """Build a 0x01 output report carrying a subcommand."""
    return (bytes([OUT_RUMBLE_AND_SUBCMD, counter & 0x0F])
            + rumble + bytes([subcmd]) + bytes(args))


def rumble_report(counter: int, rumble: bytes) -> bytes:
    return bytes([OUT_RUMBLE_ONLY, counter & 0x0F]) + bytes(rumble)


def _encode_freq(freq: float) -> Tuple[int, int]:
    freq = max(40.875885, min(1252.572266, freq))
    enc = int(round(math.log2(freq / 10.0) * 32.0))
    hf = (enc - 0x60) * 4
    lf = enc - 0x40
    return hf & 0xFFFF, lf & 0xFF


def _encode_amp(amp: float) -> Tuple[int, int]:
    amp = max(0.0, min(1.0, amp))
    if amp == 0:
        hf_amp = 0
    elif amp < 0.117:
        hf_amp = int(((math.log(amp * 1000, 2) * 32) - 0x60)
                     / (5 - pow(amp, 2)) - 1)
    elif amp < 0.23:
        hf_amp = int(((math.log(amp * 1000, 2) * 32) - 0x60) - 0x5C)
    else:
        hf_amp = int((((math.log(amp * 1000, 2) * 32) - 0x60) * 2) - 0xF6)
    hf_amp = max(0, min(0xC8, hf_amp))

    lf_amp = hf_amp // 2
    parity = lf_amp % 2
    if parity:
        lf_amp -= 1
    lf_amp = (lf_amp >> 1) + 0x40
    if parity:
        lf_amp |= 0x8000
    return hf_amp, lf_amp


def encode_rumble(freq: float = 320.0, amp: float = 0.35) -> bytes:
    """One motor's 4 bytes; doubled to make the 8-byte rumble field."""
    if amp <= 0:
        return NEUTRAL_RUMBLE
    hf, lf = _encode_freq(freq)
    hf_amp, lf_amp = _encode_amp(amp)
    one = bytes([
        hf & 0xFF,
        ((hf >> 8) & 0xFF) | hf_amp,
        lf | ((lf_amp >> 8) & 0xFF),
        lf_amp & 0xFF,
    ])
    return one + one


def player_light_mask(player: int) -> int:
    """Player 1..4 -> steady LED bitmask."""
    return 1 << max(0, min(3, player - 1))
