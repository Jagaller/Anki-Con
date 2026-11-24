"""
The mapping panel: Joy-Cons drawn in the middle, leader lines fanning out to a
dropdown for every button, laid out like an exploded parts diagram.

The artwork is painted with QPainter from the geometry in ``art``; the callout
slots are real QComboBox widgets positioned by hand, so the leader lines (drawn
in ``paintEvent``) pass underneath them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from aqt.qt import *

from . import actions, art, settings, style
from .joycon import protocol as P

# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

ROW_H = 30
ROW_GAP = 4
SWATCH = 20
LABEL_W = 84
COMBO_W = 224
GAP = 10                 # between a row's swatch, label and dropdown
GUTTER_W = SWATCH + GAP + LABEL_W + GAP + COMBO_W
LEADER_GAP = 26          # clear space between a gutter and the artwork
ART_MIN_W = 300
MARGIN = 12

LEADER = QColor(style.ACCENT)
FLASH = QColor(style.LIVE)
FLASH_MS = 450


@dataclass
class Slot:
    """One callout: a row of widgets plus the point on the art it names."""

    side: str
    element: art.Element
    binding_id: str
    row: QWidget
    swatch: QPushButton
    combo: QComboBox
    gutter: str = "left"         # which side of the diagram the row sits on
    anchor: QPointF = None       # in widget coordinates, set during layout


def _rounded_path(x0: float, y0: float, x1: float, y1: float,
                  rtl: float, rtr: float, rbr: float, rbl: float) -> QPainterPath:
    """A rectangle whose four corners can each have their own radius."""
    p = QPainterPath()
    p.moveTo(x0 + rtl, y0)
    p.lineTo(x1 - rtr, y0)
    if rtr:
        p.arcTo(x1 - 2 * rtr, y0, 2 * rtr, 2 * rtr, 90, -90)
    p.lineTo(x1, y1 - rbr)
    if rbr:
        p.arcTo(x1 - 2 * rbr, y1 - 2 * rbr, 2 * rbr, 2 * rbr, 0, -90)
    p.lineTo(x0 + rbl, y1)
    if rbl:
        p.arcTo(x0, y1 - 2 * rbl, 2 * rbl, 2 * rbl, 270, -90)
    p.lineTo(x0, y0 + rtl)
    if rtl:
        p.arcTo(x0, y0, 2 * rtl, 2 * rtl, 180, -90)
    p.closeSubpath()
    return p


def _shade(color: QColor, factor: float) -> QColor:
    """Lighten (>1) or darken (<1) while keeping the hue."""
    h, s, v, a = color.getHsvF()
    return QColor.fromHsvF(h, s, max(0.0, min(1.0, v * factor)), a)


class ColorSwatch(QPushButton):
    """A flat colour chip that opens the colour wheel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.color = QColor("#33363c")
        self.setFixedSize(SWATCH, SWATCH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip("Change this button's colour")

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        base = self.color if self.isEnabled() \
            else _shade(self.color.toHsv(), 0.6)
        fill = QLinearGradient(r.topLeft(), r.bottomLeft())
        fill.setColorAt(0.0, base.lighter(112))
        fill.setColorAt(1.0, base)
        p.setBrush(QBrush(fill))
        if self.underMouse() or self.hasFocus():
            p.setPen(QPen(QColor(style.ACCENT), 1.5))
        else:
            p.setPen(QPen(style.color("field_border"), 1.0))
        p.drawEllipse(r)


class StatusBadge(QWidget):
    """Connection indicator: a pair of Joy-Cons, lit up when connected.

    Only the halves that are actually connected light up, so it needs no more
    than a word beside it.
    """

    OK, WARN, OFF = "ok", "warn", "off"
    _COLORS = {OK: "#34c759", WARN: "#f5a623", OFF: "#8e8e93"}
    _WORDS = {OK: "Connected", WARN: "No input", OFF: "Disconnected"}

    HEIGHT = 36
    _PAD, _ICON_W, _GAP, _DOT = 14, 27, 10, 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = self.OFF
        self.sides: set = set()
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)
        # Sized for the longest word, so the box never jumps about.
        widest = max(self.fontMetrics().horizontalAdvance(w)
                     for w in self._WORDS.values())
        self.setFixedSize(2 * self._PAD + self._ICON_W + 2 * self._GAP
                          + 2 * self._DOT + widest, self.HEIGHT)
        self.setAccessibleName(self._WORDS[self.state])

    def set_status(self, state: str, sides=()) -> None:
        sides = set(sides)
        if P.SIDE_PRO in sides:
            sides |= {P.SIDE_LEFT, P.SIDE_RIGHT}
        if (state, sides) != (self.state, self.sides):
            self.state, self.sides = state, sides
            self.setAccessibleName(self._WORDS[state])
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._COLORS[self.state])

        def tint(alpha: int) -> QColor:
            c = QColor(color)
            c.setAlpha(alpha)
            return c

        box = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setBrush(tint(38))
        p.setPen(QPen(tint(120), 1.5))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)

        mid = self.height() / 2.0
        x = float(self._PAD)
        self._draw_half(p, QRectF(x, mid - 11, 12, 22), P.SIDE_LEFT, color)
        self._draw_half(p, QRectF(x + 15, mid - 11, 12, 22), P.SIDE_RIGHT, color)
        x += self._ICON_W + self._GAP

        # status light, with a soft glow while something is connected
        centre = QPointF(x + self._DOT, mid)
        p.setPen(Qt.PenStyle.NoPen)
        if self.state != self.OFF:
            p.setBrush(tint(70))
            p.drawEllipse(centre, self._DOT + 3, self._DOT + 3)
        p.setBrush(color)
        p.drawEllipse(centre, self._DOT, self._DOT)
        x += 2 * self._DOT + self._GAP

        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        p.drawText(QRectF(x, 0, self.width() - x, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._WORDS[self.state])

    def _draw_half(self, p: QPainter, r: QRectF, side: str,
                   color: QColor) -> None:
        left = side == P.SIDE_LEFT
        lit = side in self.sides and self.state != self.OFF
        outer, inner = 5.5, 1.5
        body = _rounded_path(r.left(), r.top(), r.right(), r.bottom(),
                             *((outer, inner, inner, outer) if left
                               else (inner, outer, outer, inner)))
        line = QColor(color)
        line.setAlpha(255 if lit else 110)
        p.setPen(QPen(line, 1.4))
        p.setBrush(color if lit else Qt.BrushStyle.NoBrush)
        p.drawPath(body)

        # stick and button cluster: high/low on the left, low/high on the right
        detail = QColor(255, 255, 255, 235) if lit else line
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(detail)
        high, low = r.top() + 7.0, r.bottom() - 7.0
        cx = r.center().x()
        p.drawEllipse(QPointF(cx, high if left else low), 2.5, 2.5)
        y = low if left else high
        for dx, dy in ((0, -2.4), (0, 2.4), (-2.4, 0), (2.4, 0)):
            p.drawEllipse(QPointF(cx + dx, y + dy), 1.0, 1.0)


class ActionCombo(style.Combo):
    """Shows just the action; the group it belongs to is in the list."""

    def face_text(self) -> str:
        return actions.label_for(self.currentData() or "none")

    def is_empty(self) -> bool:
        return self.currentData() in (None, "none")


class MapperPanel(QWidget):
    """Draws the controllers and owns every callout row."""

    selectionChanged = pyqtSignal(str)      # binding id, "" when cleared
    colorRequested = pyqtSignal(str)        # binding id
    bindingChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cfg: dict = {}
        self.layout_name = settings.LAYOUT_DUAL
        self.available: set = set()
        self.slots: Dict[str, Slot] = {}
        self.selected: str = ""
        self._hover: str = ""
        self._flash: Dict[str, float] = {}
        self._transforms: Dict[str, QTransform] = {}
        self._sides: List[str] = [P.SIDE_LEFT, P.SIDE_RIGHT]
        self._loading = False

        self.setMouseTracking(True)
        self.setMinimumSize(2 * GUTTER_W + 2 * LEADER_GAP + ART_MIN_W + 2 * MARGIN,
                            15 * (ROW_H + ROW_GAP) + 2 * MARGIN)

        self.setAutoFillBackground(False)
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(60)
        qconnect(self._flash_timer.timeout, self._tick_flash)

        self._build_slots()

    # -- construction ------------------------------------------------------

    def _build_slots(self) -> None:
        for side in (P.SIDE_LEFT, P.SIDE_RIGHT):
            for element in art.bindable(side):
                bid = art.binding_id(side, element.id)
                self.slots[bid] = self._make_slot(side, element, bid)

    def _make_slot(self, side: str, element: art.Element, bid: str) -> Slot:
        row = QWidget(self)
        swatch = ColorSwatch(row)
        qconnect(swatch.clicked, lambda _=False, b=bid: self.colorRequested.emit(b))

        name = QLabel(element.label, row)
        name.setObjectName("calloutLabel")
        name.setProperty("kind", "muted")

        combo = ActionCombo(row)
        combo.setFixedWidth(COMBO_W)
        self._fill_combo(combo)
        qconnect(combo.currentIndexChanged,
                 lambda _i, b=bid: self._on_combo_changed(b))
        combo.installEventFilter(self)

        return Slot(side=side, element=element, binding_id=bid, row=row,
                    swatch=swatch, combo=combo)

    @staticmethod
    def _fill_combo(combo: QComboBox) -> None:
        for group, items in actions.grouped_actions():
            for a in items:
                label = a.label if group == "General" else f"{group} · {a.label}"
                combo.addItem(label, a.id)

    def eventFilter(self, obj, event):
        # Clicking or tabbing into a dropdown selects its button on the diagram,
        # so the artwork always shows what you are editing.
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            for bid, slot in self.slots.items():
                if slot.combo is obj:
                    self.select(bid)
                    break
        return super().eventFilter(obj, event)

    # -- state -------------------------------------------------------------

    def set_config(self, cfg: dict, layout_name: str, available: set) -> None:
        self.cfg = cfg
        self.layout_name = layout_name
        self.available = set(available or ())
        self._sides = self._visible_sides()
        self.reload_bindings()
        self.reload_colors()
        self._apply_enabled()
        self._relayout()
        self.update()

    def _visible_sides(self) -> List[str]:
        """Which halves to draw. Both, unless a single grip is in play."""
        if self.layout_name == settings.LAYOUT_DUAL:
            return [P.SIDE_LEFT, P.SIDE_RIGHT]
        # Single grip: show the connected half; with nothing connected fall back
        # to the left so the panel is never empty.
        if P.SIDE_RIGHT in self.available and P.SIDE_LEFT not in self.available:
            return [P.SIDE_RIGHT]
        if P.SIDE_LEFT in self.available:
            return [P.SIDE_LEFT]
        return [P.SIDE_LEFT]

    def reload_bindings(self) -> None:
        binds = settings.bindings_for(self.cfg, self.layout_name)
        self._loading = True
        try:
            for bid, slot in self.slots.items():
                idx = slot.combo.findData(binds.get(bid, "none"))
                slot.combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._loading = False

    def reload_colors(self) -> None:
        for slot in self.slots.values():
            slot.swatch.set_color(
                settings.button_color(self.cfg, slot.side, slot.element.id))
        self.update()

    def _apply_enabled(self) -> None:
        """Grey out the half that isn't in use."""
        for slot in self.slots.values():
            live = slot.side in self._sides
            slot.row.setVisible(live)
            slot.row.setEnabled(live)

    def collect_bindings(self) -> Dict[str, str]:
        return {bid: slot.combo.currentData() for bid, slot in self.slots.items()}

    def _on_combo_changed(self, bid: str) -> None:
        if self._loading:
            return
        self.select(bid)
        self.bindingChanged.emit()

    def select(self, bid: str) -> None:
        if bid == self.selected:
            return
        self.selected = bid
        self.selectionChanged.emit(bid)
        self.update()

    def focus_binding(self, bid: str) -> None:
        slot = self.slots.get(bid)
        if slot and slot.row.isVisible():
            self.select(bid)
            slot.combo.setFocus()

    def flash(self, bid: str) -> None:
        """Light up a button that was just pressed on real hardware."""
        if bid not in self.slots:
            return
        self._flash[bid] = time.time() + FLASH_MS / 1000.0
        if not self._flash_timer.isActive():
            self._flash_timer.start()
        self.update()

    def _tick_flash(self) -> None:
        now = time.time()
        for bid in [b for b, t in self._flash.items() if t <= now]:
            self._flash.pop(bid, None)
        if not self._flash:
            self._flash_timer.stop()
        self.update()

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _art_rect(self) -> QRectF:
        return QRectF(MARGIN + GUTTER_W + LEADER_GAP, MARGIN,
                      max(ART_MIN_W, self.width() - 2 * (MARGIN + GUTTER_W + LEADER_GAP)),
                      max(60, self.height() - 2 * MARGIN))

    def _rotation(self, side: str) -> float:
        """Held sideways, a Joy-Con turns so its rail faces up."""
        if self.layout_name != settings.LAYOUT_SINGLE_H:
            return 0.0
        return -90.0 if side == P.SIDE_LEFT else 90.0

    def _transform(self, side: str, box: QRectF) -> QTransform:
        rot = self._rotation(side)
        span_w, span_h = (art.LOCAL_W, art.LOCAL_H) if rot == 0 \
            else (art.LOCAL_H, art.LOCAL_W)
        scale = min(box.width() / span_w, box.height() / span_h)

        t = QTransform()
        t.translate(box.center().x(), box.center().y())
        t.rotate(rot)
        t.scale(scale, scale)
        t.translate(-art.LOCAL_W / 2.0, -art.LOCAL_H / 2.0)
        return t

    def _relayout(self) -> None:
        rect = self._art_rect()
        self._transforms = {}

        if len(self._sides) == 1:
            boxes = {self._sides[0]: rect}
        else:
            half = rect.width() / 2.0
            boxes = {
                P.SIDE_LEFT: QRectF(rect.left(), rect.top(), half - 6, rect.height()),
                P.SIDE_RIGHT: QRectF(rect.left() + half + 6, rect.top(),
                                     half - 6, rect.height()),
            }
        for side, box in boxes.items():
            self._transforms[side] = self._transform(side, box)

        self._assign_gutters(rect)
        self._place_rows()

    def _assign_gutters(self, rect: QRectF) -> None:
        """Decide which side each callout row sits on and cache its anchor."""
        mid = rect.center().x()
        for slot in self.slots.values():
            if slot.side not in self._sides:
                slot.anchor = None
                continue
            t = self._transforms[slot.side]
            ax, ay = slot.element.anchor()
            slot.anchor = t.map(QPointF(ax, ay))
            if len(self._sides) == 2:
                # One controller per gutter keeps the fan symmetrical.
                slot.gutter = "left" if slot.side == P.SIDE_LEFT else "right"
            else:
                # A lone controller splits its rows across both gutters,
                # each row going to whichever side its button already faces.
                slot.gutter = "left" if slot.anchor.x() < mid else "right"

    def _place_rows(self) -> None:
        for gutter in ("left", "right"):
            rows = [s for s in self.slots.values()
                    if s.anchor is not None and s.gutter == gutter]
            rows.sort(key=lambda s: s.anchor.y())
            self._stack(rows, gutter)

    def _stack(self, rows: List[Slot], gutter: str) -> None:
        if not rows:
            return
        top = MARGIN
        avail = max(ROW_H, self.height() - 2 * MARGIN)
        step = min(ROW_H + ROW_GAP * 3, avail / len(rows))
        # Centre the stack when the rows don't fill the height.
        top += max(0.0, (avail - step * len(rows)) / 2.0)
        x = MARGIN if gutter == "left" else self.width() - MARGIN - GUTTER_W

        for i, slot in enumerate(rows):
            y = int(top + i * step)
            slot.row.setGeometry(int(x), y, GUTTER_W, ROW_H)
            self._lay_row(slot, mirrored=(gutter == "right"))

    @staticmethod
    def _lay_row(slot: Slot, mirrored: bool) -> None:
        """Rows mirror in the right gutter so labels face the diagram."""
        name = slot.row.findChild(QLabel, "calloutLabel")
        if mirrored:
            slot.combo.setGeometry(0, 1, COMBO_W, ROW_H - 2)
            name.setGeometry(COMBO_W + GAP, 0, LABEL_W, ROW_H)
            name.setAlignment(Qt.AlignmentFlag.AlignLeft
                              | Qt.AlignmentFlag.AlignVCenter)
            slot.swatch.move(COMBO_W + GAP + LABEL_W + GAP, (ROW_H - SWATCH) // 2)
        else:
            slot.swatch.move(0, (ROW_H - SWATCH) // 2)
            name.setGeometry(SWATCH + GAP, 0, LABEL_W, ROW_H)
            name.setAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)
            slot.combo.setGeometry(SWATCH + GAP + LABEL_W + GAP, 1, COMBO_W, ROW_H - 2)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        for side in self._sides:
            self._draw_side(p, side)
        self._draw_leaders(p)

    def _draw_side(self, p: QPainter, side: str) -> None:
        t = self._transforms.get(side)
        if t is None:
            return
        p.save()
        p.setTransform(t, True)

        shell = QColor(settings.shell_color(self.cfg, side))
        outer_left = side == P.SIDE_LEFT

        # The shoulder cap goes down before the body so the body covers its
        # lower half -- that overlap is what makes it read as a button behind
        # the shell rather than a pill floating above it.
        for e in (e for e in art.elements_for(side) if e.kind == "tab"):
            cap = QColor(settings.button_color(self.cfg, side, e.id))
            p.setBrush(_shade(cap, 0.85))
            p.setPen(QPen(_shade(cap, 0.6), 1.2))
            p.drawRoundedRect(QRectF(e.x, e.y, e.w, e.h), e.r, e.r)

        body = _rounded_path(
            art.BODY_L, art.BODY_TOP, art.BODY_R, art.BODY_BOT,
            *( (art.OUTER_R, art.INNER_R, art.INNER_R, art.OUTER_R)
               if outer_left else
               (art.INNER_R, art.OUTER_R, art.OUTER_R, art.INNER_R) ))

        grad = QLinearGradient(0, art.BODY_TOP, 0, art.BODY_BOT)
        grad.setColorAt(0.0, _shade(shell, 1.12))
        grad.setColorAt(1.0, _shade(shell, 0.88))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(_shade(shell, 0.55), 1.6))
        p.drawPath(body)

        # the flat rail down the inner edge
        rail_x = art.BODY_R - 9 if outer_left else art.BODY_L + 1
        p.setBrush(_shade(shell, 0.72))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(rail_x, art.BODY_TOP + 14, 8, art.BODY_BOT - art.BODY_TOP - 28))

        # Shoulder band, clipped to the shell so it follows the rounded top
        # edge instead of hanging off it.
        for e in (e for e in art.elements_for(side) if e.kind == "band"):
            band = QColor(settings.button_color(self.cfg, side, e.id))
            p.save()
            p.setClipPath(body)
            p.setBrush(band)
            p.setPen(QPen(_shade(band, 0.6), 1.2))
            p.drawRoundedRect(QRectF(e.x, e.y, e.w, e.h), e.r, e.r)
            p.restore()

        for e in art.elements_for(side):
            if e.id:
                self._draw_button(p, side, e)

        p.restore()

    def _draw_button(self, p: QPainter, side: str, e: art.Element) -> None:
        bid = art.binding_id(side, e.id)
        color = QColor(settings.button_color(self.cfg, side, e.id))
        bound = self.slots[bid].combo.currentData() not in (None, "none") \
            if bid in self.slots else False

        if e.kind in ("tab", "band"):
            # Already painted as part of the shell, where the clipping and
            # stacking order live; only the selection ring is left to do.
            self._draw_highlight(p, bid, e)
            return

        p.setPen(QPen(_shade(color, 0.6), 1.2))
        p.setBrush(color)

        if e.kind == "circle":
            p.drawEllipse(QPointF(e.x, e.y), e.r, e.r)
            self._glyph(p, e, color)
        elif e.kind == "stick":
            p.setBrush(_shade(color, 0.75))
            p.drawEllipse(QPointF(e.x, e.y), e.r, e.r)
            p.setBrush(color)
            p.setPen(QPen(_shade(color, 0.5), 1.0))
            p.drawEllipse(QPointF(e.x, e.y), e.r - 7, e.r - 7)
        elif e.kind == "dir":
            self._draw_dir(p, e, color, bound)
        elif e.kind == "capture":
            p.drawRoundedRect(QRectF(e.x, e.y, e.w, e.h), e.r, e.r)
            p.setBrush(_shade(color, 1.9))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(e.x + 6, e.y + 6, e.w - 12, e.h - 12), 2, 2)
        elif e.kind == "home":
            p.drawEllipse(QPointF(e.x, e.y), e.r, e.r)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_shade(color, 2.1), 1.6))
            p.drawEllipse(QPointF(e.x, e.y), e.r - 5, e.r - 5)
        elif e.kind == "plus":
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(e.x, e.y + e.h / 2 - 2.5, e.w, 5), 2, 2)
            p.drawRoundedRect(QRectF(e.x + e.w / 2 - 2.5, e.y, 5, e.h), 2, 2)
        elif e.kind == "minus":
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(e.x, e.y, e.w, e.h), e.r, e.r)
        else:  # rrect: the SL/SR rail buttons
            p.drawRoundedRect(QRectF(e.x, e.y, e.w, e.h), e.r, e.r)

        self._draw_highlight(p, bid, e)

    def _glyph(self, p: QPainter, e: art.Element, color: QColor) -> None:
        """The letter or arrow moulded into a face button."""
        text = {"Up": "▲", "Down": "▼", "Left": "◀", "Right": "▶"}.get(e.id, e.id)
        if e.id not in ("A", "B", "X", "Y", "Up", "Down", "Left", "Right"):
            return
        p.save()
        p.setPen(_shade(color, 2.4))
        font = p.font()
        font.setPointSizeF(e.r * 0.95)
        font.setBold(True)
        p.setFont(font)
        box = QRectF(e.x - e.r, e.y - e.r, e.r * 2, e.r * 2)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _draw_dir(self, p: QPainter, e: art.Element, color: QColor,
                  bound: bool) -> None:
        """Stick directions have no plastic, so draw a small pointer instead."""
        cx, cy = e.x, e.y
        dx, dy = self._dir_vector(e.id)   # points away from the stick centre
        size = 6.0
        tip = QPointF(cx + dx * size, cy + dy * size)
        a = QPointF(cx - dx * size * 0.3 + dy * size * 0.8,
                    cy - dy * size * 0.3 - dx * size * 0.8)
        b = QPointF(cx - dx * size * 0.3 - dy * size * 0.8,
                    cy - dy * size * 0.3 + dx * size * 0.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color if bound else _shade(color, 1.7))
        p.drawPolygon(QPolygonF([tip, a, b]))

    @staticmethod
    def _dir_vector(element_id: str) -> Tuple[float, float]:
        return {"StickUp": (0.0, -1.0), "StickDown": (0.0, 1.0),
                "StickLeft": (-1.0, 0.0), "StickRight": (1.0, 0.0)}.get(
                    element_id, (0.0, 0.0))

    def _draw_highlight(self, p: QPainter, bid: str, e: art.Element) -> None:
        flashing = bid in self._flash
        if not flashing and bid != self.selected and bid != self._hover:
            return
        color = FLASH if flashing else (LEADER if bid == self.selected
                                        else QColor("#9aa0a6"))
        width = 2.6 if (flashing or bid == self.selected) else 1.6
        x, y, w, h = e.bounds()
        pad = 4.0
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, width))
        if e.kind in ("circle", "stick", "home", "dir"):
            p.drawEllipse(QPointF(e.anchor()[0], e.anchor()[1]),
                          max(w, h) / 2 + pad, max(w, h) / 2 + pad)
        else:
            p.drawRoundedRect(QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad),
                              e.r + pad, e.r + pad)

    def _draw_leaders(self, p: QPainter) -> None:
        for bid, slot in self.slots.items():
            if slot.anchor is None or not slot.row.isVisible():
                continue
            live = bid in self._flash or bid == self.selected or bid == self._hover
            color = FLASH if bid in self._flash else (
                LEADER if live else style.color("leader"))
            p.setPen(QPen(color, 2.0 if live else 1.1,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(color)

            geo = slot.row.geometry()
            if slot.gutter == "left":
                start = QPointF(geo.right() + 2, geo.center().y())
                elbow = QPointF(start.x() + LEADER_GAP * 0.45, start.y())
            else:
                start = QPointF(geo.left() - 2, geo.center().y())
                elbow = QPointF(start.x() - LEADER_GAP * 0.45, start.y())

            path = QPainterPath(start)
            path.lineTo(elbow)
            path.lineTo(slot.anchor)
            p.strokePath(path, p.pen())
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(slot.anchor, 2.6 if live else 2.0,
                          2.6 if live else 2.0)

    # -- mouse -------------------------------------------------------------

    def _hit(self, pos: QPointF) -> str:
        best, best_d = "", 1e9
        for bid, slot in self.slots.items():
            if slot.anchor is None or not slot.row.isVisible():
                continue
            t = self._transforms.get(slot.side)
            if t is None:
                continue
            inv, ok = t.inverted()
            if not ok:
                continue
            local = inv.map(QPointF(pos))
            ax, ay = slot.element.anchor()
            d = (local.x() - ax) ** 2 + (local.y() - ay) ** 2
            if d < slot.element.hit_radius() ** 2 and d < best_d:
                best, best_d = bid, d
        return best

    def mouseMoveEvent(self, event) -> None:
        hit = self._hit(event.position() if hasattr(event, "position")
                        else QPointF(event.pos()))
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = ""
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
        hit = self._hit(pos)
        if not hit:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.colorRequested.emit(hit)
        else:
            self.focus_binding(hit)

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
        hit = self._hit(pos)
        if hit:
            self.slots[hit].combo.showPopup()
