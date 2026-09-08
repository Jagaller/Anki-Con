"""
Optional cross-platform backend.

macOS gets the native IOKit path in backend_macos.py. Windows and Linux fall
back to this one, which needs the `hid` module (pip install hidapi) importable
from Anki's Python. It is deliberately best-effort: the add-on is fully usable
without it, and the rest of the code does not care which backend it got.

Linux users also need a udev rule granting access to vendor 057e, otherwise
hidapi will open the device read-only or not at all.
"""

from __future__ import annotations

import threading
import time

from . import protocol as P


def available() -> bool:
    try:
        import hid  # noqa: F401
        return True
    except Exception:
        return False


class HidApiBackend(threading.Thread):
    """Polls every matching Nintendo device on one worker thread."""

    daemon = True
    RESCAN_SECONDS = 2.0

    def __init__(self, on_attach, on_report, on_detach, log=print) -> None:
        super().__init__(name="JoyConHID")
        self.on_attach = on_attach
        self.on_report = on_report
        self.on_detach = on_detach
        self.log = log
        self._stop = threading.Event()
        self._open: dict = {}       # path(bytes) -> {"dev":..., "handle":int}
        self._lock = threading.Lock()
        self._next_handle = 1

    def send(self, handle: int, payload: bytes, delay: float = 0.0) -> None:
        if delay > 0:
            threading.Timer(delay, self.send, (handle, payload)).start()
            return
        with self._lock:
            for rec in self._open.values():
                if rec["handle"] == handle:
                    try:
                        rec["dev"].write(payload)
                    except Exception as exc:
                        self.log(f"write failed: {exc}")
                    return

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        import hid

        last_scan = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_scan > self.RESCAN_SECONDS:
                last_scan = now
                self._scan(hid)

            got_data = False
            with self._lock:
                records = list(self._open.items())
            for path, rec in records:
                try:
                    data = rec["dev"].read(P.__dict__.get("MAX_REPORT", 64) or 64,
                                           timeout_ms=0)
                except Exception:
                    self._drop(path)
                    continue
                if data:
                    got_data = True
                    self.on_report(rec["handle"], bytes(data))
            if not got_data:
                time.sleep(0.004)

        for path in list(self._open):
            self._drop(path)

    def _scan(self, hid) -> None:
        try:
            found = hid.enumerate(P.VENDOR_NINTENDO, 0)
        except Exception:
            return
        for info in found:
            pid = info.get("product_id")
            path = info.get("path")
            if pid not in P.PRODUCTS or path in self._open:
                continue
            try:
                dev = hid.device()
                dev.open_path(path)
                dev.set_nonblocking(True)
            except Exception as exc:
                self.log(f"could not open {pid:#06x}: {exc}")
                continue
            handle = self._next_handle
            self._next_handle += 1
            with self._lock:
                self._open[path] = {"dev": dev, "handle": handle}
            self.on_attach(handle, pid, info.get("serial_number") or str(handle))

    def _drop(self, path) -> None:
        with self._lock:
            rec = self._open.pop(path, None)
        if not rec:
            return
        try:
            rec["dev"].close()
        except Exception:
            pass
        self.on_detach(rec["handle"])
