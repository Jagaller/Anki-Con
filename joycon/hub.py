"""
Backend-agnostic front door. Owns the device table and forwards button edges
to a callback. Callbacks fire on the HID thread -- the Qt layer is responsible
for hopping to the main thread.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from . import protocol as P
from .device import JoyConDevice


class JoyConHub:
    def __init__(self, on_button: Callable[[object, str, bool], None],
                 on_devices_changed: Callable[[List[dict]], None] = None,
                 deadzone: float = 0.5, log=print, seize: bool = False,
                 player_leds: bool = True) -> None:
        self.on_button = on_button
        self.on_devices_changed = on_devices_changed or (lambda _d: None)
        self.deadzone = deadzone
        self.log = log
        self.seize = seize
        self.player_leds = player_leds

        self._devices: Dict[int, JoyConDevice] = {}
        self._lock = threading.RLock()
        self._backend = None
        self._keeper: Optional[threading.Thread] = None
        self._keeper_stop = threading.Event()
        self.backend_name = "none"
        self.last_error: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        if self.is_running():
            return True

        from . import backend_macos, backend_hidapi

        if backend_macos.available():
            self._backend = backend_macos.MacHIDBackend(
                self._attached, self._report, self._detached, log=self.log,
                seize=self.seize)
            self.backend_name = "IOKit"
        elif backend_hidapi.available():
            self._backend = backend_hidapi.HidApiBackend(
                self._attached, self._report, self._detached, log=self.log)
            self.backend_name = "hidapi"
        else:
            self.last_error = (
                "No HID backend available. macOS works out of the box; on "
                "Windows/Linux install the 'hidapi' Python package into Anki's "
                "environment.")
            self.log(self.last_error)
            return False

        self._backend.start()
        # A fresh event per run, so a keeper still sleeping from the last run
        # can't be revived by this one.
        self._keeper_stop = threading.Event()
        self._keeper = threading.Thread(target=self._keepalive_loop,
                                        args=(self._keeper_stop,),
                                        name="JoyConKeeper", daemon=True)
        self._keeper.start()
        return True

    def is_running(self) -> bool:
        return self._backend is not None

    def stop(self) -> None:
        self._keeper_stop.set()
        if self._backend:
            try:
                self._backend.stop()
            except Exception:
                pass
        self._backend = None
        with self._lock:
            self._devices.clear()
        self._notify()

    def restart(self) -> bool:
        self.stop()
        time.sleep(0.2)
        return self.start()

    # -- state -------------------------------------------------------------

    def devices(self) -> List[dict]:
        with self._lock:
            return [d.info() for d in self._devices.values()]

    def device_sides(self) -> List[str]:
        with self._lock:
            return [d.side for d in self._devices.values()]

    def rumble_all(self, freq: float = 320.0, amp: float = 0.35) -> None:
        with self._lock:
            devs = list(self._devices.values())
        for d in devs:
            try:
                d.rumble(freq, amp)
            except Exception:
                pass

    def rumble(self, handle: int, freq: float = 320.0, amp: float = 0.35) -> None:
        with self._lock:
            d = self._devices.get(handle)
        if d:
            d.rumble(freq, amp)

    def set_deadzone(self, value: float) -> None:
        self.deadzone = value
        with self._lock:
            for d in self._devices.values():
                d.deadzone = value

    def set_player_leds(self, on: bool) -> None:
        self.player_leds = on
        with self._lock:
            devs = list(self._devices.values())
        for d in devs:
            if d.leds != on:
                d.set_leds(on)

    # -- backend callbacks (HID thread) ------------------------------------

    def _attached(self, handle: int, product_id: int, serial: str) -> None:
        with self._lock:
            player = len(self._devices) + 1
            dev = JoyConDevice(handle, product_id, serial,
                               send=self._send, player=player,
                               deadzone=self.deadzone, log=self.log,
                               leds=self.player_leds)
            self._devices[handle] = dev
        self.log(f"connected: {dev.name} ({serial})")
        dev.initialise()
        self._notify()

    def _detached(self, handle: int) -> None:
        with self._lock:
            dev = self._devices.pop(handle, None)
        if dev:
            self.log(f"disconnected: {dev.name}")
            # renumber player LEDs so the remaining controller is player 1
            with self._lock:
                for i, d in enumerate(self._devices.values(), start=1):
                    if d.player != i:
                        try:
                            d.set_player(i)
                        except Exception:
                            pass
        self._notify()

    def _report(self, handle: int, data: bytes) -> None:
        with self._lock:
            dev = self._devices.get(handle)
        if not dev:
            return
        try:
            edges = dev.handle_report(data)
        except Exception as exc:
            self.log(f"report parse error: {exc}")
            return
        for button, pressed in edges:
            try:
                self.on_button(dev, button, pressed)
            except Exception as exc:
                self.log(f"dispatch error: {exc}")

    def _send(self, handle: int, payload: bytes, delay: float = 0.0) -> None:
        if self._backend:
            self._backend.send(handle, payload, delay)

    def _notify(self) -> None:
        try:
            self.on_devices_changed(self.devices())
        except Exception:
            pass

    def _keepalive_loop(self, stop: threading.Event) -> None:
        while not stop.wait(0.5):
            with self._lock:
                devs = list(self._devices.values())
            for d in devs:
                try:
                    d.poll_init()
                    self._check_silent(d)
                except Exception:
                    pass

    def _check_silent(self, dev) -> None:
        """Say so, once, when a controller connects but never sends anything.

        This is the failure that otherwise just looks like "the buttons don't
        work": the device node is there, so it shows as connected, but the HID
        open was refused and no reports are coming.
        """
        if dev.reports or dev.warned_silent:
            return
        if time.time() - dev.attached_at < 3.0:
            return
        dev.warned_silent = True
        self.log(f"{dev.name} is connected but has sent no input reports. "
                 "macOS is most likely holding the controller with its own "
                 "driver -- try 'Exclusive control' in Options.")

    def stats(self) -> dict:
        b = self._backend
        return {
            "backend": self.backend_name,
            "reports_in": getattr(b, "reports_in", 0),
            "reports_out": getattr(b, "reports_out", 0),
            "send_errors": getattr(b, "send_errors", 0),
            "seize": self.seize,
        }
