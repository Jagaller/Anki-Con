"""
Per-controller state: the init handshake, button edge detection, and turning
the analog stick into four direction pseudo-buttons.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Set

from . import protocol as P

# Raw 12-bit stick values sit near 2048 at rest but vary per unit, so the
# centre is learned instead of assumed. Deflection is measured against these.
_STICK_FULL = 1100.0
_SAMPLES_TO_CENTRE = 20


class JoyConDevice:
    # Gap between handshake subcommands. The controller needs time to process
    # and answer each one; anything much tighter gets dropped.
    SUBCMD_SPACING = 0.09
    MAX_INIT_TRIES = 25

    def __init__(self, handle: int, product_id: int, serial: str,
                 send: Callable[[int, bytes], None], player: int = 1,
                 deadzone: float = 0.5, log=print, leds: bool = True) -> None:
        self.handle = handle
        self.product_id = product_id
        self.serial = serial
        self.side = P.PRODUCTS.get(product_id, P.SIDE_RIGHT)
        self.name = P.PRODUCT_NAMES.get(product_id, "Controller")
        self.player = player
        self.deadzone = deadzone
        self.leds = leds
        self._send = send
        self._log = log

        self.battery: Optional[int] = None
        self.charging = False
        self.full_mode = False
        self.last_seen = time.time()
        self.attached_at = time.time()
        self.reports = 0        # input reports seen; 0 means the link is silent
        self.warned_silent = False

        self._counter = 0
        self._pressed: Set[str] = set()
        self._centre = None
        self._centre_samples: list = []
        self._init_deadline = 0.0
        self._init_tries = 0
        self._acked: Set[int] = set()

    # -- outgoing ----------------------------------------------------------

    def _next_counter(self) -> int:
        self._counter = (self._counter + 1) & 0x0F
        return self._counter

    def _subcmd(self, sub: int, args: bytes = b"", delay: float = 0.0) -> None:
        self._send(self.handle, P.subcommand(self._next_counter(), sub, args),
                   delay)

    def handshake_done(self) -> bool:
        """Full report mode is live and vibration was acknowledged."""
        return self.full_mode and P.SUBCMD_ENABLE_VIBRATION in self._acked

    def initialise(self) -> None:
        """Ask the controller for full 60 Hz reports, LEDs and vibration.

        The subcommands are spaced out on purpose. A Joy-Con handles one at a
        time and silently drops anything that arrives while it is busy, so
        sending all four back-to-back means a race in which some land and some
        do not -- which shows up later as "rumble does nothing" or "the buttons
        are scrambled", depending on which one lost. Only the subcommands that
        have not taken effect are re-sent.
        """
        self._init_tries += 1
        wanted = [
            (P.SUBCMD_ENABLE_VIBRATION, bytes([0x01])),
            (P.SUBCMD_ENABLE_IMU, bytes([0x00])),   # off: nothing here needs gyro
            (P.SUBCMD_SET_PLAYER_LIGHTS, bytes([self._light_mask()])),
            (P.SUBCMD_SET_INPUT_MODE, bytes([P.REPORT_STANDARD])),
        ]
        # An acknowledged input mode still counts as outstanding until 0x30
        # reports actually arrive: a Joy-Con can accept the command and stay in
        # basic mode, and then the retries would have nothing to send.
        todo = [(sub, args) for sub, args in wanted
                if sub not in self._acked
                or (sub == P.SUBCMD_SET_INPUT_MODE and not self.full_mode)]
        # Input mode last: once 0x30 reports start flowing the 0x21 replies for
        # anything still outstanding stop arriving.
        for i, (sub, args) in enumerate(todo):
            self._subcmd(sub, args, delay=i * self.SUBCMD_SPACING)
        self._init_deadline = time.time() + len(todo) * self.SUBCMD_SPACING + 1.0

    def poll_init(self) -> None:
        """Re-send whatever has not taken effect yet.

        Keeps trying for a while rather than giving up after a fixed handful:
        a controller that misses the handshake is not usable, and retrying is
        cheap compared with the user concluding the add-on is broken.
        """
        if self.handshake_done() or self._init_tries >= self.MAX_INIT_TRIES:
            return
        if self._init_deadline and time.time() > self._init_deadline:
            missing = [hex(s) for s, _ in (
                (P.SUBCMD_ENABLE_VIBRATION, 0), (P.SUBCMD_SET_INPUT_MODE, 0))
                if s not in self._acked]
            self._log(f"{self.name}: handshake retry {self._init_tries + 1} "
                      f"(waiting on {', '.join(missing) or 'full-mode reports'})")
            self.initialise()

    def rumble(self, freq: float = 320.0, amp: float = 0.35,
               ms: int = 90) -> None:
        data = P.encode_rumble(freq, amp)
        self._send(self.handle, P.rumble_report(self._next_counter(), data))
        # The stop packet has to be held back: queued immediately it reaches the
        # controller microseconds later and the motor never spins up at all.
        self._send(self.handle,
                   P.rumble_report(self._next_counter(), P.NEUTRAL_RUMBLE),
                   max(0.02, ms / 1000.0))

    def set_player(self, player: int) -> None:
        self.player = player
        self._send_lights()

    def set_leds(self, on: bool) -> None:
        self.leds = on
        self._send_lights()

    def _light_mask(self) -> int:
        return P.player_light_mask(self.player) if self.leds else 0

    def _send_lights(self) -> None:
        self._subcmd(P.SUBCMD_SET_PLAYER_LIGHTS, bytes([self._light_mask()]))

    # -- incoming ----------------------------------------------------------

    def handle_report(self, data: bytes):
        """Return a list of (button_id, pressed) edges."""
        if not data:
            return []
        self.last_seen = time.time()
        self.reports += 1
        rid = data[0]

        if rid in (P.REPORT_STANDARD, P.REPORT_SUBCMD_REPLY, P.REPORT_NFC_IR):
            if rid == P.REPORT_SUBCMD_REPLY:
                reply = P.parse_subcmd_ack(data)
                if reply and reply[1]:
                    self._acked.add(reply[0])
            parsed = P.parse_standard(data)
            if rid == P.REPORT_STANDARD:
                self.full_mode = True
        elif rid == P.REPORT_SIMPLE:
            parsed = P.parse_simple(data, self.side)
        else:
            return []

        if not parsed:
            return []

        if parsed["battery"] is not None:
            self.battery = parsed["battery"]
            self.charging = parsed["charging"]

        pressed = set(parsed["buttons"])
        if parsed["full"]:
            pressed |= self._stick_directions(parsed)

        edges = []
        for b in pressed - self._pressed:
            edges.append((b, True))
        for b in self._pressed - pressed:
            edges.append((b, False))
        self._pressed = pressed
        return edges

    def _stick_directions(self, parsed) -> Set[str]:
        raw = parsed["left_stick"] if self.side != P.SIDE_RIGHT else parsed["right_stick"]
        half = "L" if self.side != P.SIDE_RIGHT else "R"
        if raw is None:
            return set()

        # Pro Controller: both sticks, both halves.
        if self.side == P.SIDE_PRO:
            out = self._one_stick(parsed["left_stick"], "L")
            out |= self._one_stick(parsed["right_stick"], "R")
            return out
        return self._one_stick(raw, half)

    def _one_stick(self, raw, half: str) -> Set[str]:
        if raw is None or raw == (0, 0):
            return set()
        if self._centre is None:
            self._centre_samples.append(raw)
            if len(self._centre_samples) < _SAMPLES_TO_CENTRE:
                return set()
            xs = [s[0] for s in self._centre_samples]
            ys = [s[1] for s in self._centre_samples]
            self._centre = (sum(xs) / len(xs), sum(ys) / len(ys))
            self._centre_samples = []

        cx, cy = self._centre
        dx = (raw[0] - cx) / _STICK_FULL
        dy = (raw[1] - cy) / _STICK_FULL

        # Hysteresis: engage at the deadzone, release at 70% of it, so a stick
        # resting near the edge does not machine-gun the reviewer.
        on = self.deadzone
        off = self.deadzone * 0.7
        out: Set[str] = set()

        def axis(value, pos_id, neg_id):
            held_pos = (half + ":" + pos_id) in self._pressed
            held_neg = (half + ":" + neg_id) in self._pressed
            if value > (off if held_pos else on):
                out.add(half + ":" + pos_id)
            elif value < -(off if held_neg else on):
                out.add(half + ":" + neg_id)

        axis(dx, "StickRight", "StickLeft")
        axis(dy, "StickUp", "StickDown")
        return out

    # -- info --------------------------------------------------------------

    def info(self) -> dict:
        return {
            "handle": self.handle,
            "name": self.name,
            "side": self.side,
            "serial": self.serial,
            "battery": self.battery,
            "charging": self.charging,
            "full_mode": self.full_mode,
            "player": self.player,
            "reports": self.reports,
            "vibration": P.SUBCMD_ENABLE_VIBRATION in self._acked,
            "acked": sorted(hex(a) for a in self._acked),
            "init_tries": self._init_tries,
        }
