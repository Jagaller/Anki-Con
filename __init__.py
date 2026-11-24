"""
Anki-Con
========

Review with one or two Nintendo Joy-Cons. Every reviewer command -- Show
Answer, Again/Hard/Good/Easy, and everything in the More menu -- can be mapped
to any button from a diagram of the controllers themselves.

macOS talks to the controllers through IOKit directly, driven from ctypes so
the add-on stays pure Python with no build step. Windows and Linux fall back to
hidapi if it is installed.
"""

from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.qt import *

from .controller import JoyConController
from .dialog import AnkiconDialog

_controller: JoyConController = None  # type: ignore
_dialog: AnkiconDialog = None  # type: ignore


def get_controller() -> JoyConController:
    global _controller
    if _controller is None:
        _controller = JoyConController()
    return _controller


def open_dialog() -> None:
    # Held in a module global: the window is modeless, so without a reference
    # it can be collected out from under the user mid-mapping.
    global _dialog
    if _dialog is not None:
        try:
            _dialog.close()
        except Exception:
            pass
    _dialog = AnkiconDialog(get_controller(), mw)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()


def _on_profile_open() -> None:
    get_controller().start()


def _on_profile_close() -> None:
    if _controller is not None:
        _controller.stop()


def _on_quit() -> None:
    if _controller is not None:
        _controller.stop()


def _install_menu() -> None:
    action = QAction("Anki-Con…", mw)
    qconnect(action.triggered, open_dialog)
    mw.form.menuTools.addAction(action)


_install_menu()
mw.addonManager.setConfigAction(__name__, open_dialog)

gui_hooks.profile_did_open.append(_on_profile_open)
gui_hooks.profile_will_close.append(_on_profile_close)
qconnect(mw.app.aboutToQuit, _on_quit)
