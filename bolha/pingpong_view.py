# SPDX-License-Identifier: GPL-3.0-only
"""Placar e raquete transparentes para o pingue-pongue no desktop."""

import time
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .pet import FLAGS


class PaddleView(QWidget):
    """A face acompanha a região real de contato, sem capturar o mouse."""

    def __init__(self):
        super().__init__(None, FLAGS | Qt.WindowTransparentForInput)
        self.setWindowTitle('Bolha · Raquete')
        self.setAccessibleName('Raquete do ponteiro')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(76, 84)
        self.area = None
        self.radius = 14.
        self.tilt = -22.
        self.flash_until = 0.
        self.previous_cursor = None

    def sync(self, match, cursor, paused, hit=False):
        if (match is None or cursor is None or paused or match.finished
                or not (match.area[0] <= cursor[0] < match.area[2]
                        and match.area[1] <= cursor[1] < match.area[3])):
            self.previous_cursor = None
            self.hide()
            return
        self.area = match.area
        self.radius = match.cursor_radius-match.toy_radius
        if self.previous_cursor is not None:
            dx, dy = cursor[0]-self.previous_cursor[0],cursor[1]-self.previous_cursor[1]
            self.tilt = -22.+max(-12.,min(12.,dx*.65+dy*.25))
        self.previous_cursor = cursor
        if hit:
            self.flash_until = time.monotonic()+.16
        self.move(round(cursor[0]-38),round(cursor[1]-28))
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, event):
        if self.area is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        left,top,right,bottom = self.area
        painter.setClipRect(QRectF(left-self.x(),top-self.y(),right-left,bottom-top))
        painter.translate(38,28)
        painter.rotate(self.tilt)
        radius = self.radius
        # O cabo serve de orientação; apenas a face circular rebate no modelo.
        painter.setPen(QPen(QColor('#251d26'),2.))
        painter.setBrush(QColor('#d8b481'))
        painter.drawRoundedRect(QRectF(-4.,radius-3.,8.,24.),3.,3.)
        painter.setPen(QPen(QColor('#8a5b43'),1.3))
        for y in (radius+7.,radius+11.,radius+15.):
            painter.drawLine(QPointF(-3.,y),QPointF(3.,y))
        painter.setPen(QPen(QColor('#171522'),4.5))
        painter.setBrush(QColor('#e85d72'))
        painter.drawEllipse(QRectF(-radius,-radius,2*radius,2*radius))
        painter.setPen(QPen(QColor('#ffe3a3'),1.5))
        painter.drawEllipse(QRectF(-radius,-radius,2*radius,2*radius))
        painter.setPen(QPen(QColor('#ffacb4'),1.6))
        painter.drawArc(QRectF(-radius+3.,-radius+3.,2*radius-6.,2*radius-6.),35*16,92*16)
        flash = max(0.,min(1.,(self.flash_until-time.monotonic())/.16))
        if flash:
            painter.setPen(QPen(QColor(255,240,183,round(225*flash)),2.))
            painter.setBrush(Qt.NoBrush)
            extent=radius+2.+3.*(1.-flash)
            painter.drawEllipse(QRectF(-extent,-extent,extent*2,extent*2))
        painter.end()


class PingPongView(QWidget):
    """Show status without covering the toy, pet, or pointer interaction."""

    def __init__(self):
        super().__init__(None, FLAGS | Qt.WindowTransparentForInput)
        self.setWindowTitle('Bolha · Pingue-pongue')
        self.setAccessibleName('Placar do pingue-pongue da Bolha')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMouseTracking(False)
        self._match = None
        self._paused = False
        self._frame_key = None
        self.paddle = PaddleView()
        self._last_rally = 0

    def sync(self, match, paused=False, cursor=None):
        hit = (match is self._match and match is not None
               and match.rally>self._last_rally and match.vx<0)
        self._match = match
        self._paused = bool(paused)
        self._last_rally = match.rally if match else 0
        self.paddle.sync(match,cursor,self._paused,hit)
        if match is None:
            if self.isVisible():
                self.hide()
            self._frame_key = None
            return
        left, top, right, _ = match.area
        width = round(min(360.,right-left-24.))
        geometry = round((left+right-width)/2),round(top+12),width,64
        key = (match.player_score, match.pet_score, match.rally, match.best,
               match.serve_delay > 0, match.finished, match.winner, self._paused, geometry)
        if self.geometry().getRect() != geometry:
            self.setGeometry(*geometry)
        if not self.isVisible():
            self.show()
        if key != self._frame_key:
            self._frame_key = key
            self.update()

    def _font(self, size, bold):
        return QFont(self.font().family(), size, QFont.Bold if bold else QFont.Medium)

    def _label(self, painter, rect, text, *, size, bold=False, color=QColor(255,255,255)):
        font = self._font(size, bold)
        width = QFontMetricsF(font).horizontalAdvance(text)
        if width > rect.width():
            font.setPointSizeF(max(7., size * (rect.width()-4) / width))
        painter.setFont(font)
        painter.setPen(QColor(0,0,0,190))
        painter.drawText(rect.translated(0,1), Qt.AlignCenter, text)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        match = self._match
        if match is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._paused:
            instruction = 'Pausado · volte à tela ou feche o menu'
        elif match.finished:
            instruction = ('Você venceu! · feche pelo menu da Bolha' if match.winner == 'player'
                           else 'A Bolha venceu · feche pelo menu da Bolha')
        elif match.serve_delay > 0:
            instruction = 'Saque · prepare a raquete'
        else:
            instruction = 'Rebata o brinquedo com a raquete'

        score = f'VOCÊ  {match.player_score}   ·   {match.pet_score}  BOLHA'
        stats = f'TROCAS {match.rally}   ·   RECORDE {match.best}'
        panel = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(9,17,29,178))
        painter.drawRoundedRect(panel, 17, 17)
        self._label(painter, QRectF(panel.left()+10,panel.top()+4,panel.width()-20,20), score,
                    size=12,bold=True)
        self._label(painter, QRectF(panel.left()+10,panel.top()+24,panel.width()-20,17), stats,
                    size=9,color=QColor(218,230,243))
        self._label(painter, QRectF(panel.left()+8,panel.top()+42,panel.width()-16,18), instruction,
                    size=9,bold=True,color=QColor(255,255,255))
        painter.end()

    def hideEvent(self, event):
        self.paddle.hide()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.paddle.close()
        super().closeEvent(event)
