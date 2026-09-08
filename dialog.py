"""Ankicon's mapping window: Tools ▸ Ankicon…"""

from __future__ import annotations

import os
from typing import Dict

from aqt import mw
from aqt.qt import *
from aqt.utils import getText, showWarning, tooltip

from . import profiles, settings
from .joycon import protocol as P
from .joycon_view import ColorSwatch, MapperPanel

_NO_PROFILE = "— unsaved —"


class OptionsDialog(QDialog):
    """The knobs that aren't part of a controller profile."""

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Ankicon Options")
        form = QFormLayout(self)

        self.chk_enabled = QCheckBox("Listen for Joy-Cons")
        self.chk_enabled.setChecked(bool(cfg["enabled"]))
        form.addRow(self.chk_enabled)

        self.chk_seize = QCheckBox(
            "Take exclusive control of the controller")
        self.chk_seize.setChecked(bool(cfg.get("seize_device", False)))
        self.chk_seize.setToolTip(
            "macOS has its own Joy-Con driver and can hold the controller so "
            "that Anki receives nothing. This takes it away from the system "
            "while Anki is running. Turn it on if buttons do nothing, then "
            "press Rescan.")
        form.addRow(self.chk_seize)

        self.chk_reveal = QCheckBox(
            "An ease button on the question side shows the answer instead")
        self.chk_reveal.setChecked(bool(cfg["ease_reveals_answer"]))
        form.addRow(self.chk_reveal)

        self.chk_rumble = QCheckBox("Rumble when a card is answered")
        self.chk_rumble.setChecked(bool(cfg["rumble_on_answer"]))
        form.addRow(self.chk_rumble)

        self.spin_rumble = QDoubleSpinBox()
        self.spin_rumble.setRange(0.0, 1.0)
        self.spin_rumble.setSingleStep(0.05)
        self.spin_rumble.setValue(float(cfg["rumble_strength"]))
        form.addRow("Rumble strength", self.spin_rumble)

        self.spin_dead = QDoubleSpinBox()
        self.spin_dead.setRange(0.2, 0.95)
        self.spin_dead.setSingleStep(0.05)
        self.spin_dead.setValue(float(cfg["stick_deadzone"]))
        form.addRow("Stick deadzone", self.spin_dead)

        self.chk_tooltip = QCheckBox("Show a tooltip naming each action fired")
        self.chk_tooltip.setChecked(bool(cfg["show_tooltip_on_action"]))
        form.addRow(self.chk_tooltip)

        self.chk_log = QCheckBox("Verbose logging to the console")
        self.chk_log.setChecked(bool(cfg["verbose_log"]))
        form.addRow(self.chk_log)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        qconnect(box.accepted, self.accept)
        qconnect(box.rejected, self.reject)
        form.addRow(box)

    def apply_to(self, cfg: dict) -> None:
        cfg["enabled"] = self.chk_enabled.isChecked()
        cfg["ease_reveals_answer"] = self.chk_reveal.isChecked()
        cfg["rumble_on_answer"] = self.chk_rumble.isChecked()
        cfg["rumble_strength"] = float(self.spin_rumble.value())
        cfg["stick_deadzone"] = float(self.spin_dead.value())
        cfg["seize_device"] = self.chk_seize.isChecked()
        cfg["show_tooltip_on_action"] = self.chk_tooltip.isChecked()
        cfg["verbose_log"] = self.chk_log.isChecked()


class DiagnosticsDialog(QDialog):
    """Live log and device state -- the first place to look when nothing works."""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Ankicon Diagnostics")
        self.resize(760, 520)

        v = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.view.setFont(font)
        v.addWidget(self.view)

        row = QHBoxLayout()
        copy = QPushButton("Copy to clipboard")
        qconnect(copy.clicked, self._copy)
        row.addWidget(copy)
        row.addStretch(1)
        close = QPushButton("Close")
        qconnect(close.clicked, self.accept)
        row.addWidget(close)
        v.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(600)
        qconnect(self._timer.timeout, self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self) -> None:
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.view.setPlainText(self.controller.diagnostics())
        if at_end:
            bar.setValue(bar.maximum())

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.controller.diagnostics())
        tooltip("Diagnostics copied.", parent=self)

    def done(self, code) -> None:
        self._timer.stop()
        super().done(code)


class AnkiconDialog(QDialog):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent or mw)
        self.controller = controller
        self.cfg = settings.get()
        self.editing_layout = settings.LAYOUT_DUAL
        self._loading_profiles = False
        self._panel_ready = False
        self._connected: set = set()

        self.setWindowTitle("Ankicon")
        self.setSizeGripEnabled(True)
        self._build()
        self._apply_initial_size()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(700)
        qconnect(self._status_timer.timeout, self._refresh_status)
        self._status_timer.start()

        self.controller.add_watcher(self._on_press)
        self._refresh_profiles()
        self._refresh_status(force=True)

    # -- construction ------------------------------------------------------

    def _apply_initial_size(self) -> None:
        """Open big enough to show both controllers and every callout.

        The panel is inside a scroll area, which has a tiny size hint of its
        own, so without this the window opens at its minimum and the diagram is
        a sliver. Clamped to the screen so it still fits a small laptop.
        """
        want = self.cfg.get("window_size")
        chrome_w, chrome_h = 70, 215      # status bar, toolbar, hint, buttons
        if not (isinstance(want, list) and len(want) == 2):
            want = [self.panel.minimumWidth() + chrome_w,
                    self.panel.minimumHeight() + chrome_h]

        w, h = int(want[0]), int(want[1])
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            # Never open larger than the screen; the scroll area copes on a
            # display too small for the full diagram.
            avail = screen.availableGeometry()
            w = min(w, max(480, avail.width() - 40))
            h = min(h, max(360, avail.height() - 60))
        self.resize(w, h)

    def _remember_size(self) -> None:
        # Window geometry is a UI preference, not part of the mapping, so it is
        # written straight through rather than waiting for Save.
        try:
            cfg = settings.get()
            cfg["window_size"] = [self.width(), self.height()]
            settings.save(cfg)
        except Exception:
            pass

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        outer.addLayout(self._status_bar())
        outer.addWidget(self._toolbar())

        self.panel = MapperPanel(self)
        qconnect(self.panel.colorRequested, self._pick_button_color)
        qconnect(self.panel.bindingChanged, self._on_binding_changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.panel)
        outer.addWidget(scroll, 1)

        hint = QLabel("Click a button on the diagram to jump to its dropdown, or "
                      "right-click it to change its colour. Press a button on a "
                      "live Joy-Con and it lights up here.")
        hint.setWordWrap(True)
        # Dim the normal text colour rather than naming one: "palette(mid)"
        # resolves to a dark grey that is unreadable on Anki's dark themes.
        pal = hint.palette()
        col = pal.color(QPalette.ColorRole.WindowText)
        col.setAlpha(165)
        pal.setColor(QPalette.ColorRole.WindowText, col)
        hint.setPalette(pal)
        outer.addWidget(hint)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                               | QDialogButtonBox.StandardButton.Cancel
                               | QDialogButtonBox.StandardButton.RestoreDefaults)
        opts = box.addButton("Options…", QDialogButtonBox.ButtonRole.ActionRole)
        qconnect(opts.clicked, self._open_options)
        qconnect(box.accepted, self._save)
        qconnect(box.rejected, self.reject)
        qconnect(box.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked,
                 self._restore_defaults)
        outer.addWidget(box)

    def _status_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding:6px 10px; border-radius:5px;")
        row.addWidget(self.status, 1)

        for text, slot in (("Rescan", self._rescan),
                           ("Test rumble", self._test_rumble),
                           ("Diagnostics…", self._open_diagnostics),
                           ("Pairing help", self._pairing_help)):
            btn = QPushButton(text)
            qconnect(btn.clicked, slot)
            row.addWidget(btn)
        return row

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("Grip:"))
        self.grip_buttons: Dict[str, QRadioButton] = {}
        group = QButtonGroup(self)
        for name in settings.LAYOUTS:
            rb = QRadioButton(settings.LAYOUT_LABELS[name])
            group.addButton(rb)
            row.addWidget(rb)
            self.grip_buttons[name] = rb
            qconnect(rb.toggled,
                     lambda on, n=name: self._on_grip_toggled(n, on))

        row.addSpacing(18)
        row.addWidget(QLabel("Shell:"))
        self.shell_swatches: Dict[str, ColorSwatch] = {}
        for side, label in ((P.SIDE_LEFT, "L"), (P.SIDE_RIGHT, "R")):
            row.addWidget(QLabel(label))
            sw = ColorSwatch()
            sw.setToolTip(f"Colour of the {label} shell")
            sw.set_color(settings.shell_color(self.cfg, side))
            qconnect(sw.clicked, lambda _=False, s=side: self._pick_shell_color(s))
            self.shell_swatches[side] = sw
            row.addWidget(sw)

        row.addStretch(1)

        row.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        qconnect(self.profile_combo.currentIndexChanged, self._on_profile_picked)
        row.addWidget(self.profile_combo)
        for text, slot in (("Save as…", self._profile_save_as),
                           ("Delete", self._profile_delete),
                           ("Import…", self._profile_import),
                           ("Export…", self._profile_export)):
            btn = QPushButton(text)
            qconnect(btn.clicked, slot)
            row.addWidget(btn)
        return bar

    # -- grip / layout -----------------------------------------------------

    def _commit_current(self) -> None:
        """Fold the on-screen dropdowns back into the in-memory config.

        Guarded on the panel having been populated: opening the window with a
        single Joy-Con already connected switches away from the dual map before
        anything is loaded, and committing then would save a screenful of
        freshly-constructed "nothing" combos over a real mapping.
        """
        if not self._panel_ready:
            return
        self.cfg.setdefault("layouts", {})[self.editing_layout] = \
            self.panel.collect_bindings()

    def _on_grip_toggled(self, name: str, on: bool) -> None:
        if not on or name == self.editing_layout:
            return
        self._commit_current()
        self.editing_layout = name
        if name in (settings.LAYOUT_SINGLE_H, settings.LAYOUT_SINGLE_V):
            self.cfg["orientation"] = name
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        self.panel.set_config(self.cfg, self.editing_layout, self._connected)
        self._panel_ready = True

    def _sync_grip_availability(self) -> None:
        """Both halves connected locks you to the dual map; one unlocks the
        orientation choice; nothing connected lets you edit any of the three."""
        both = {P.SIDE_LEFT, P.SIDE_RIGHT}.issubset(self._connected) \
            or P.SIDE_PRO in self._connected
        single = bool(self._connected) and not both

        enabled = {
            settings.LAYOUT_DUAL: not single,
            settings.LAYOUT_SINGLE_H: not both,
            settings.LAYOUT_SINGLE_V: not both,
        }
        want = self.editing_layout
        if both:
            want = settings.LAYOUT_DUAL
        elif single and want == settings.LAYOUT_DUAL:
            want = self.cfg.get("orientation", settings.LAYOUT_SINGLE_H)

        for name, rb in self.grip_buttons.items():
            rb.setEnabled(enabled[name])
            rb.blockSignals(True)
            rb.setChecked(name == want)
            rb.blockSignals(False)

        if want != self.editing_layout:
            self._commit_current()
            self.editing_layout = want
        self._refresh_panel()

    # -- colours -----------------------------------------------------------

    def _pick_button_color(self, binding_id: str) -> None:
        slot = self.panel.slots.get(binding_id)
        if slot is None:
            return
        current = QColor(settings.button_color(self.cfg, slot.side, slot.element.id))
        chosen = QColorDialog.getColor(
            current, self, f"Colour for {slot.element.label}")
        if not chosen.isValid():
            return
        self.cfg.setdefault("colors", settings.default_colors())
        self.cfg["colors"].setdefault("buttons", {})[binding_id] = chosen.name()
        self.panel.reload_colors()

    def _pick_shell_color(self, side: str) -> None:
        current = QColor(settings.shell_color(self.cfg, side))
        chosen = QColorDialog.getColor(current, self, "Shell colour")
        if not chosen.isValid():
            return
        key = "left" if side == P.SIDE_LEFT else "right"
        self.cfg.setdefault("colors", settings.default_colors())
        self.cfg["colors"].setdefault("shell", {})[key] = chosen.name()
        self.shell_swatches[side].set_color(chosen.name())
        self.panel.update()

    # -- profiles ----------------------------------------------------------

    def _refresh_profiles(self, select: str = None) -> None:
        self._loading_profiles = True
        try:
            self.profile_combo.clear()
            self.profile_combo.addItem(_NO_PROFILE, "")
            for name in profiles.names():
                self.profile_combo.addItem(name, name)
            want = select if select is not None else self.cfg.get("active_profile", "")
            idx = self.profile_combo.findData(want)
            self.profile_combo.setCurrentIndex(max(0, idx))
        finally:
            self._loading_profiles = False

    def _on_profile_picked(self, _index: int) -> None:
        if self._loading_profiles:
            return
        name = self.profile_combo.currentData()
        if not name:
            self.cfg["active_profile"] = ""
            return
        payload = profiles.load(name)
        if payload is None:
            showWarning(f"Could not read the profile “{name}”.", parent=self)
            return
        self.cfg = profiles.apply_payload(self.cfg, payload)
        self.cfg["active_profile"] = name
        for side, sw in self.shell_swatches.items():
            sw.set_color(settings.shell_color(self.cfg, side))
        self._sync_grip_availability()
        tooltip(f"Loaded profile “{name}”.", parent=self)

    def _profile_save_as(self) -> None:
        self._commit_current()
        default = self.cfg.get("active_profile") or "My Joy-Cons"
        name, ok = getText("Name for this controller profile:", parent=self,
                           default=default)
        name = (name or "").strip()
        if not ok or not name:
            return
        if profiles.exists(name) and QMessageBox.question(
                self, "Overwrite?",
                f"A profile called “{name}” already exists. Replace it?"
        ) != QMessageBox.StandardButton.Yes:
            return
        profiles.save(name, self.cfg)
        self.cfg["active_profile"] = name
        self._refresh_profiles(select=name)
        tooltip(f"Saved profile “{name}”.", parent=self)

    def _profile_delete(self) -> None:
        name = self.profile_combo.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Delete profile?",
                                f"Delete the profile “{name}”?") \
                != QMessageBox.StandardButton.Yes:
            return
        profiles.delete(name)
        self.cfg["active_profile"] = ""
        self._refresh_profiles(select="")

    def _profile_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a controller profile", "",
            "Ankicon profiles (*.json);;All files (*)")
        if not path:
            return
        payload = profiles.import_from(path)
        if payload is None:
            showWarning("That file isn't an Ankicon profile.", parent=self)
            return
        self._refresh_profiles(select=payload["name"])
        self.profile_combo.setCurrentIndex(
            self.profile_combo.findData(payload["name"]))

    def _profile_export(self) -> None:
        self._commit_current()
        name = self.cfg.get("active_profile") or "ankicon-profile"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export controller profile",
            os.path.expanduser(f"~/{name}{profiles.SUFFIX}"),
            "Ankicon profiles (*.json)")
        if not path:
            return
        profiles.export_to(path, self.cfg, name)
        tooltip("Profile exported.", parent=self)

    # -- live hardware -----------------------------------------------------

    def _on_press(self, button_id: str, pressed: bool) -> None:
        if pressed:
            self.panel.flash(button_id)

    def _refresh_status(self, force: bool = False) -> None:
        self.controller.poll_devices()
        info = self.controller.device_info or []
        connected = {d.get("side") for d in info if d.get("side")}
        changed = connected != self._connected
        self._connected = connected

        self.status.setText(self.controller.status_text())
        healthy = bool(info) and self.controller.is_healthy()
        self.status.setStyleSheet(
            "padding:6px 10px; border-radius:5px;"
            + ("background:#1f7a3f; color:white;" if healthy
               else "background:#8a6d1f; color:white;"))

        if changed or force:
            self._sync_grip_availability()

    def _open_diagnostics(self) -> None:
        DiagnosticsDialog(self.controller, self).exec()

    def _rescan(self) -> None:
        self.controller.restart()
        tooltip("Rescanning for Joy-Cons…", parent=self)

    def _test_rumble(self) -> None:
        if not self.controller.hub or not self.controller.device_info:
            tooltip("No controller connected.", parent=self)
            return
        if not self.controller.is_healthy():
            tooltip("The controller isn't sending input yet — see Diagnostics.",
                    parent=self)
            return
        self.controller.hub.rumble_all(
            340.0, float(self.cfg.get("rumble_strength", 0.35)))

    def _pairing_help(self) -> None:
        QMessageBox.information(
            self, "Pairing a Joy-Con",
            "1. Detach the Joy-Con from the Switch (or from its grip).\n"
            "2. Hold the small round SYNC button on the flat inner rail for "
            "about three seconds, until the four player lights run back and "
            "forth.\n"
            "3. On your Mac open System Settings ▸ Bluetooth and connect "
            "“Joy-Con (L)” or “Joy-Con (R)”.\n"
            "4. Come back here and press Rescan. Repeat for the second "
            "Joy-Con — they connect independently and can be used together.\n\n"
            "If macOS asks for Input Monitoring permission, grant it to Anki "
            "in System Settings ▸ Privacy & Security, then restart Anki.")

    # -- save --------------------------------------------------------------

    def _on_binding_changed(self) -> None:
        self.panel.update()

    def _open_options(self) -> None:
        dlg = OptionsDialog(self.cfg, self)
        if dlg.exec():
            dlg.apply_to(self.cfg)

    def _restore_defaults(self) -> None:
        settings.reset_layout(self.cfg, self.editing_layout)
        self.panel.reload_bindings()
        self.panel.update()
        tooltip(f"{settings.LAYOUT_LABELS[self.editing_layout]} mapping reset — "
                "press Save to keep it.", parent=self)

    def _save(self) -> None:
        self._commit_current()
        settings.save(self.cfg)
        self.controller.reload_config()
        self.accept()

    # -- teardown ----------------------------------------------------------

    def reject(self) -> None:
        self._teardown()
        super().reject()

    def accept(self) -> None:
        self._teardown()
        super().accept()

    def _teardown(self) -> None:
        self._remember_size()
        self._status_timer.stop()
        self.controller.remove_watcher(self._on_press)


# Kept so an older import path still resolves.
JoyConDialog = AnkiconDialog
