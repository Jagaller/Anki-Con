"""Anki-Con's mapping window: Tools ▸ Anki-Con…"""

from __future__ import annotations

import os
from typing import Dict

from aqt import gui_hooks, mw
from aqt.qt import *
from aqt.utils import getText, showWarning, tooltip

from . import profiles, settings, style
from .joycon import protocol as P
from .joycon_view import ColorSwatch, MapperPanel, StatusBadge

_NO_PROFILE = "— unsaved —"


class OptionsDialog(QDialog):
    """The knobs that aren't part of a controller profile."""

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Anki-Con Options")
        self.setMinimumWidth(400)
        style.apply(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(6)

        self.chk_enabled = self._switch(cfg["enabled"])
        self.chk_seize = self._switch(cfg.get("seize_device", False))
        self.chk_leds = self._switch(cfg.get("player_leds", True))
        self.spin_dead = self._spin(0.2, 0.95, cfg["stick_deadzone"])
        self._section(outer, "Controller", (
            ("Enable Joy-Cons", self.chk_enabled,
             "Lets Anki-Con respond to your Joy-Cons. When this is off, their "
             "buttons do nothing in Anki."),
            ("Exclusive control", self.chk_seize,
             "Stops macOS from using the Joy-Con while Anki has it. Turn this "
             "on if your Joy-Con connects but its buttons do nothing."),
            ("Player LED", self.chk_leds,
             "Lights the player number on each connected Joy-Con. Turn this "
             "off to keep the lights dark."),
            ("Stick deadzone", self.spin_dead,
             "How far you push the stick before it counts. Raise it if the "
             "stick triggers by itself; lower it for a lighter touch.")))

        self.chk_reveal = self._switch(cfg["ease_reveals_answer"])
        self.chk_rumble = self._switch(cfg["rumble_on_answer"])
        self.spin_rumble = self._spin(0.0, 1.0, cfg["rumble_strength"])
        self._section(outer, "Reviewing", (
            ("Reveal answer first", self.chk_reveal,
             "If the answer is still hidden, pressing Again, Hard, Good or "
             "Easy shows it. When this is off, the press is ignored."),
            ("Rumble", self.chk_rumble,
             "Vibrates the Joy-Con when you answer a card or use a card "
             "action, such as Mark or Bury."),
            ("Rumble strength", self.spin_rumble,
             "How strongly the Joy-Con vibrates, from 0 (none) to 1 "
             "(strongest).")))

        self.chk_tooltip = self._switch(cfg["show_tooltip_on_action"])
        self.chk_log = self._switch(cfg["verbose_log"])
        self._section(outer, "Debugging", (
            ("Action tooltips", self.chk_tooltip,
             "Briefly shows the name of each action when you use it, so you "
             "can check what a button does."),
            ("Verbose logging", self.chk_log,
             "Prints controller activity to the console. Only useful for "
             "tracking down a problem.")))

        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(style.button("Cancel", self.reject))
        ok = style.button("OK", self.accept, "primary")
        ok.setDefault(True)
        row.addWidget(ok)
        outer.addLayout(row)

    @staticmethod
    def _switch(on) -> style.Switch:
        w = style.Switch()
        w.setChecked(bool(on))
        return w

    @staticmethod
    def _spin(low: float, high: float, value) -> style.Spin:
        w = style.Spin()
        w.setRange(low, high)
        w.setSingleStep(0.05)
        w.setValue(float(value))
        return w

    @staticmethod
    def _section(outer: QVBoxLayout, title: str, rows) -> None:
        """A titled card with one setting per line."""
        if outer.count():
            outer.addSpacing(10)
        caption = style.label(title, "caption")
        caption.setContentsMargins(6, 0, 0, 0)
        outer.addWidget(caption)
        card = style.frame("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 2, 14, 2)
        v.setSpacing(0)
        for n, (text, control, about) in enumerate(rows):
            if n:
                v.addWidget(style.rule())
            line = QHBoxLayout()
            line.setContentsMargins(0, 8, 0, 8)
            line.setSpacing(7)
            line.addWidget(style.RowLabel(text, control))
            line.addWidget(style.HelpButton(text, about))
            line.addStretch(1)
            line.addWidget(control)
            v.addLayout(line)
        outer.addWidget(card)

    def apply_to(self, cfg: dict) -> None:
        cfg["enabled"] = self.chk_enabled.isChecked()
        cfg["ease_reveals_answer"] = self.chk_reveal.isChecked()
        cfg["rumble_on_answer"] = self.chk_rumble.isChecked()
        cfg["rumble_strength"] = float(self.spin_rumble.value())
        cfg["player_leds"] = self.chk_leds.isChecked()
        cfg["stick_deadzone"] = float(self.spin_dead.value())
        cfg["seize_device"] = self.chk_seize.isChecked()
        cfg["show_tooltip_on_action"] = self.chk_tooltip.isChecked()
        cfg["verbose_log"] = self.chk_log.isChecked()


class DiagnosticsDialog(QDialog):
    """Live log and device state -- the first place to look when nothing works."""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Anki-Con Diagnostics")
        self.resize(760, 520)
        style.apply(self)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setProperty("kind", "code")
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.view.setFont(font)
        v.addWidget(self.view)

        row = QHBoxLayout()
        copy = style.button("Copy to clipboard", self._copy, "primary")
        copy.setDefault(True)
        row.addWidget(copy)
        row.addStretch(1)
        row.addWidget(style.button("Close", self.accept))
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

        self.setWindowTitle("Anki-Con")
        self.setSizeGripEnabled(True)
        style.apply(self)
        self._build()
        self._apply_initial_size()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(700)
        qconnect(self._status_timer.timeout, self._refresh_status)
        self._status_timer.start()

        gui_hooks.theme_did_change.append(self._on_theme_changed)
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
        chrome_w, chrome_h = 70, 235      # header, toolbar, footer, margins
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

    def _on_theme_changed(self) -> None:
        self.setStyleSheet(style.sheet())
        self.update()

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
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        outer.addLayout(self._status_bar())
        outer.addWidget(self._toolbar())

        self.panel = MapperPanel(self)
        qconnect(self.panel.colorRequested, self._pick_button_color)
        qconnect(self.panel.bindingChanged, self._on_binding_changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setProperty("kind", "clear")
        scroll.setWidget(self.panel)
        scroll.viewport().setAutoFillBackground(False)
        self.panel.setAutoFillBackground(False)

        card = style.frame("card")
        inside = QVBoxLayout(card)
        inside.setContentsMargins(8, 8, 8, 8)
        inside.addWidget(scroll)
        outer.addWidget(card, 1)
        outer.addLayout(self._footer())

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(style.button("Restore Defaults", self._restore_defaults))
        row.addWidget(style.button("Options…", self._open_options))

        hint = style.label("Click a button to edit it, right-click to recolour "
                           "it, or press it on your Joy-Con.", "muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        row.addWidget(hint, 1)

        row.addWidget(style.button("Cancel", self.reject))
        save = style.button("Save", self._save, "primary")
        save.setDefault(True)
        row.addWidget(save)
        return row

    def _status_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status = StatusBadge()
        row.addWidget(self.status)
        row.addStretch(1)

        for text, slot in (("Rescan", self._rescan),
                           ("Test rumble", self._test_rumble),
                           ("Diagnostics…", self._open_diagnostics),
                           ("Pairing help", self._pairing_help)):
            row.addWidget(style.button(text, slot))
        return row

    def _toolbar(self) -> QWidget:
        bar = style.frame("card")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(8)

        row.addWidget(style.label("Grip", "caption"))
        self.grip_buttons: Dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        well = style.frame("well")
        segments = QHBoxLayout(well)
        segments.setContentsMargins(3, 3, 3, 3)
        segments.setSpacing(2)
        row.addWidget(well)
        for name in settings.LAYOUTS:
            rb = style.button(settings.LAYOUT_LABELS[name], kind="segment")
            rb.setCheckable(True)
            group.addButton(rb)
            segments.addWidget(rb)
            self.grip_buttons[name] = rb
            qconnect(rb.toggled,
                     lambda on, n=name: self._on_grip_toggled(n, on))

        row.addSpacing(6)
        row.addWidget(style.rule(vertical=True))
        row.addSpacing(6)
        row.addWidget(style.label("Shell", "caption"))
        self.shell_swatches: Dict[str, ColorSwatch] = {}
        for side, label in ((P.SIDE_LEFT, "L"), (P.SIDE_RIGHT, "R")):
            row.addWidget(style.label(label, "muted"))
            sw = ColorSwatch()
            sw.setToolTip(f"Colour of the {label} shell")
            sw.set_color(settings.shell_color(self.cfg, side))
            qconnect(sw.clicked, lambda _=False, s=side: self._pick_shell_color(s))
            self.shell_swatches[side] = sw
            row.addWidget(sw)

        row.addSpacing(6)
        row.addWidget(style.rule(vertical=True))
        row.addSpacing(6)
        row.addWidget(style.label("Profile", "caption"))
        self.profile_combo = style.Combo()
        self.profile_combo.setMinimumWidth(130)
        self.profile_combo.setFixedHeight(30)
        qconnect(self.profile_combo.currentIndexChanged, self._on_profile_picked)
        row.addWidget(self.profile_combo, 1)
        for text, slot in (("Save as…", self._profile_save_as),
                           ("Delete", self._profile_delete),
                           ("Import…", self._profile_import),
                           ("Export…", self._profile_export)):
            row.addWidget(style.button(text, slot))
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
            "Anki-Con profiles (*.json);;All files (*)")
        if not path:
            return
        payload = profiles.import_from(path)
        if payload is None:
            showWarning("That file isn't an Anki-Con profile.", parent=self)
            return
        # Selecting it here is silent, so load it explicitly: choosing the same
        # entry again would not count as a change.
        self._refresh_profiles(select=payload["name"])
        self._on_profile_picked(self.profile_combo.currentIndex())

    def _profile_export(self) -> None:
        self._commit_current()
        name = self.cfg.get("active_profile") or "anki-con-profile"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export controller profile",
            os.path.expanduser(f"~/{name}{profiles.SUFFIX}"),
            "Anki-Con profiles (*.json)")
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

        if info and self.controller.is_healthy():
            state = StatusBadge.OK
        else:
            state = StatusBadge.WARN if info else StatusBadge.OFF
        self.status.set_status(state, connected)
        self.status.setToolTip(self.controller.status_text())

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
        gui_hooks.theme_did_change.remove(self._on_theme_changed)


# Kept so an older import path still resolves.
JoyConDialog = AnkiconDialog
