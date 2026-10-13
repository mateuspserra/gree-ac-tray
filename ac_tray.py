"""
Controle do ar condicionado Gree pela bandeja do Windows.

    pip install PySide6 greeclimate
    python ac_tray.py              # usa o ar real da rede
    python ac_tray.py --demo       # só a interface, sem ar (para testar o visual)
    python ac_tray.py --ip 192.168.0.50 --name Quarto
"""
import argparse
import asyncio
import math
import logging
import sys
import threading
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation,
                            QObject, QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QMenu, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
TMIN, TMAX = 16, 30

MODES = [("Cool", "Resfriar"), ("Dry", "Seco"), ("Fan", "Ventilar"),
         ("Heat", "Aquecer"), ("Auto", "Automático")]
FANS = [("Auto", "Auto"), ("Low", "Baixa"), ("MediumLow", "Méd. baixa"),
        ("Medium", "Média"), ("MediumHigh", "Méd. alta"), ("High", "Alta")]
FAN_SPEED = {"Auto": 1.0, "Low": 0.6, "MediumLow": 0.8, "Medium": 1.0, "MediumHigh": 1.35, "High": 1.7}
AIR_COLOR = {"Cool": (205, 230, 255), "Dry": (210, 218, 228), "Fan": (235, 238, 242),
             "Heat": (255, 196, 150), "Auto": (235, 238, 242)}

# (chave no estado, propriedade no greeclimate, ícone, rótulo, dica, tipo)
OPTIONS = [
    ("vswing", "vertical_swing", "ArrowsV", "Vertical", "Oscilação vertical", "swing_v"),
    ("hswing", "horizontal_swing", "ArrowsH", "Lateral", "Oscilação lateral", "swing_h"),
    ("quiet", "quiet", "Quiet", "Silencioso", "Modo silencioso", "int"),
    ("sleep", "sleep", "Moon", "Sono", "Modo sono", "bool"),
    ("save", "power_save", "Bolt", "Economia", "Economia de energia", "bool"),
    ("heat8", "steady_heat", "Heat", "Calor 8°C", "Calor estável a 8 °C (aquecimento)", "bool"),
    ("xfan", "xfan", "Dry", "Secar", "Secar o interior depois de desligar (X-Fan)", "bool"),
    ("anion", "anion", "Sparkle", "Saúde", "Saúde (ionizador)", "bool"),
    ("fresh", "fresh_air", "Leaf", "Ar fresco", "Entrada de ar fresco", "bool"),
    ("light", "light", "Bulb", "Luz", "Luz do display do aparelho", "bool"),
    ("buzzer", "buzzer", "Bell", "Beep", "Beep do aparelho ao receber comando", "bool"),
]
SLEEP_OPTS = [(0, "Não"), (30, "30 min"), (60, "1 h"), (120, "2 h"), (240, "4 h")]

CYAN = "#59c9ff"
MUTED = "#8a909c"
TEXT = "#f4f6fa"
FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]


def C(hex_color, alpha=255):
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def font(px, bold=False):
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def pen(color, width=1.6):
    return QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


# ----------------------------------------------------------------------------
# Ícones desenhados à mão (sem depender de fonte de ícones)
# ----------------------------------------------------------------------------
def draw_icon(p, kind, c, r, color):
    p.save()
    p.setPen(pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    x, y = c.x(), c.y()

    if kind == "Cool":
        for a in (0, 60, 120):
            dx, dy = math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r
            p.drawLine(QPointF(x - dx, y - dy), QPointF(x + dx, y + dy))
        for a in range(0, 360, 60):
            tip = QPointF(x + math.cos(math.radians(a)) * r * 0.68, y + math.sin(math.radians(a)) * r * 0.68)
            for s in (-40, 40):
                b = math.radians(a + 180 + s)
                p.drawLine(tip, QPointF(tip.x() + math.cos(b) * r * 0.3, tip.y() + math.sin(b) * r * 0.3))
    elif kind == "Dry":
        path = QPainterPath(QPointF(x, y - r))
        path.cubicTo(x + r * 0.9, y - r * 0.1, x + r * 0.8, y + r, x, y + r)
        path.cubicTo(x - r * 0.8, y + r, x - r * 0.9, y - r * 0.1, x, y - r)
        p.drawPath(path)
    elif kind == "Fan":
        for i in range(4):
            p.save()
            p.translate(x, y)
            p.rotate(i * 90)
            p.drawEllipse(QPointF(0, -r * 0.52), r * 0.3, r * 0.5)
            p.restore()
        p.drawEllipse(c, r * 0.12, r * 0.12)
    elif kind == "Heat":
        p.drawEllipse(c, r * 0.42, r * 0.42)
        for a in range(0, 360, 45):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            p.drawLine(QPointF(x + ca * r * 0.7, y + sa * r * 0.7), QPointF(x + ca * r, y + sa * r))
    elif kind == "Auto":
        p.setFont(font(int(r * 2), True))
        p.drawText(QRectF(x - r, y - r, r * 2, r * 2), Qt.AlignmentFlag.AlignCenter, "A")
    elif kind == "Wind":
        for dy, ln, curl in ((-0.55, 1.0, True), (0.0, 1.5, False), (0.55, 1.1, True)):
            path = QPainterPath(QPointF(x - r * 0.9, y + dy * r))
            end = x - r * 0.9 + r * ln
            path.lineTo(end, y + dy * r)
            if curl:
                sgn = -1 if dy < 0 else 1
                path.quadTo(end + r * 0.55, y + dy * r, end + r * 0.3, y + dy * r + sgn * r * 0.45)
            p.drawPath(path)
    elif kind == "Therm":
        p.drawRoundedRect(QRectF(x - r * 0.28, y - r, r * 0.56, r * 1.55), r * 0.28, r * 0.28)
        p.drawEllipse(QPointF(x, y + r * 0.6), r * 0.48, r * 0.48)
        p.drawLine(QPointF(x, y - r * 0.3), QPointF(x, y + r * 0.5))
    elif kind == "Power":
        p.setPen(pen(color, 2.0))
        p.drawArc(QRectF(x - r * 0.72, y - r * 0.62, r * 1.44, r * 1.44), 120 * 16, 300 * 16)
        p.drawLine(QPointF(x, y - r * 0.95), QPointF(x, y - r * 0.1))
    elif kind == "Refresh":
        R = r * 0.78
        p.drawArc(QRectF(x - R, y - R, R * 2, R * 2), 40 * 16, 280 * 16)
        end = QPointF(x + R * math.cos(math.radians(-40)), y - R * math.sin(math.radians(-40)))
        back = (-0.643, 0.766)
        for s in (-38, 38):
            t = math.radians(s)
            bx = back[0] * math.cos(t) - back[1] * math.sin(t)
            by = back[0] * math.sin(t) + back[1] * math.cos(t)
            p.drawLine(end, QPointF(end.x() + bx * r * 0.5, end.y() + by * r * 0.5))
    elif kind == "Shield":
        path = QPainterPath(QPointF(x, y - r))
        path.lineTo(x + r * 0.8, y - r * 0.6)
        path.lineTo(x + r * 0.8, y + r * 0.1)
        path.quadTo(x + r * 0.8, y + r * 0.7, x, y + r)
        path.quadTo(x - r * 0.8, y + r * 0.7, x - r * 0.8, y + r * 0.1)
        path.lineTo(x - r * 0.8, y - r * 0.6)
        path.closeSubpath()
        p.drawPath(path)
        p.drawPolyline([QPointF(x - r * 0.33, y), QPointF(x - r * 0.05, y + r * 0.3), QPointF(x + r * 0.4, y - r * 0.25)])
    elif kind == "ArrowsV":
        p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
        p.drawPolyline([QPointF(x - r * 0.45, y - r * 0.5), QPointF(x, y - r), QPointF(x + r * 0.45, y - r * 0.5)])
        p.drawPolyline([QPointF(x - r * 0.45, y + r * 0.5), QPointF(x, y + r), QPointF(x + r * 0.45, y + r * 0.5)])
    elif kind == "ArrowsH":
        p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
        p.drawPolyline([QPointF(x - r * 0.5, y - r * 0.45), QPointF(x - r, y), QPointF(x - r * 0.5, y + r * 0.45)])
        p.drawPolyline([QPointF(x + r * 0.5, y - r * 0.45), QPointF(x + r, y), QPointF(x + r * 0.5, y + r * 0.45)])
    elif kind == "Quiet":
        p.drawPolygon([QPointF(x - r, y - r * 0.3), QPointF(x - r * 0.45, y - r * 0.3), QPointF(x + r * 0.05, y - r * 0.8),
                       QPointF(x + r * 0.05, y + r * 0.8), QPointF(x - r * 0.45, y + r * 0.3), QPointF(x - r, y + r * 0.3)])
        p.drawLine(QPointF(x + r * 0.4, y - r * 0.35), QPointF(x + r * 0.95, y + r * 0.35))
        p.drawLine(QPointF(x + r * 0.4, y + r * 0.35), QPointF(x + r * 0.95, y - r * 0.35))
    elif kind == "Moon":
        outer, inner = QPainterPath(), QPainterPath()
        outer.addEllipse(c, r * 0.85, r * 0.85)
        inner.addEllipse(QPointF(x + r * 0.45, y - r * 0.3), r * 0.75, r * 0.75)
        p.drawPath(outer.subtracted(inner))
    elif kind == "Bolt":
        p.drawPolygon([QPointF(x + r * 0.25, y - r), QPointF(x - r * 0.55, y + r * 0.1), QPointF(x, y + r * 0.1),
                       QPointF(x - r * 0.25, y + r), QPointF(x + r * 0.55, y - r * 0.2), QPointF(x, y - r * 0.2)])
    elif kind == "Sparkle":
        k = 0.25
        p.drawPolygon([QPointF(x, y - r), QPointF(x + r * k, y - r * k), QPointF(x + r, y), QPointF(x + r * k, y + r * k),
                       QPointF(x, y + r), QPointF(x - r * k, y + r * k), QPointF(x - r, y), QPointF(x - r * k, y - r * k)])
    elif kind == "Leaf":
        path = QPainterPath(QPointF(x - r * 0.8, y + r * 0.8))
        path.quadTo(x - r * 0.95, y - r * 0.6, x + r * 0.8, y - r * 0.8)
        path.quadTo(x + r * 0.95, y + r * 0.6, x - r * 0.8, y + r * 0.8)
        p.drawPath(path)
        p.drawLine(QPointF(x - r * 0.8, y + r * 0.8), QPointF(x + r * 0.2, y - r * 0.2))
    elif kind == "Bulb":
        p.drawEllipse(QPointF(x, y - r * 0.25), r * 0.62, r * 0.62)
        p.drawLine(QPointF(x - r * 0.3, y + r * 0.55), QPointF(x + r * 0.3, y + r * 0.55))
        p.drawLine(QPointF(x - r * 0.2, y + r * 0.9), QPointF(x + r * 0.2, y + r * 0.9))
    elif kind == "Bell":
        path = QPainterPath(QPointF(x - r * 0.65, y + r * 0.5))
        path.cubicTo(x - r * 0.65, y - r * 0.2, x - r * 0.5, y - r * 0.8, x, y - r * 0.8)
        path.cubicTo(x + r * 0.5, y - r * 0.8, x + r * 0.65, y - r * 0.2, x + r * 0.65, y + r * 0.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(x - r * 0.2, y + r * 0.85), QPointF(x + r * 0.2, y + r * 0.85))
    elif kind in ("ChevLeft", "ChevRight"):
        d = -1 if kind == "ChevLeft" else 1
        p.drawPolyline([QPointF(x - d * r * 0.3, y - r * 0.6), QPointF(x + d * r * 0.3, y), QPointF(x - d * r * 0.3, y + r * 0.6)])
    p.restore()


# ----------------------------------------------------------------------------
# Widgets
# ----------------------------------------------------------------------------
class Header(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.name, self.room = "Ar condicionado", None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_icon(p, "Therm", QPointF(8, 20), 7, C(MUTED))
        p.setFont(font(14, True))
        p.setPen(C(TEXT))
        p.drawText(QPointF(22, 25), self.name)


class PowerButton(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.on, self.hover = False, False

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(20, 20)
        if self.on:
            glow = QRadialGradient(c, 20)
            glow.setColorAt(0.6, C(CYAN, 70))
            glow.setColorAt(1, C(CYAN, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, 20, 20)
            p.setBrush(C("#7ad8ff") if self.hover else C(CYAN))
            p.drawEllipse(c, 16, 16)
            draw_icon(p, "Power", c, 8, C("#06222f"))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C("#363a43") if self.hover else C("#2a2d34"))
            p.drawEllipse(c, 16, 16)
            draw_icon(p, "Power", c, 8, C(MUTED))


class AirHero(QWidget):
    """Ar condicionado desenhado + fluxo de ar animado."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(150)
        self.on, self.temp, self.mode, self.fan, self.turbo = False, 24, "Cool", "Auto", False
        self.phase = 0.0

    def advance(self, dt):
        self.phase += dt * FAN_SPEED.get(self.fan, 1.0) * (1.5 if self.turbo else 1.0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        uw, uh = 196, 56
        ux, uy = (self.width() - uw) / 2, 10
        if self.on:
            self._air(p, ux, uw, uy + uh - 8)

        g = QLinearGradient(0, uy, 0, uy + uh)
        g.setColorAt(0, C("#ffffff"))
        g.setColorAt(1, C("#d6dce5"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(ux, uy, uw, uh), 16, 16)
        p.setBrush(C("#14161a") if self.on else C("#b4bbc7"))
        p.drawRoundedRect(QRectF(ux + 8, uy + uh - 15, uw - 16, 8), 4, 4)
        p.setBrush(C("#c2c8d2"))
        p.drawEllipse(QPointF(ux + 30, uy + 16), 1.8, 1.8)
        p.setFont(font(10, True))
        p.setPen(C(CYAN) if self.on else C("#9aa0aa"))
        p.drawText(QRectF(ux + uw - 52, uy + 8, 38, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(self.temp))

    def _air(self, p, ux, uw, y0):
        col = AIR_COLOR.get(self.mode, (235, 238, 242))
        n = 32
        for i in range(n):
            t = i / (n - 1)
            ang = (t - 0.5) * 2 * 0.28
            x0 = ux + 18 + t * (uw - 36)
            frac = ((i * 7919) % 97) / 97.0
            speed = 0.35 + 0.25 * (((i * 31) % 13) / 13.0)
            s = (self.phase * speed + frac) % 1.0
            max_len = 70 + 18 * (((i * 17) % 7) / 7.0)
            d1 = s * max_len
            d2 = min(d1 + 24 + 14 * frac, max_len)
            alpha = int(150 * math.sin(math.pi * s))
            if alpha < 6:
                continue
            sa, ca = math.sin(ang), math.cos(ang)
            wob = math.sin(self.phase * 2.2 + i) * 1.5

            def pt(d):
                return QPointF(x0 + sa * d + wob * d / max_len, y0 + ca * d)

            p.setPen(pen(QColor(col[0], col[1], col[2], alpha), 1.1))
            p.drawLine(pt(d1), pt(d2))


class BigTemp(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(58)
        self.value, self.on = 24, False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        txt = str(self.value)
        p.setFont(font(46, True))
        p.setPen(C(TEXT) if self.on else C("#5d626c"))
        p.drawText(QPointF(2, 46), txt)
        w = p.fontMetrics().horizontalAdvance(txt)
        p.setFont(font(16))
        p.setPen(C(MUTED) if self.on else C("#4a4e57"))
        p.drawText(QPointF(2 + w + 6, 28), "°C")


class TempSlider(QWidget):
    changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(66)
        self.value, self.on, self._drag = 24, False, False

    # geometria
    def _track(self):
        return QRectF(46, 4, self.width() - 92, 36)

    def _knob_x(self):
        tr = self._track()
        lo, hi = tr.left() + 18, tr.right() - 18
        return lo + (self.value - TMIN) / (TMAX - TMIN) * (hi - lo)

    def _value_at(self, x):
        tr = self._track()
        lo, hi = tr.left() + 18, tr.right() - 18
        f = min(1.0, max(0.0, (x - lo) / (hi - lo)))
        return int(round(TMIN + f * (TMAX - TMIN)))

    def _set(self, v):
        v = max(TMIN, min(TMAX, v))
        if v != self.value:
            self.value = v
            self.update()
            self.changed.emit(v)

    def mousePressEvent(self, e):
        x, y = e.position().x(), e.position().y()
        if x < 40:
            self._set(self.value - 1)
        elif x > self.width() - 40:
            self._set(self.value + 1)
        else:
            self._drag = True
            self._set(self._value_at(x))

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set(self._value_at(e.position().x()))

    def mouseReleaseEvent(self, _):
        self._drag = False

    def wheelEvent(self, e):
        self._set(self.value + (1 if e.angleDelta().y() > 0 else -1))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tr, cy = self._track(), 22
        # botões - e +
        for cx, sign in ((20, "-"), (self.width() - 20, "+")):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C("#23262c"))
            p.drawEllipse(QPointF(cx, cy), 17, 17)
            p.setPen(pen(C("#c9ced8"), 1.8))
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
            if sign == "+":
                p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        # trilho
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C("#23262c"))
        p.drawRoundedRect(tr, 18, 18)
        kx = self._knob_x()
        fill = QRectF(tr.left(), tr.top(), kx - tr.left() + 2, tr.height())
        g = QLinearGradient(fill.left(), 0, fill.right(), 0)
        if self.on:
            g.setColorAt(0, C("#2f66ff"))
            g.setColorAt(1, C("#52c4ff"))
        else:
            g.setColorAt(0, C("#2c2f36"))
            g.setColorAt(1, C("#5a5e68"))
        p.setBrush(g)
        p.drawRoundedRect(fill, 18, 18)
        p.setBrush(C("#ffffff"))
        p.drawEllipse(QPointF(kx, cy), 13, 13)
        # rótulos
        p.setFont(font(11))
        p.setPen(C("#6b7078"))
        lo, hi = tr.left() + 18, tr.right() - 18
        p.drawText(QRectF(lo - 20, 46, 40, 16), Qt.AlignmentFlag.AlignCenter, f"{TMIN}°")
        p.drawText(QRectF(hi - 20, 46, 40, 16), Qt.AlignmentFlag.AlignCenter, f"{TMAX}°")


class Tile(QWidget):
    clicked = Signal()

    def __init__(self, title):
        super().__init__()
        self.setFixedHeight(66)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title, self.value, self.icon = title, "", "Fan"
        self.toggle = None  # None = sem switch; True/False = switch
        self.hover = False

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = self.toggle is True
        p.setBrush(C(CYAN, 22) if active else (C("#ffffff", 14) if self.hover else C("#ffffff", 8)))
        p.setPen(QPen(C(CYAN, 110) if active else C("#ffffff", 22), 1))
        p.drawRoundedRect(r, 12, 12)
        draw_icon(p, self.icon, QPointF(20, 18), 7.5, C(CYAN) if active else C("#c9ced8"))
        p.setFont(font(11))
        p.setPen(C(MUTED))
        p.drawText(QPointF(12, 40), self.title)
        p.setFont(font(13, True))
        p.setPen(C(TEXT))
        p.drawText(QPointF(12, 58), self.value)
        if self.toggle is not None:
            sw = QRectF(self.width() - 46, 10, 34, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(CYAN) if self.toggle else C("#3a3e47"))
            p.drawRoundedRect(sw, 10, 10)
            kx = sw.right() - 10 if self.toggle else sw.left() + 10
            p.setBrush(C("#ffffff"))
            p.drawEllipse(QPointF(kx, sw.center().y()), 7, 7)


class Footer(QWidget):
    refresh = Signal()
    more = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(30)
        self.kind, self.text, self.spin = "ok", "Atualizado", 0.0
        self.hover, self.more_open = 0, False   # hover: 0 nada, 1 mais opções, 2 atualizar
        self.setMouseTracking(True)

    def set_status(self, kind, text):
        self.kind, self.text = kind, text
        self.update()

    def advance(self, dt):
        if self.kind == "busy":
            self.spin = (self.spin + dt * 360 * 1.4) % 360
            self.update()

    def _zone(self, x):
        if x > self.width() - 34:
            return 2
        if x > self.width() - 34 - 104:
            return 1
        return 0

    def mouseMoveEvent(self, e):
        z = self._zone(e.position().x())
        self.setCursor(Qt.CursorShape.PointingHandCursor if z else Qt.CursorShape.ArrowCursor)
        if z != self.hover:
            self.hover = z
            self.update()

    def leaveEvent(self, _):
        self.hover = 0
        self.update()

    def mouseReleaseEvent(self, e):
        z = self._zone(e.position().x())
        if z == 2:
            self.refresh.emit()
        elif z == 1:
            self.more.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        col = C("#e2878a") if self.kind == "error" else C("#7d838f")
        if self.kind == "busy":
            p.setPen(pen(col, 1.6))
            p.drawArc(QRectF(4, cy - 7, 14, 14), int(-self.spin * 16), 270 * 16)
        else:
            draw_icon(p, "Shield", QPointF(11, cy), 6.5, col)
        p.setFont(font(11))
        p.setPen(col)
        p.drawText(QPointF(26, cy + 4), self.text)
        # Mais opções
        mc = C(TEXT) if (self.hover == 1 or self.more_open) else C("#9aa0aa")
        rx = self.width() - 34
        p.setPen(mc)
        p.drawText(QRectF(rx - 104, 0, 88, self.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Mais opções")
        draw_icon(p, "ChevRight" if self.more_open else "ChevLeft", QPointF(rx - 8, cy), 6, mc)
        draw_icon(p, "Refresh", QPointF(self.width() - 14, cy), 7.5, C("#c9ced8") if self.hover == 2 else C("#7d838f"))


class Chip(QWidget):
    clicked = Signal()

    def __init__(self, icon, label):
        super().__init__()
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon, self.label, self.on, self.hover = icon, label, False, False

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(C(CYAN, 22) if self.on else (C("#ffffff", 14) if self.hover else C("#ffffff", 8)))
        p.setPen(QPen(C(CYAN, 110) if self.on else C("#ffffff", 22), 1))
        p.drawRoundedRect(r, 10, 10)
        draw_icon(p, self.icon, QPointF(self.width() / 2, 19), 7, C(CYAN) if self.on else C("#c9ced8"))
        p.setFont(font(11))
        p.setPen(C(TEXT) if self.on else C("#a3a9b4"))
        txt = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, self.width() - 6)
        p.drawText(QRectF(0, 33, self.width(), 16), Qt.AlignmentFlag.AlignCenter, txt)


class SideTitle(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(14, True))
        p.setPen(C(TEXT))
        p.drawText(QPointF(2, 24), "Mais opções")


class TimerRow(QWidget):
    picked = Signal(int)   # minutos; 0 = cancelar

    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("A contagem é feita por este app: o PC precisa estar ligado.")
        self.sel, self.left = 0, None

    def _seg(self):
        gap = 6
        return (self.width() - gap * (len(SLEEP_OPTS) - 1)) / len(SLEEP_OPTS), gap

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or e.position().y() < 20:
            return
        w, gap = self._seg()
        i = int(e.position().x() // (w + gap))
        if 0 <= i < len(SLEEP_OPTS):
            self.picked.emit(SLEEP_OPTS[i][0])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(11))
        p.setPen(C(MUTED))
        p.drawText(QPointF(2, 12), "Desligar sozinho em")
        if self.left is not None:
            m = int((self.left + 59) // 60)
            txt = f"Faltam {m // 60} h {m % 60:02d} min" if m >= 60 else f"Faltam {m} min"
            p.setPen(C(CYAN))
            p.drawText(QRectF(0, 0, self.width() - 2, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)
        w, gap = self._seg()
        p.setFont(font(12 if w >= 52 else 11, True))
        for i, (mins, label) in enumerate(SLEEP_OPTS):
            rect = QRectF(i * (w + gap), 22, w, 30)
            on = mins == self.sel
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(CYAN) if on else C("#2a2d34"))
            p.drawRoundedRect(rect, 15, 15)
            p.setPen(C("#06222f") if on else C("#c9ced8"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


class InfoRow(QWidget):
    """Só aparece se o aparelho informar umidade, tanque ou filtro."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(44)
        self.items = []

    def paintEvent(self, _):
        if not self.items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 8
        w = (self.width() - gap * (len(self.items) - 1)) / len(self.items)
        for i, (label, value, warn) in enumerate(self.items):
            rect = QRectF(i * (w + gap), 0, w, self.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C("#ffffff", 10))
            p.drawRoundedRect(rect, 10, 10)
            p.setFont(font(11))
            p.setPen(C(MUTED))
            p.drawText(QPointF(rect.left() + 10, 17), label)
            p.setFont(font(13, True))
            p.setPen(C("#e8b45a") if warn else C(TEXT))
            p.drawText(QPointF(rect.left() + 10, 34), value)


# ----------------------------------------------------------------------------
# Backends (Gree real e demo)
# ----------------------------------------------------------------------------
class Backend(QObject):
    state_changed = Signal(dict)   # leitura periódica / inicial
    push_done = Signal(dict)       # resultado de um envio
    status = Signal(str, str)      # (ok|busy|error, texto)

    def start(self): ...
    def push(self, changes): ...
    def refresh(self): ...


class DemoBackend(Backend):
    def __init__(self):
        super().__init__()
        self.s = dict(power=True, temp=24, mode="Cool", fan="Auto", turbo=False, room=26, name="Quarto",
                      humidity=58, water_full=False, clean_filter=True,
                      **{k: False for k, *_ in OPTIONS})
        self.s.update(vswing=True, save=True, light=True, buzzer=True)

    def start(self):
        QTimer.singleShot(200, lambda: self.state_changed.emit(dict(self.s)))

    def push(self, changes):
        self.s.update(changes)
        self.status.emit("busy", "Enviando…")
        QTimer.singleShot(700, self._done)

    def _done(self):
        self.push_done.emit(dict(self.s))
        self.status.emit("ok", "Atualizado")

    def refresh(self):
        self.status.emit("busy", "Atualizando…")
        QTimer.singleShot(500, lambda: (self.state_changed.emit(dict(self.s)), self.status.emit("ok", "Atualizado")))


class GreeBackend(Backend):
    def __init__(self, ip=None):
        super().__init__()
        self.ip, self.dev = ip, None
        self.loop = asyncio.new_event_loop()
        self._lock = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self._lock = asyncio.Lock()
        self.loop.run_forever()

    def _submit(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start(self):
        self.refresh()

    def push(self, changes):
        self._submit(self._push(changes))

    def refresh(self):
        self._submit(self._refresh())

    # --- internos (rodam na thread do asyncio) ---
    async def _ensure(self):
        if self.dev:
            return
        from greeclimate.device import Device
        from greeclimate.discovery import Discovery
        self.status.emit("busy", "Procurando ar…")
        from ipaddress import IPv4Address
        # com --ip, pergunta direto ao aparelho quando ele estiver acessível na rede;
        # sem --ip, usa broadcast em todas as placas de rede do PC
        targets = [IPv4Address(self.ip)] if self.ip else None
        infos = await Discovery().scan(wait_for=4, bcast_ifaces=targets)
        if self.ip:
            infos = [i for i in infos if i.ip == self.ip]
        if not infos:
            raise ConnectionError("nenhum Gree encontrado")
        class ResponsiveDevice(Device):
            def __init__(self, info):
                super().__init__(info, timeout=6, bind_timeout=3)
                self.state_received = asyncio.Event()

            def handle_state_update(self, **properties):
                super().handle_state_update(**properties)
                self.state_received.set()

        dev = ResponsiveDevice(infos[0])
        await dev.bind()
        self.dev = dev

    async def _read(self):
        from greeclimate.device import FanSpeed, Mode
        self.dev.state_received.clear()
        await self.dev.update_state()
        await asyncio.wait_for(self.dev.state_received.wait(), timeout=6)
        d = self.dev

        def name(enum, v):
            try:
                return enum(v).name
            except Exception:
                return str(v)

        room = getattr(d, "current_temperature", None)
        st = dict(power=bool(d.power), temp=int(d.target_temperature),
                  mode=name(Mode, d.mode), fan=name(FanSpeed, d.fan_speed),
                  turbo=bool(d.turbo), room=room,
                  name=getattr(d.device_info, "name", None) or "Ar condicionado",
                  humidity=getattr(d, "current_humidity", None),
                  water_full=getattr(d, "water_full", None),
                  clean_filter=getattr(d, "clean_filter", None))
        for key, attr, *_ in OPTIONS:
            st[key] = bool(getattr(d, attr, None))   # swing/quiet: 0 ou None = desligado
        return st

    async def _refresh(self):
        try:
            async with self._lock:
                await self._ensure()
                self.status.emit("busy", "Atualizando…")
                st = await self._read()
            self.state_changed.emit(st)
            self.status.emit("ok", "Atualizado")
        except Exception:
            logging.exception("Falha na comunicacao com o ar")
            self.dev = None
            self.status.emit("error", "Sem conexão")

    async def _push(self, ch):
        from greeclimate.device import FanSpeed, HorizontalSwing, Mode, VerticalSwing
        try:
            async with self._lock:
                await self._ensure()
                self.status.emit("busy", "Enviando…")
                await self._read()   # aguarda o estado atual antes de alterar
                d = self.dev
                if "power" in ch:
                    d.power = ch["power"]
                if "temp" in ch:
                    d.target_temperature = ch["temp"]
                if "mode" in ch:
                    d.mode = getattr(Mode, ch["mode"])
                if "fan" in ch:
                    d.fan_speed = getattr(FanSpeed, ch["fan"])
                if "turbo" in ch:
                    d.turbo = ch["turbo"]
                for key, attr, _i, _l, _t, kind in OPTIONS:
                    if key not in ch:
                        continue
                    v = ch[key]
                    if kind == "swing_v":
                        v = VerticalSwing.FullSwing if v else VerticalSwing.Default
                    elif kind == "swing_h":
                        v = HorizontalSwing.FullSwing if v else HorizontalSwing.Default
                    elif kind == "int":
                        v = int(v)
                    setattr(d, attr, v)
                d.state_received.clear()
                await d.push_state_update()
                await asyncio.wait_for(d.state_received.wait(), timeout=6)
                self.status.emit("busy", "Atualizando…")
                st = await self._read()
            self.push_done.emit(st)
            self.status.emit("ok", "Atualizado")
        except Exception:
            logging.exception("Falha na comunicacao com o ar")
            self.dev = None
            self.push_done.emit({})
            self.status.emit("error", "Sem conexão")


# ----------------------------------------------------------------------------
# Janela popup
# ----------------------------------------------------------------------------
class Card(QWidget):
    """Cartão escuro arredondado (fundo do popup e do painel lateral)."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, C("#1d2229"))
        g.setColorAt(1, C("#101216"))
        p.fillPath(path, g)
        glow = QRadialGradient(QPointF(50, 0), 260)
        glow.setColorAt(0, C("#2ad4d4", 38))
        glow.setColorAt(1, C("#2ad4d4", 0))
        p.fillPath(path, glow)
        p.setPen(QPen(C("#ffffff", 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class Popup(QWidget):
    def __init__(self, backend, name_override=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.backend, self.name_override = backend, name_override
        self.state = dict(power=False, temp=24, mode="Cool", fan="Auto", turbo=False, room=None,
                          name=name_override or "Ar condicionado",
                          humidity=None, water_full=None, clean_filter=None,
                          **{k: False for k, *_ in OPTIONS})
        self.sleep_end = None
        self.pending, self.inflight, self._hidden_at = {}, 0, 0.0

        self.header, self.power = Header(), PowerButton()
        self.hero, self.big, self.slider = AirHero(), BigTemp(), TempSlider()
        self.t_mode, self.t_fan, self.t_turbo = Tile("Modo"), Tile("Ventilação"), Tile("Turbo")
        self.t_fan.icon, self.t_turbo.icon, self.t_turbo.toggle = "Fan", "Wind", False
        self.footer = Footer()

        # --- janela = [painel lateral (opcional)] + [cartão principal] ---
        self.main, self.side = Card(), Card()
        self.main.setFixedWidth(340)
        self.side.setFixedWidth(300)
        self.side.hide()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self.side)
        root.addWidget(self.main)

        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(10)
        sl.addWidget(SideTitle())
        grid = QGridLayout()
        grid.setSpacing(6)
        self.chips = {}
        for i, (key, _attr, icon, label, tip, _kind) in enumerate(OPTIONS):
            chip = Chip(icon, label)
            chip.setToolTip(tip)
            chip.clicked.connect(lambda k=key: self.change(**{k: not self.state[k]}))
            grid.addWidget(chip, i // 3, i % 3)
            self.chips[key] = chip
        sl.addLayout(grid)
        self.timer_row, self.info = TimerRow(), InfoRow()
        sl.addWidget(self.timer_row)
        sl.addWidget(self.info)
        sl.addStretch(1)

        lay = QVBoxLayout(self.main)
        lay.setContentsMargins(20, 16, 20, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(self.header, 1)
        head.addWidget(self.power)
        lay.addLayout(head)
        lay.addWidget(self.hero)
        lay.addWidget(self.big)
        lay.addSpacing(4)
        lay.addWidget(self.slider)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        for t in (self.t_mode, self.t_fan, self.t_turbo):
            row.addWidget(t)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(self.footer)

        # ações do usuário
        self.power.clicked.connect(lambda: self.change(power=not self.state["power"]))
        self.slider.changed.connect(lambda v: self.change(temp=v))
        self.t_mode.clicked.connect(lambda: self.change(mode=self._next(MODES, "mode")))
        self.t_fan.clicked.connect(lambda: self.change(fan=self._next(FANS, "fan")))
        self.t_turbo.clicked.connect(lambda: self.change(turbo=not self.state["turbo"]))
        self.footer.refresh.connect(self.backend.refresh)
        self.footer.more.connect(self.toggle_more)
        self.timer_row.picked.connect(self._set_sleep)
        self.sleep_tick = QTimer(self, interval=1000)
        self.sleep_tick.timeout.connect(self._sleep_tick)

        # backend
        backend.state_changed.connect(self._on_state)
        backend.push_done.connect(self._on_push_done)
        backend.status.connect(self.footer.set_status)

        self.debounce = QTimer(self, singleShot=True, interval=450)
        self.debounce.timeout.connect(self._flush)
        self.anim = QTimer(self, interval=33)
        self.anim.timeout.connect(self._tick)
        self.poll = QTimer(self, interval=15000)
        self.poll.timeout.connect(self._poll)
        self.poll.start()
        self._anims = []
        self.refresh_ui()

    # ----- lógica -----
    def _next(self, table, key):
        keys = [k for k, _ in table]
        i = keys.index(self.state[key]) if self.state[key] in keys else -1
        return keys[(i + 1) % len(keys)]

    def change(self, **kw):
        if kw.get("power") is False and self.sleep_end:
            self._set_sleep(0)          # desligou na mão: cancela o timer
        self.state.update(kw)
        self.pending.update(kw)
        self.refresh_ui()
        self.footer.set_status("busy", "Aguardando…")
        self.debounce.start()

    def _flush(self):
        ch, self.pending = self.pending, {}
        if ch:
            self.inflight += 1
            self.backend.push(ch)

    def _busy(self):
        return bool(self.pending) or self.debounce.isActive() or self.inflight > 0

    def _on_state(self, st):
        if not self._busy():
            self._apply(st)

    def _on_push_done(self, st):
        self.inflight = max(0, self.inflight - 1)
        if st and not self._busy():
            self._apply(st)

    def _apply(self, st):
        self.state.update(st)
        if self.name_override:
            self.state["name"] = self.name_override
        self.refresh_ui()

    def _poll(self):
        if not self._busy():
            self.backend.refresh()

    def refresh_ui(self):
        s = self.state
        on = s["power"]
        self.header.name, self.header.room = s["name"], s.get("room")
        self.power.on = on
        self.hero.on, self.hero.temp, self.hero.mode = on, s["temp"], s["mode"]
        self.hero.fan, self.hero.turbo = s["fan"], s["turbo"]
        self.big.value, self.big.on = s["temp"], on
        self.slider.value, self.slider.on = s["temp"], on
        self.t_mode.icon = s["mode"]
        self.t_mode.value = dict(MODES).get(s["mode"], s["mode"])
        self.t_fan.value = dict(FANS).get(s["fan"], s["fan"])
        self.t_turbo.toggle = s["turbo"]
        self.t_turbo.value = "Ligado" if s["turbo"] else "Desligado"
        for key, chip in self.chips.items():
            chip.on = bool(s.get(key))
            chip.update()
        items = []
        if s.get("humidity") is not None:
            items.append(("Umidade", f"{s['humidity']}%", False))
        if s.get("water_full") is not None:
            items.append(("Tanque", "Cheio" if s["water_full"] else "OK", bool(s["water_full"])))
        if s.get("clean_filter") is not None:
            items.append(("Filtro", "Limpar" if s["clean_filter"] else "OK", bool(s["clean_filter"])))
        self.info.items = items
        self.info.setVisible(bool(items))
        for w in (self.header, self.power, self.hero, self.big, self.slider,
                  self.t_mode, self.t_fan, self.t_turbo, self.info):
            w.update()

    # ----- Mais opções e timer -----
    def toggle_more(self):
        anchor = (self.x() + self.width(), self.y() + self.height())   # antes do layout mexer na janela
        on = not self.side.isVisible()
        self.side.setVisible(on)
        self.footer.more_open = on
        self.footer.update()
        self._fit(anchor)

    def _fit(self, anchor=None):
        """Ajusta o tamanho da janela. O painel lateral cresce para a esquerda,
        mantendo a borda direita e a base no lugar (a altura não aumenta)."""
        right, bottom = anchor or (self.x() + self.width(), self.y() + self.height())
        lay = self.layout()
        lay.activate()
        size = lay.sizeHint()
        if self.isVisible():
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            x = max(screen.availableGeometry().left() + 8, right - size.width())
            self.setGeometry(x, bottom - size.height(), size.width(), size.height())
        else:
            self.resize(size)

    def _set_sleep(self, minutes):
        self.timer_row.sel = minutes
        if minutes:
            self.sleep_end = time.monotonic() + minutes * 60
            self.timer_row.left = minutes * 60
            self.sleep_tick.start()
        else:
            self.sleep_end, self.timer_row.left = None, None
            self.sleep_tick.stop()
        self.timer_row.update()

    def _sleep_tick(self):
        left = self.sleep_end - time.monotonic()
        if left <= 0:
            self._set_sleep(0)
            self.change(power=False)
            return
        self.timer_row.left = left
        self.timer_row.update()

    def _tick(self):
        if self.state["power"]:
            self.hero.advance(0.033)
        self.footer.advance(0.033)

    # ----- comportamento de popup -----
    def event(self, e):
        if e.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            self.close_popup()
        return super().event(e)

    def close_popup(self):
        self.hide()
        self.anim.stop()
        self._hidden_at = time.monotonic()

    def toggle(self):
        if self.isVisible():
            self.close_popup()
        elif time.monotonic() - self._hidden_at > 0.25:
            self.open_popup()

    def open_popup(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self._fit()
        end = QPoint(geo.right() - self.width() - 12, geo.bottom() - self.height() - 12)
        self.setWindowOpacity(0.0)
        self.move(end + QPoint(0, 18))
        self.show()
        self.raise_()
        self.activateWindow()
        a1 = QPropertyAnimation(self, b"windowOpacity", self)
        a1.setDuration(150)
        a1.setStartValue(0.0)
        a1.setEndValue(1.0)
        a2 = QPropertyAnimation(self, b"pos", self)
        a2.setDuration(190)
        a2.setStartValue(end + QPoint(0, 18))
        a2.setEndValue(end)
        a2.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anims = [a1, a2]
        a1.start()
        a2.start()
        self.anim.start()
        self._poll()


# ----------------------------------------------------------------------------
# Ícone da bandeja + main
# ----------------------------------------------------------------------------
def make_tray_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(C("#1e90ff"))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.setBrush(C("#ffffff"))
    p.drawRoundedRect(QRectF(10, 15, 44, 18), 6, 6)
    p.setBrush(C("#0b3a66"))
    p.drawRoundedRect(QRectF(14, 27, 36, 3.5), 1.7, 1.7)
    p.setPen(pen(C("#ffffff", 220), 2.6))
    for x in (18, 32, 46):
        p.drawLine(QPointF(x, 40), QPointF(x, 52))
    p.end()
    return QIcon(pm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="interface sem ar real")
    ap.add_argument("--ip", help="IP do ar (se houver mais de um Gree na rede)")
    ap.add_argument("--name", help="nome mostrado no topo, ex.: Quarto")
    ap.add_argument("--open", action="store_true", help="abre o popup ao iniciar")
    a = ap.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Bandeja do sistema indisponível.")
        return 1

    backend = DemoBackend() if a.demo else GreeBackend(a.ip)
    popup = Popup(backend, a.name)

    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("Ar condicionado")
    menu = QMenu()
    menu.addAction("Abrir", popup.open_popup)
    menu.addSeparator()
    menu.addAction("Sair", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: popup.toggle() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    def tooltip(_=None):
        s = popup.state
        tray.setToolTip(f"{s['name']}: {s['temp']}°C · {'Ligado' if s['power'] else 'Desligado'}")

    backend.state_changed.connect(tooltip)
    backend.push_done.connect(tooltip)

    backend.start()
    if a.open:
        QTimer.singleShot(300, popup.open_popup)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())