"""
Glue between the HID thread and Anki's main thread.

Button edges arrive on a background thread; Qt widgets and the Anki collection
may only be touched on the main thread, so everything crosses over through a
queued signal.
"""

from __future__ import annotations

import time
from typing import List, Optional

from aqt import mw
from aqt.qt import *
from aqt.utils import tooltip

from . import actions, settings
from .joycon.hub import JoyConHub


def _queued():
    try:
        return Qt.ConnectionType.QueuedConnection
    except AttributeError:
        return Qt.QueuedConnection


class _Bridge(QObject):
    # button id, pressed, device handle. The handle is a 64-bit pointer on macOS
    # and a Qt int is 32-bit, so it crosses as an object to survive intact.
    button = pyqtSignal(str, bool, object)
    devices = pyqtSignal(object)             # list[dict]
    message = pyqtSignal(str)


class JoyConController:
    """One per Anki session."""

    # Stick directions repeat while held, unless the action opts out; buttons
    # do not.
    REPEAT_AFTER = 0.45
    REPEAT_EVERY = 0.14

    def __init__(self) -> None:
        self.bridge = _Bridge()
        self.bridge.button.connect(self._on_button_main, _queued())
        self.bridge.devices.connect(self._on_devices_main, _queued())
        self.bridge.message.connect(self._on_message_main, _queued())

        self.cfg = settings.get()
        self.hub: Optional[JoyConHub] = None
        self.device_info: List[dict] = []
        self.log_lines: List[str] = []
        self.recent_inputs: List[str] = []
        # Which grip's map is live. Recomputed whenever the device set changes.
        self.layout_name: str = settings.LAYOUT_DUAL

        self._held: dict = {}
        self._repeat_timer: Optional[QTimer] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        self.cfg = settings.get()
        self._recompute_layout()
        if not self.cfg.get("enabled", True):
            return False
        if self.hub is None:
            self.hub = JoyConHub(
                on_button=self._on_button_thread,
                on_devices_changed=lambda d: self.bridge.devices.emit(d),
                deadzone=float(self.cfg.get("stick_deadzone", 0.5)),
                log=lambda m: self.bridge.message.emit(str(m)),
                seize=bool(self.cfg.get("seize_device", False)),
                player_leds=bool(self.cfg.get("player_leds", True)),
            )
        ok = self.hub.start()

        if self._repeat_timer is None:
            self._repeat_timer = QTimer(mw)
            self._repeat_timer.setInterval(40)
            qconnect(self._repeat_timer.timeout, self._tick_repeat)
        self._repeat_timer.start()
        return ok

    def stop(self) -> None:
        if self._repeat_timer:
            self._repeat_timer.stop()
        if self.hub:
            self.hub.stop()
        self.device_info = []
        self._held.clear()

    def restart(self) -> bool:
        self.stop()
        self.hub = None
        return self.start()

    def reload_config(self) -> None:
        self.cfg = settings.get()
        self._recompute_layout()
        want_seize = bool(self.cfg.get("seize_device", False))
        if self.hub and self.hub.seize != want_seize:
            # Exclusive access is decided when the device is opened, so the new
            # setting only means anything after a fresh open. Do it here rather
            # than making the user find Rescan -- this is the setting people
            # reach for precisely because nothing is working.
            self.restart()
            return
        if self.hub:
            self.hub.set_deadzone(float(self.cfg.get("stick_deadzone", 0.5)))
            self.hub.set_player_leds(bool(self.cfg.get("player_leds", True)))
        if self.cfg.get("enabled", True):
            if self.hub is None or not self.hub.is_running():
                self.start()
        else:
            self.stop()

    # -- HID thread --------------------------------------------------------

    def _on_button_thread(self, device, button: str, pressed: bool) -> None:
        self.bridge.button.emit(button, pressed, device.handle)

    # -- main thread -------------------------------------------------------

    def _on_devices_main(self, info) -> None:
        self.device_info = list(info or [])
        self._drop_stale_holds()
        self._recompute_layout()

    def _drop_stale_holds(self) -> None:
        """Forget sticks held on a controller that has gone away.

        A disconnect sends no release, so without this the other Joy-Con staying
        connected was enough to keep the action repeating forever.
        """
        live = {d.get("handle") for d in self.device_info}
        for button, (_due, handle) in list(self._held.items()):
            if handle not in live:
                del self._held[button]

    def poll_devices(self) -> None:
        """Re-read live device state.

        The hub only pushes on attach/detach, so anything that changes while a
        controller stays connected -- battery, full mode, the report counter --
        was frozen at whatever it happened to be the moment it was plugged in.
        That made a perfectly working controller keep reporting itself silent.
        """
        if self.hub is None:
            return
        try:
            self.device_info = self.hub.devices()
        except Exception:
            return
        self._drop_stale_holds()
        self._recompute_layout()

    def _recompute_layout(self) -> None:
        sides = {d.get("side") for d in self.device_info if d.get("side")}
        self.layout_name = settings.active_layout(
            sides, self.cfg.get("orientation", settings.LAYOUT_SINGLE_H))

    def bindings(self) -> dict:
        return settings.bindings_for(self.cfg, self.layout_name)

    def _on_message_main(self, msg: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del self.log_lines[:-200]
        if self.cfg.get("verbose_log"):
            print(f"[joycon] {msg}")

    def _on_button_main(self, button: str, pressed: bool, handle: int) -> None:
        # let the config dialog show live presses even when unbound
        for cb in list(getattr(self, "_watchers", [])):
            try:
                cb(button, pressed)
            except Exception:
                pass

        # Keep a short trail of what the hardware actually reported, so a
        # "this button does the wrong thing" can be checked against the id the
        # add-on saw rather than guessed at.
        mode = "?"
        for d in self.device_info:
            if d.get("handle") == handle:
                mode = "full" if d.get("full_mode") else "basic"
                break
        self.recent_inputs.append(
            f"{time.strftime('%H:%M:%S')}  {button:<14} "
            f"{'press' if pressed else 'release':<8} [{mode} mode]")
        del self.recent_inputs[:-60]

        if not pressed:
            self._held.pop(button, None)
            return

        self._fire(button, handle)

        if "Stick" in button:
            self._held[button] = (time.time() + self.REPEAT_AFTER, handle)

    def _tick_repeat(self) -> None:
        now = time.time()
        for button, (due, handle) in list(self._held.items()):
            if now >= due:
                act = actions.ACTIONS_BY_ID.get(self.bindings().get(button))
                if act is not None and not act.repeatable:
                    continue
                self._fire(button, handle, repeat=True)
                self._held[button] = (now + self.REPEAT_EVERY, handle)

    def _fire(self, button: str, handle: int, repeat: bool = False) -> None:
        action_id = self.bindings().get(button)
        if not action_id or action_id == "none":
            return

        ran = actions.run_action(
            action_id, reveal_first=self.cfg.get("ease_reveals_answer", True))
        if not ran:
            return

        if not repeat and self.cfg.get("rumble_on_answer") and self.hub:
            act = actions.ACTIONS_BY_ID.get(action_id)
            if act and act.haptic and act.group in ("Answering", "Card"):
                strength = float(self.cfg.get("rumble_strength", 0.35))
                freq = 260.0 if action_id == "again" else 340.0
                try:
                    self.hub.rumble(handle, freq, strength)
                except Exception:
                    pass

        if self.cfg.get("show_tooltip_on_action"):
            tooltip(actions.label_for(action_id), period=700)

    # -- used by the config dialog ----------------------------------------

    def add_watcher(self, cb) -> None:
        if not hasattr(self, "_watchers"):
            self._watchers = []
        self._watchers.append(cb)

    def remove_watcher(self, cb) -> None:
        try:
            self._watchers.remove(cb)
        except (AttributeError, ValueError):
            pass

    def status_text(self) -> str:
        if self.hub is None:
            return "Not started."
        if self.hub.last_error:
            return self.hub.last_error
        if not self.device_info:
            return (f"Backend: {self.hub.backend_name} — searching. "
                    "Pair your Joy-Cons in System Settings ▸ Bluetooth first.")
        parts = []
        for d in self.device_info:
            if not d.get("reports"):
                # Paired and enumerated, but the HID open was refused, so not a
                # single report has arrived. Say that instead of showing a
                # battery of "?" and letting it look like a flat controller.
                parts.append(
                    f"{d['name']} — connected but sending nothing. macOS is "
                    "probably holding it; enable “Exclusive control” in "
                    "Options, then Rescan.")
                continue
            bat = d.get("battery")
            bat_txt = {4: "full", 3: "good", 2: "medium", 1: "low", 0: "critical"}.get(
                bat, "?")
            if d.get("charging"):
                bat_txt += ", charging"
            line = f"{d['name']} — player {d['player']}, battery {bat_txt}"
            # Say which half of the handshake is still missing: in basic mode the
            # buttons come through rotated, and without vibration rumble is dead.
            missing = []
            if not d.get("full_mode"):
                missing.append("full report mode")
            if not d.get("vibration"):
                missing.append("rumble")
            line += (", still negotiating " + " and ".join(missing)) if missing else ", ready"
            parts.append(line)
        grip = settings.LAYOUT_LABELS.get(self.layout_name, self.layout_name)
        parts.append(f"Active grip: {grip}")
        return "\n".join(parts)

    def is_healthy(self) -> bool:
        """True when at least one controller is actually sending input."""
        return any(d.get("reports") for d in self.device_info)

    def diagnostics(self) -> str:
        """Everything worth pasting into a bug report."""
        import platform
        lines = [
            f"Anki-Con diagnostics",
            f"macOS {platform.mac_ver()[0]} / Python {platform.python_version()}",
        ]
        if self.hub:
            lines.append(f"backend: {self.hub.backend_name}")
            lines.append(f"stats: {self.hub.stats()}")
            if self.hub.last_error:
                lines.append(f"last error: {self.hub.last_error}")
        else:
            lines.append("hub: not started")
        lines.append(f"grip: {self.layout_name}")
        for d in self.device_info:
            lines.append(f"device: {d}")
        if not self.device_info:
            lines.append("device: none detected")
        lines.append("")
        lines.append("--- recent input (press a button to check its mapping) ---")
        lines.extend(self.recent_inputs[-30:] or ["  (nothing yet)"])
        lines.append("")
        lines.append("--- log ---")
        lines.extend(self.log_lines[-120:])
        return "\n".join(lines)
