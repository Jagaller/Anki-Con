"""
macOS HID backend.

Opens an IOHIDManager, matches on Nintendo's vendor id, and pumps input reports
on a CFRunLoop. Doing this through ctypes rather than shipping a compiled helper
matters here, because Anki add-ons have to be pure Python -- there is no place
to put a .dylib that every user's Anki build would load.

Everything in this module runs on its own thread; nothing here touches Qt.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import queue
import threading
import time
from ctypes import CFUNCTYPE, POINTER, byref, c_bool, c_double, c_int32, c_uint8, c_uint32, c_void_p

from . import protocol as P

CFIndex = ctypes.c_long
IOReturn = c_uint32

_CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_IOKIT_PATH = "/System/Library/Frameworks/IOKit.framework/IOKit"

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type = 3
kIOHIDReportTypeOutput = 1
kIOHIDOptionsTypeNone = 0
kIOHIDOptionsTypeSeizeDevice = 1

MAX_REPORT = 512  # 0x31 NFC/IR reports can reach 362 bytes

# IOReturn codes worth naming. Without these every failure reads as a bare hex
# number, which is useless when the whole question is *why* nothing arrives.
_IORETURN = {
    0x00000000: "success",
    0xE00002BC: "kIOReturnError",
    0xE00002BD: "kIOReturnNoMemory",
    0xE00002BE: "kIOReturnNoResources",
    0xE00002C0: "kIOReturnNoDevice",
    0xE00002C1: "kIOReturnNotPrivileged",
    0xE00002C2: "kIOReturnBadArgument",
    0xE00002C3: "kIOReturnLockedRead",
    0xE00002C4: "kIOReturnLockedWrite",
    0xE00002C5: "kIOReturnExclusiveAccess (another process holds the device)",
    0xE00002C7: "kIOReturnUnsupported",
    0xE00002C9: "kIOReturnInternalError",
    0xE00002CA: "kIOReturnIOError",
    0xE00002CD: "kIOReturnNotOpen",
    0xE00002CE: "kIOReturnNotReadable",
    0xE00002CF: "kIOReturnNotWritable",
    0xE00002D6: "kIOReturnTimeout",
    0xE00002E2: "kIOReturnNotPermitted (grant Input Monitoring to Anki)",
    0xE00002EF: "kIOReturnOffline",
}


def ioreturn(code: int) -> str:
    code &= 0xFFFFFFFF
    name = _IORETURN.get(code)
    return f"0x{code:08X} {name}" if name else f"0x{code:08X}"


def available() -> bool:
    import sys
    return sys.platform == "darwin"


class _CF:
    """Lazily bound CoreFoundation + IOKit entry points."""

    def __init__(self) -> None:
        self.cf = ctypes.cdll.LoadLibrary(_CF_PATH)
        self.io = ctypes.cdll.LoadLibrary(_IOKIT_PATH)
        cf, io = self.cf, self.io

        cf.CFRelease.argtypes = [c_void_p]
        cf.CFRetain.argtypes = [c_void_p]
        cf.CFRetain.restype = c_void_p

        cf.CFStringCreateWithCString.restype = c_void_p
        cf.CFStringCreateWithCString.argtypes = [c_void_p, ctypes.c_char_p, c_uint32]

        cf.CFStringGetCString.restype = c_bool
        cf.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, CFIndex, c_uint32]

        cf.CFNumberCreate.restype = c_void_p
        cf.CFNumberCreate.argtypes = [c_void_p, CFIndex, c_void_p]
        cf.CFNumberGetValue.restype = c_bool
        cf.CFNumberGetValue.argtypes = [c_void_p, CFIndex, c_void_p]

        cf.CFDictionaryCreateMutable.restype = c_void_p
        cf.CFDictionaryCreateMutable.argtypes = [c_void_p, CFIndex, c_void_p, c_void_p]
        cf.CFDictionarySetValue.argtypes = [c_void_p, c_void_p, c_void_p]

        cf.CFArrayCreateMutable.restype = c_void_p
        cf.CFArrayCreateMutable.argtypes = [c_void_p, CFIndex, c_void_p]
        cf.CFArrayAppendValue.argtypes = [c_void_p, c_void_p]

        cf.CFRunLoopGetCurrent.restype = c_void_p
        cf.CFRunLoopRunInMode.restype = c_int32
        cf.CFRunLoopRunInMode.argtypes = [c_void_p, c_double, c_bool]

        self.dict_key_cb = c_void_p(
            ctypes.addressof(c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")))
        self.dict_val_cb = c_void_p(
            ctypes.addressof(c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
        self.array_cb = c_void_p(
            ctypes.addressof(c_void_p.in_dll(cf, "kCFTypeArrayCallBacks")))
        self.default_mode = c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")

        io.IOHIDManagerCreate.restype = c_void_p
        io.IOHIDManagerCreate.argtypes = [c_void_p, c_uint32]
        io.IOHIDManagerSetDeviceMatchingMultiple.argtypes = [c_void_p, c_void_p]
        io.IOHIDManagerRegisterDeviceMatchingCallback.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDManagerRegisterDeviceRemovalCallback.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDManagerScheduleWithRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDManagerUnscheduleFromRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDManagerOpen.restype = IOReturn
        io.IOHIDManagerOpen.argtypes = [c_void_p, c_uint32]
        io.IOHIDManagerClose.restype = IOReturn
        io.IOHIDManagerClose.argtypes = [c_void_p, c_uint32]

        io.IOHIDDeviceOpen.restype = IOReturn
        io.IOHIDDeviceOpen.argtypes = [c_void_p, c_uint32]
        io.IOHIDDeviceClose.restype = IOReturn
        io.IOHIDDeviceClose.argtypes = [c_void_p, c_uint32]
        io.IOHIDDeviceGetProperty.restype = c_void_p
        io.IOHIDDeviceGetProperty.argtypes = [c_void_p, c_void_p]
        io.IOHIDDeviceScheduleWithRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDDeviceUnscheduleFromRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
        io.IOHIDDeviceRegisterInputReportCallback.argtypes = [
            c_void_p, POINTER(c_uint8), CFIndex, c_void_p, c_void_p]
        io.IOHIDDeviceSetReport.restype = IOReturn
        io.IOHIDDeviceSetReport.argtypes = [c_void_p, c_uint32, CFIndex,
                                            POINTER(c_uint8), CFIndex]

        self._strings: dict = {}

    def string(self, s: str) -> c_void_p:
        if s not in self._strings:
            self._strings[s] = self.cf.CFStringCreateWithCString(
                None, s.encode("utf-8"), kCFStringEncodingUTF8)
        return self._strings[s]

    def number(self, n: int) -> c_void_p:
        v = c_int32(n)
        return self.cf.CFNumberCreate(None, kCFNumberSInt32Type, byref(v))

    def device_int(self, dev, key: str):
        ref = self.io.IOHIDDeviceGetProperty(dev, self.string(key))
        if not ref:
            return None
        v = c_int32(0)
        if self.cf.CFNumberGetValue(ref, kCFNumberSInt32Type, byref(v)):
            return v.value
        return None

    def device_str(self, dev, key: str):
        ref = self.io.IOHIDDeviceGetProperty(dev, self.string(key))
        if not ref:
            return None
        buf = ctypes.create_string_buffer(256)
        if self.cf.CFStringGetCString(ref, buf, 256, kCFStringEncodingUTF8):
            return buf.value.decode("utf-8", "replace")
        return None


DeviceMatchingCallback = CFUNCTYPE(None, c_void_p, IOReturn, c_void_p, c_void_p)
InputReportCallback = CFUNCTYPE(None, c_void_p, IOReturn, c_void_p,
                                c_uint32, c_uint32, POINTER(c_uint8), CFIndex)


class MacHIDBackend(threading.Thread):
    """
    Discovers Nintendo controllers and pumps their input reports.

    on_attach(handle, product_id, serial)  -> called from this thread
    on_report(handle, bytes)
    on_detach(handle)
    """

    daemon = True

    def __init__(self, on_attach, on_report, on_detach, log=print,
                 seize: bool = False) -> None:
        super().__init__(name="JoyConHID")
        self.on_attach = on_attach
        self.on_report = on_report
        self.on_detach = on_detach
        self.log = log
        # Seizing takes the controller away from macOS's own Joy-Con driver.
        # Off by default; we fall back to it automatically if a plain open is
        # refused, which is what happens when the system driver got there first.
        self.seize = seize
        self.reports_in = 0
        self.reports_out = 0
        self.send_errors = 0

        self._stop = threading.Event()
        self._outbox: "queue.Queue[tuple]" = queue.Queue()
        self._pending: list = []      # (due, handle, payload) not yet due
        self._devices: dict = {}      # handle(int) -> record
        self._cf: _CF = None          # type: ignore
        self._manager = None
        self._keepalive: list = []    # ctypes callbacks must outlive the loop

    # -- public, callable from any thread ---------------------------------

    def send(self, handle: int, payload: bytes, delay: float = 0.0) -> None:
        """Queue an output report, optionally `delay` seconds from now.

        Joy-Cons handle one subcommand at a time and drop anything that lands
        while they are busy, so the handshake has to be paced rather than
        blasted; rumble likewise needs the motor left running before the stop
        packet arrives.
        """
        self._outbox.put((time.monotonic() + delay, handle, bytes(payload)))

    def stop(self) -> None:
        self._stop.set()

    # -- thread body -------------------------------------------------------

    def run(self) -> None:
        try:
            self._cf = _CF()
        except Exception as exc:  # pragma: no cover - only on broken systems
            self.log(f"could not load IOKit: {exc}")
            return

        cf, io = self._cf.cf, self._cf.io
        self._manager = io.IOHIDManagerCreate(None, 0)
        if not self._manager:
            self.log("IOHIDManagerCreate failed")
            return

        io.IOHIDManagerSetDeviceMatchingMultiple(self._manager, self._matching())

        cb_match = DeviceMatchingCallback(self._matched)
        cb_remove = DeviceMatchingCallback(self._removed)
        self._keepalive += [cb_match, cb_remove]
        io.IOHIDManagerRegisterDeviceMatchingCallback(self._manager, cb_match, None)
        io.IOHIDManagerRegisterDeviceRemovalCallback(self._manager, cb_remove, None)

        runloop = cf.CFRunLoopGetCurrent()
        io.IOHIDManagerScheduleWithRunLoop(self._manager, runloop, self._cf.default_mode)

        rc = io.IOHIDManagerOpen(self._manager, kIOHIDOptionsTypeNone)
        if rc != 0:
            self.log(f"IOHIDManagerOpen failed: {ioreturn(rc)}")
        else:
            self.log("HID manager open, watching for Nintendo controllers")

        try:
            while not self._stop.is_set():
                self._flush_outbox()
                # A short bounded spin keeps stop() instant without needing a
                # cross-thread CFRunLoopStop.
                cf.CFRunLoopRunInMode(self._cf.default_mode, 0.02, True)
        finally:
            self._shutdown(runloop)

    def _shutdown(self, runloop) -> None:
        io = self._cf.io
        for handle, rec in list(self._devices.items()):
            try:
                io.IOHIDDeviceUnscheduleFromRunLoop(rec["dev"], runloop,
                                                    self._cf.default_mode)
                io.IOHIDDeviceClose(rec["dev"], kIOHIDOptionsTypeNone)
            except Exception:
                pass
            try:
                self.on_detach(handle)
            except Exception:
                pass
        self._devices.clear()
        try:
            io.IOHIDManagerUnscheduleFromRunLoop(self._manager, runloop,
                                                 self._cf.default_mode)
            io.IOHIDManagerClose(self._manager, kIOHIDOptionsTypeNone)
        except Exception:
            pass

    # -- helpers -----------------------------------------------------------

    def _matching(self):
        cf = self._cf.cf
        arr = cf.CFArrayCreateMutable(None, 0, self._cf.array_cb)
        for pid in P.PRODUCTS:
            d = cf.CFDictionaryCreateMutable(None, 0, self._cf.dict_key_cb,
                                             self._cf.dict_val_cb)
            cf.CFDictionarySetValue(d, self._cf.string("VendorID"),
                                    self._cf.number(P.VENDOR_NINTENDO))
            cf.CFDictionarySetValue(d, self._cf.string("ProductID"),
                                    self._cf.number(pid))
            cf.CFArrayAppendValue(arr, d)
            cf.CFRelease(d)
        return arr

    def _flush_outbox(self) -> None:
        io = self._cf.io
        while True:
            try:
                self._pending.append(self._outbox.get_nowait())
            except queue.Empty:
                break

        if not self._pending:
            return
        now = time.monotonic()
        due = [e for e in self._pending if e[0] <= now]
        self._pending = [e for e in self._pending if e[0] > now]

        for _at, handle, payload in due:
            rec = self._devices.get(handle)
            if not rec:
                continue
            buf = (c_uint8 * len(payload)).from_buffer_copy(payload)
            try:
                rc = io.IOHIDDeviceSetReport(rec["dev"], kIOHIDReportTypeOutput,
                                             payload[0], buf, len(payload))
            except Exception as exc:
                self.send_errors += 1
                self.log(f"SetReport raised: {exc}")
                continue

            self.reports_out += 1
            if rc != 0:
                # Rumble and the full-mode handshake both ride on this, so a
                # silent failure here looks like "the controller is ignoring me".
                self.send_errors += 1
                if self.send_errors <= 5:
                    self.log(f"SetReport(0x{payload[0]:02X}) failed: {ioreturn(rc)}")

    # -- IOKit callbacks ---------------------------------------------------

    def _matched(self, context, result, sender, device) -> None:
        try:
            io = self._cf.io
            handle = int(ctypes.cast(device, c_void_p).value or 0)
            if handle in self._devices:
                return

            pid = self._cf.device_int(device, "ProductID")
            if pid not in P.PRODUCTS:
                return

            first = kIOHIDOptionsTypeSeizeDevice if self.seize else kIOHIDOptionsTypeNone
            rc = io.IOHIDDeviceOpen(device, first)
            if rc != 0 and not self.seize:
                # Almost always macOS's built-in Joy-Con driver holding it.
                self.log(f"IOHIDDeviceOpen: {ioreturn(rc)} - retrying with seize")
                rc = io.IOHIDDeviceOpen(device, kIOHIDOptionsTypeSeizeDevice)
                if rc == 0:
                    self.log("opened with seize (taken from the system driver)")
            if rc != 0:
                self.log(f"IOHIDDeviceOpen FAILED: {ioreturn(rc)} - "
                         "no input will arrive from this controller")
            else:
                self.log("device opened" + (" (seized)" if self.seize else ""))

            buf = (c_uint8 * MAX_REPORT)()
            cb = InputReportCallback(self._make_report_cb(handle))
            self._keepalive.append(cb)

            io.IOHIDDeviceRegisterInputReportCallback(device, buf, MAX_REPORT, cb, None)
            io.IOHIDDeviceScheduleWithRunLoop(device, self._cf.cf.CFRunLoopGetCurrent(),
                                              self._cf.default_mode)

            # keep the ctypes objects referenced or the runloop reads freed memory
            self._devices[handle] = {"dev": device, "buf": buf, "cb": cb, "pid": pid}
            serial = self._cf.device_str(device, "SerialNumber") or f"{handle:x}"
            self.on_attach(handle, pid, serial)
        except Exception as exc:
            self.log(f"attach error: {exc}")

    def _removed(self, context, result, sender, device) -> None:
        handle = int(ctypes.cast(device, c_void_p).value or 0)
        rec = self._devices.pop(handle, None)
        if rec is None:
            return
        try:
            self.on_detach(handle)
        except Exception as exc:
            self.log(f"detach error: {exc}")

    def _make_report_cb(self, handle: int):
        def _cb(context, result, sender, rtype, report_id, report, length):
            try:
                n = int(length)
                if n <= 0:
                    return
                data = bytes(bytearray(report[:n]))
                self.reports_in += 1
                if self.reports_in <= 3:
                    self.log(f"input report #{self.reports_in}: id=0x{data[0]:02X} "
                             f"len={n} {data[:12].hex(' ')}")
                # IOKit hands numbered reports back with the id already in
                # place, but be tolerant of the other convention.
                if report_id and (not data or data[0] != report_id):
                    data = bytes([report_id]) + data
                self.on_report(handle, data)
            except Exception:
                pass
        return _cb
