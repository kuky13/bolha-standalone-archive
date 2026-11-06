# SPDX-License-Identifier: GPL-3.0-only
"""Prévia local com uma rede descartável, sem acesso ao estado da personagem."""
import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .character import draw_character, draw_reaction_marks, draw_sleep_marks
from .motion import animation_pose


class ExpressionPreview(QWidget):
    def __init__(self, lab):
        super().__init__(lab)
        self.lab = lab
        self.setMinimumHeight(188)
        self.setAccessibleName('Prévia animada da Bolha')

    def paintEvent(self, event):
        pose = self.lab.pose
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        x, y = self.width()/2, self.height()/2
        angle = self.lab.orientation.currentData() + pose['angle_offset']
        scale = .98*pose['visual_scale']
        painter.save()
        painter.setOpacity(pose['body_opacity'])
        draw_character(painter, x, y, scale=scale, angle=angle,
                       emotion=pose['emotion'], blink=pose['blink'],
                       blink_left=pose['blink_left'], blink_right=pose['blink_right'],
                       eye_open=pose['eye_open'], gaze=pose['gaze'] or (0., 0.),
                       squash=pose['squash'], ear_tilt=pose['ear_tilt'],
                       ear_raise=pose['ear_raise'], anger=pose['anger'])
        painter.restore()
        if pose['zzz_strength'] > 0:
            draw_sleep_marks(painter, x, y, scale, pose['zzz_phase'], pose['zzz_strength'],
                             angle, pose['squash'])
        if pose['effect_strength'] > 0:
            draw_reaction_marks(painter, x, y, .98 if pose['effect']=='pop' else scale,
                                pose['effect_phase'], pose['effect'], pose['effect_strength'],
                                angle, 0. if pose['effect']=='pop' else pose['squash'],
                                pose['effect_angle'])
        painter.end()


class ExpressionLab(QWidget):
    """Experimentos reiniciáveis na rede LIF, sem gravação nem sensores do PC."""
    EXPRESSIONS = (
        ('Curiosa', 'curioso'), ('Feliz', 'feliz'), ('Brava', 'bravo'),
        ('Segurada', 'held'), ('Dormindo', 'sleeping'), ('Carinho', 'caress'),
        ('Correndo', 'correndo'), ('Deitada', 'deitada'),
        ('Rebatendo', 'pingpong_rebatida'), ('Estourando', 'pop'), ('Tímida', 'timido'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.started = time.monotonic()
        self.pose = animation_pose('curioso', 0.)
        self.brain = self.senses = self.drives = self.emotion = None
        self.caress_until = self.hold_until = self.next_brain = 0.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.setAccessibleName('Tipo de teste')
        self.mode.addItems(('Animações', 'Sinais e emoções'))
        form.addRow('Testar', self.mode)
        layout.addLayout(form)
        self.preview = ExpressionPreview(self)
        layout.addWidget(self.preview)
        self.expressions = QComboBox()
        self.expressions.setAccessibleName('Expressão da prévia')
        for name, mode in self.EXPRESSIONS:
            self.expressions.addItem(name, mode)
        self.orientation = QComboBox()
        self.orientation.setAccessibleName('Posição da prévia')
        for name, angle in (('Em pé', 0.), ('Deitada à esquerda', -90.),
                            ('Deitada à direita', 90.), ('Invertida', 180.)):
            self.orientation.addItem(name, angle)
        self.animation_controls = QWidget()
        controls = QFormLayout(self.animation_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addRow('Expressão', self.expressions)
        controls.addRow('Posição', self.orientation)
        self.direction = QComboBox()
        self.direction.setAccessibleName('Direção da corrida')
        self.direction.addItem('Para a direita', 1.)
        self.direction.addItem('Para a esquerda', -1.)
        self.direction_label = QLabel('Direção')
        controls.addRow(self.direction_label, self.direction)
        layout.addWidget(self.animation_controls)
        self.brain_controls = QWidget()
        controls = QHBoxLayout(self.brain_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.stimulus = QComboBox()
        self.stimulus.setAccessibleName('Estímulo da simulação')
        for name, channel in (('Carinho', 'caress'), ('Segurar', 'hold'),
                              ('Arremesso', 'throw'), ('Brinquedo perto', 'toy')):
            self.stimulus.addItem(name, channel)
        controls.addWidget(self.stimulus, 1)
        self.apply_stimulus = QPushButton('Aplicar estímulo')
        self.apply_stimulus.clicked.connect(self.stimulate)
        controls.addWidget(self.apply_stimulus)
        layout.addWidget(self.brain_controls)
        self.brain_controls.hide()
        self.readout = QLabel('Escolha uma expressão para ver o movimento.')
        self.readout.setTextFormat(Qt.PlainText)
        self.readout.setWordWrap(True)
        self.readout.setAccessibleName('Resultado do teste')
        layout.addWidget(self.readout)
        self.note = QLabel('A prévia usa os desenhos da Bolha. Seu aprendizado é preservado.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.reset = QPushButton('Recomeçar teste')
        self.reset.clicked.connect(self.restart)
        layout.addWidget(self.reset, 0, Qt.AlignLeft)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.expressions.currentIndexChanged.connect(self.restart)
        self.direction.currentIndexChanged.connect(self.tick)
        self.orientation.currentIndexChanged.connect(self.tick)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.tick()

    def _new_brain(self):
        from pestinha.core.nervous_system import LIFBrain
        from pestinha.core.homeostasis import Drives
        from pestinha.core.emotion import EmotionState
        from pestinha.sense.senses import ComputerSenses
        self.brain = LIFBrain(seed=1313, temperament={'CURIOUS':1.3, 'PLAYFUL':1.2, 'DRAG->FRUSTRATION':.45})
        self.senses, self.drives, self.emotion = ComputerSenses(), Drives(), EmotionState()
        self.caress_until = self.hold_until = self.next_brain = 0.

    def _mode_changed(self):
        neural = self.mode.currentIndex()==1
        self.animation_controls.setVisible(not neural)
        self.brain_controls.setVisible(neural)
        self.note.setText('Simulação temporária de sinais e emoções. Seu aprendizado é preservado.'
                          if neural else 'A prévia usa os desenhos da Bolha. Seu aprendizado é preservado.')
        self.restart()

    def restart(self):
        self.started = time.monotonic()
        if self.mode.currentIndex()==1:
            self._new_brain()
        self.tick()

    def stimulate(self):
        if self.brain is None:
            self._new_brain()
        now = time.monotonic()
        action = self.stimulus.currentData()
        if action=='caress':
            self.caress_until = now+2.
        elif action=='hold':
            self.hold_until = now+3.
        elif action=='throw':
            self.senses.thrown(.8)
        else:
            self.senses.kick('TOY_NEAR', .8)
        self.tick()

    def tick(self):
        now = time.monotonic()
        elapsed = now-self.started
        if self.mode.currentIndex()==1:
            from pestinha import config
            if self.brain is None:
                self._new_brain()
            if now>=self.next_brain:
                self.senses.set_dragging(now<self.hold_until)
                inputs = self.senses.update('IDLE', None, self.drives.channels(), now<self.caress_until)
                self.brain.stimulate(inputs)
                self.brain.step(100)
                rates = self.brain.motor_activity()
                self.emotion.update(rates, .1, config.PROFILES['normal'], now)
                self.brain.learn(.8 if now<self.caress_until else 0., .1, config.PROFILES['normal']['learn_rate'])
                self.next_brain = now+.1
                top = sorted(rates.items(), key=lambda item:item[1], reverse=True)[:3]
                names = {'WATCH':'Observar', 'WANDER':'Passear', 'CHEER':'Alegria',
                         'SETTLE':'Calma', 'DROWSE':'Sono', 'ANGRY':'Irritação',
                         'SAD':'Tristeza', 'STARTLE':'Susto', 'ACEITAR':'Aceitar',
                         'FUGIR':'Fugir', 'CARTAZ':'Protestar', 'CANTO':'Cantinho',
                         'TRAVESSURA':'Travessura', 'PAPEL':'Papel', 'SENTAR':'Sentar'}
                detail = ' · '.join(f'{names.get(name,name)} {rate:.1f} Hz' for name,rate in top)
                self.readout.setText(f'470 neurônios simulados · {self.emotion.current}\n{detail}')
            self.pose = animation_pose(self.emotion.current, elapsed)
        else:
            mode = self.expressions.currentData()
            duration = .75 if mode=='pop' else 1.5 if mode=='pingpong_rebatida' else 6.
            self.pose = animation_pose(mode, elapsed%duration)
            running = mode=='correndo'
            self.direction.setVisible(running)
            self.direction_label.setVisible(running)
            if running:
                direction = self.direction.currentData()
                heading = 0. if direction>0 else 180.
                self.pose['angle_offset'] *= direction
                local = math.radians(heading-self.orientation.currentData()-self.pose['angle_offset'])
                self.pose['gaze'] = (math.cos(local)*.86, math.sin(local)*.86)
                self.pose['effect_angle'] = math.degrees(local)
            self.readout.setText('Escolha uma expressão para ver o movimento.')
        self.preview.update()

    def showEvent(self, event):
        self.started = time.monotonic()
        self.timer.start()
        self.tick()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
