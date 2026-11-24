"""
The look of Anki-Con's windows: colours, stylesheet and a few painted controls.

Everything is drawn or styled here rather than left to the platform, so the
windows look the same under Anki's native and Anki widget styles. Rules only
match widgets that opt in through a "kind" property or an object name, which
keeps the file pickers and message boxes opened from these windows native.
"""

from __future__ import annotations

import os

from aqt.qt import *

ACCENT = "#0a84ff"
LIVE = "#34c759"

_DARK = {
    "window_top": "#2b2c31", "window_bottom": "#202125",
    "card": "#2f3035", "card_border": "#3d3e44",
    "text": "#f2f2f5", "muted": "#a0a1a8", "disabled": "#6b6c73",
    "field_top": "#45464d", "field_bottom": "#3b3c42", "field_border": "#54555d",
    "hover_top": "#50515a", "hover_bottom": "#45464d",
    "pressed": "#34353a",
    "well": "#232428", "segment": "#54565f",
    "code": "#1b1c1f",
    "switch_off": "#55565e",
    "leader": "#9aa0a6",
}

_LIGHT = {
    "window_top": "#fafafc", "window_bottom": "#eeeef2",
    "card": "#ffffff", "card_border": "#dcdce2",
    "text": "#1d1d21", "muted": "#6a6b73", "disabled": "#b0b1b8",
    "field_top": "#ffffff", "field_bottom": "#f5f5f8", "field_border": "#cfd0d7",
    "hover_top": "#ffffff", "hover_bottom": "#ececf1",
    "pressed": "#e2e2e8",
    "well": "#e7e7ec", "segment": "#ffffff",
    "code": "#f7f7fa",
    "switch_off": "#c9cad1",
    "leader": "#a9aab2",
}


def is_dark() -> bool:
    return QApplication.palette().color(
        QPalette.ColorRole.Window).lightness() < 128


def tokens() -> dict:
    return _DARK if is_dark() else _LIGHT


def color(name: str) -> QColor:
    return QColor(tokens()[name])


def sheet() -> str:
    t = tokens()
    return f"""
    QDialog[kind="window"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {t['window_top']},
                                    stop:1 {t['window_bottom']});
    }}
    QFrame[kind="card"] {{
        background: {t['card']};
        border: 1px solid {t['card_border']};
        border-radius: 12px;
    }}
    QFrame[kind="well"] {{
        background: {t['well']}; border: none; border-radius: 9px;
    }}
    QFrame[kind="rule"] {{
        background: {t['card_border']}; border: none;
    }}
    QScrollArea[kind="clear"] {{ background: transparent; border: none; }}

    QLabel[kind="text"] {{ color: {t['text']}; background: transparent; }}
    QLabel[kind="text"]:disabled {{ color: {t['disabled']}; }}
    QLabel[kind="muted"] {{ color: {t['muted']}; background: transparent; }}
    QLabel[kind="caption"] {{
        color: {t['muted']}; background: transparent;
        font-size: 11px; font-weight: 600;
    }}

    QPushButton[kind="plain"], QPushButton[kind="primary"] {{
        min-height: 18px; margin: 0px; padding: 5px 12px;
        border-radius: 8px; font-size: 13px;
    }}
    QPushButton[kind="plain"] {{
        color: {t['text']};
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {t['field_top']},
                                    stop:1 {t['field_bottom']});
        border: 1px solid {t['field_border']};
    }}
    QPushButton[kind="plain"]:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {t['hover_top']},
                                    stop:1 {t['hover_bottom']});
    }}
    QPushButton[kind="plain"]:pressed {{ background: {t['pressed']}; }}
    QPushButton[kind="plain"]:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton[kind="plain"]:disabled {{ color: {t['disabled']}; }}

    QPushButton[kind="primary"] {{
        color: white; font-weight: 600; padding: 5px 20px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #2f97ff, stop:1 #0a78ea);
        border: 1px solid #0a6cd4;
    }}
    QPushButton[kind="primary"]:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #47a4ff, stop:1 #1683f2);
    }}
    QPushButton[kind="primary"]:pressed {{ background: #0868cc; }}
    QPushButton[kind="primary"]:focus {{ border: 1px solid #8cc4ff; }}

    QPushButton[kind="segment"] {{
        color: {t['muted']}; background: transparent;
        min-height: 18px; margin: 0px; padding: 4px 12px;
        border: 1px solid transparent; border-radius: 7px; font-size: 13px;
    }}
    QPushButton[kind="segment"]:hover {{ color: {t['text']}; }}
    QPushButton[kind="segment"]:checked {{
        color: {t['text']}; background: {t['segment']};
        border: 1px solid {t['field_border']};
    }}
    QPushButton[kind="segment"]:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton[kind="segment"]:disabled {{
        color: {t['disabled']}; background: transparent;
        border: 1px solid transparent;
    }}

    QDoubleSpinBox[kind="number"] {{
        color: {t['text']}; background: transparent;
        border: none; padding: 0px; margin: 0px;
    }}

    QPlainTextEdit[kind="code"] {{
        color: {t['text']}; background: {t['code']};
        border: 1px solid {t['card_border']}; border-radius: 10px;
        padding: 8px;
    }}
    """


def apply(dialog: QDialog) -> None:
    dialog.setProperty("kind", "window")
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setStyleSheet(sheet())


# --------------------------------------------------------------------------
# Small builders
# --------------------------------------------------------------------------

def label(text: str, kind: str = "text") -> QLabel:
    w = QLabel(text.upper() if kind == "caption" else text)
    w.setProperty("kind", kind)
    return w


def button(text: str, slot=None, kind: str = "plain") -> QPushButton:
    w = QPushButton(text)
    w.setProperty("kind", kind)
    # macOS pads native buttons with invisible margins; ignore them so these
    # line up with everything else.
    w.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
    w.setAutoDefault(False)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        qconnect(w.clicked, slot)
    return w


def frame(kind: str = "card") -> QFrame:
    w = QFrame()
    w.setProperty("kind", kind)
    return w


def rule(vertical: bool = False) -> QFrame:
    w = frame("rule")
    if vertical:
        w.setFixedSize(1, 22)
    else:
        w.setFixedHeight(1)
    return w


# --------------------------------------------------------------------------
# Painted controls
# --------------------------------------------------------------------------

def _arrows(p: QPainter, x: float, y: float, ink: QColor) -> None:
    """The up and down chevrons on a dropdown or number field."""
    pen = QPen(ink, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for sign in (-1, 1):
        p.drawPolyline(QPolygonF([QPointF(x - 3.2, y + sign * 2.4),
                                  QPointF(x, y + sign * 5.6),
                                  QPointF(x + 3.2, y + sign * 2.4)]))


class Logo(QWidget):
    """The Anki-Con wordmark, scaled for the screen it is shown on."""

    HEIGHT = 36
    _PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source = QPixmap(self._PATH)
        self._scaled = QPixmap()
        # Takes no room if the image is missing.
        width = 0 if self._source.isNull() else round(
            self.HEIGHT * self._source.width() / self._source.height())
        self.setFixedSize(width, self.HEIGHT)
        self.setAccessibleName("Anki-Con")

    def paintEvent(self, _e) -> None:
        if self._source.isNull():
            return
        ratio = self.devicePixelRatioF()
        if self._scaled.isNull() or self._scaled.devicePixelRatio() != ratio:
            self._scaled = self._source.scaled(
                round(self.width() * ratio), round(self.height() * ratio),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._scaled.setDevicePixelRatio(ratio)
        QPainter(self).drawPixmap(0, 0, self._scaled)


class Combo(QComboBox):
    """A dropdown with a cleaner face. The popup is the platform's own."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)

    def face_text(self) -> str:
        return self.currentText()

    def is_empty(self) -> bool:
        return not self.currentData()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isEnabled()
        hot = on and self.underMouse()

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QLinearGradient(r.topLeft(), r.bottomLeft())
        fill.setColorAt(0.0, color("hover_top" if hot else "field_top"))
        fill.setColorAt(1.0, color("hover_bottom" if hot else "field_bottom"))
        p.setBrush(QBrush(fill))
        p.setPen(QPen(QColor(ACCENT), 1.5) if self.hasFocus()
                 else QPen(color("field_border"), 1.0))
        p.drawRoundedRect(r, 8, 8)

        ink = color("disabled" if not on else
                    "muted" if self.is_empty() else "text")
        p.setPen(ink)
        box = QRectF(r.left() + 11, r.top(), r.width() - 34, r.height())
        text = p.fontMetrics().elidedText(
            self.face_text(), Qt.TextElideMode.ElideRight, int(box.width()))
        p.drawText(box, Qt.AlignmentFlag.AlignVCenter
                   | Qt.AlignmentFlag.AlignLeft, text)

        _arrows(p, r.right() - 14, r.center().y(),
                color("muted" if on else "disabled"))


class Spin(QDoubleSpinBox):
    """A number field that matches the dropdowns."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.setFixedSize(84, 28)
        self.setFrame(False)
        # Qt styles the text box inside through the spin box's own rules.
        self.setProperty("kind", "number")
        edit = self.lineEdit()
        edit.setFrame(False)
        edit.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.lineEdit().setGeometry(8, 2, self.width() - 34, self.height() - 4)

    def _on_arrows(self, event) -> bool:
        pos = event.position() if hasattr(event, "position") else event.pos()
        return pos.x() >= self.width() - 24

    def mousePressEvent(self, event) -> None:
        # The arrows are painted here, so their clicks are handled here too
        # rather than wherever the platform style would have put them.
        if event.button() == Qt.MouseButton.LeftButton and self._on_arrows(event):
            pos = event.position() if hasattr(event, "position") else event.pos()
            self.stepBy(1 if pos.y() < self.height() / 2 else -1)
            return
        super().mousePressEvent(event)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QLinearGradient(r.topLeft(), r.bottomLeft())
        fill.setColorAt(0.0, color("field_top"))
        fill.setColorAt(1.0, color("field_bottom"))
        p.setBrush(QBrush(fill))
        p.setPen(QPen(QColor(ACCENT), 1.5) if self.hasFocus()
                 else QPen(color("field_border"), 1.0))
        p.drawRoundedRect(r, 8, 8)
        _arrows(p, r.right() - 14, r.center().y(), color("muted"))


class Switch(QCheckBox):
    """A checkbox drawn as a switch; its label sits elsewhere in the row."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.setFixedSize(40, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, 38, 22)
        on = self.isChecked()
        p.setPen(QPen(QColor(ACCENT), 1.5) if self.hasFocus()
                 else Qt.PenStyle.NoPen)
        p.setBrush(QColor(LIVE) if on else color("switch_off"))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        x = r.right() - 11 if on else r.left() + 11
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QPointF(x, r.center().y() + 0.8), 9, 9)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(x, r.center().y()), 9, 9)


class RowLabel(QLabel):
    """A settings label that toggles the switch beside it."""

    def __init__(self, text: str, target: QWidget) -> None:
        super().__init__(text)
        self.setProperty("kind", "text")
        self._target = target
        target.setAccessibleName(text)

    def mouseReleaseEvent(self, event) -> None:
        if isinstance(self._target, QAbstractButton) and \
                event.button() == Qt.MouseButton.LeftButton:
            self._target.click()
        super().mouseReleaseEvent(event)


class HelpPopup(QWidget):
    """A small speech bubble with a title and a short explanation."""

    _ARROW = 8
    _WIDTH = 250

    def __init__(self, title: str, text: str, owner: QWidget) -> None:
        super().__init__(owner.window(), Qt.WindowType.Popup
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # Clicking the "?" again closes the bubble instead of reopening it.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
        self._owner = owner
        self._above = False
        self._tip_x = 0.0

        self._box = QVBoxLayout(self)
        self._box.setSpacing(4)
        head = label(title)
        font = head.font()
        font.setWeight(QFont.Weight.DemiBold)
        head.setFont(font)
        self._box.addWidget(head)
        # A non-breaking hyphen, so "Joy-Con" never splits across lines.
        body = label(text.replace("Joy-Con", "Joy\u2011Con"), "muted")
        body.setWordWrap(True)
        body.setFixedWidth(self._WIDTH)
        self._box.addWidget(body)

    def show_beside(self, owner: QWidget) -> None:
        """Open under the owner, or over it when there is no room below."""
        self._pad(above=False)
        size = self.sizeHint()
        mid = owner.mapToGlobal(QPoint(owner.width() // 2, 0))
        top = mid.y() + owner.height() + 2
        x = mid.x() - size.width() // 2
        screen = owner.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if top + size.height() > area.bottom():
                self._pad(above=True)
                top = mid.y() - size.height() - 2
            x = max(area.left() + 8,
                    min(x, area.right() - size.width() - 8))
        self._tip_x = float(mid.x() - x)
        self.setGeometry(x, top, size.width(), size.height())
        self.show()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._owner.popup_closed()

    def _pad(self, above: bool) -> None:
        self._above = above
        a = self._ARROW
        self._box.setContentsMargins(15, 12 + (0 if above else a),
                                     15, 13 + (a if above else 0))
        self._box.activate()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = self._ARROW
        r = QRectF(self.rect()).adjusted(
            0.5, 0.5 + (0 if self._above else a),
            -0.5, -0.5 - (a if self._above else 0))
        body = QPainterPath()
        body.addRoundedRect(r, 10, 10)
        x = max(r.left() + 18, min(self._tip_x, r.right() - 18))
        base, tip = (r.bottom() - 1, r.bottom() + a - 1) if self._above \
            else (r.top() + 1, r.top() - a + 1)
        arrow = QPainterPath(QPointF(x - a, base))
        arrow.lineTo(x, tip)
        arrow.lineTo(x + a, base)
        arrow.closeSubpath()
        p.setBrush(color("field_bottom" if is_dark() else "card"))
        p.setPen(QPen(color("field_border"), 1.0))
        p.drawPath(body.united(arrow))


class HelpButton(QAbstractButton):
    """The "?" beside a setting. Click it for an explanation."""

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title, self._text = title, text
        self.popup = None
        # Tracked here rather than with underMouse(): no leave event arrives
        # while a popup is open, which left the icon lit after it closed.
        self._hot = False
        self.setFixedSize(18, 18)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(f"About {title}")
        self.setAccessibleDescription(text)
        qconnect(self.clicked, self._open)

    def _open(self) -> None:
        self.popup = HelpPopup(self._title, self._text, self)
        self.popup.show_beside(self)

    def popup_closed(self) -> None:
        self.popup = None
        self._set_hot(False)

    def _set_hot(self, on: bool) -> None:
        if on != self._hot:
            self._hot = on
            self.update()

    def enterEvent(self, event) -> None:
        self._set_hot(True)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._set_hot(True)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hot(False)
        super().leaveEvent(event)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lit = self._hot or self.popup is not None or self.hasFocus()
        ink = QColor(ACCENT) if lit else color("muted")
        p.setPen(QPen(ink, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(1.5, 1.5, 15, 15))
        font = p.font()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(QRectF(0, 0, 18, 18), Qt.AlignmentFlag.AlignCenter, "?")
