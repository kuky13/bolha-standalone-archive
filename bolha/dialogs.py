# SPDX-License-Identifier: GPL-3.0-only
"""Diálogos locais, abertos pelo controlador somente quando solicitados.

Controller: store.preferences; save_preferences(patch)/reset_appearance() -> dict;
startup_enabled()/set_startup(bool)/reset_learning() -> bool; diagnostics_text()
-> str; show_neural(); game; updater.state/changed/check()/defer(). Gravações que
falham lançam OSError/ValueError e preservam os dados anteriores. False retornado
por set_startup(False) significa sucesso, não erro. Os diálogos não alteram a
física nem game.panel: o controlador acompanha QDialog.finished.
reset_learning() True confirma a solicitação de backup/reinício, cuja conclusão
é assíncrona; falhas posteriores ficam no diagnóstico do controlador.
"""
import math
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QVBoxLayout, QWidget, QDoubleSpinBox, QToolButton,
)
from . import VERSION
from .preferences import DEFAULTS, OBJECT_SCALE_TYPES


def _label(text=''):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


def _number(value, default=0.):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError, OverflowError):
        return default


def _fit(dialog, width, height):
    area = QApplication.primaryScreen().availableGeometry()
    dialog.setMinimumSize(min(430, area.width()-24), min(380, area.height()-48))
    dialog.resize(min(width, area.width()-24), min(height, area.height()-48))


def _button(text, callback):
    button = QPushButton(text)
    button.setAutoDefault(False)
    button.clicked.connect(callback)
    return button


class SettingsDialog(QDialog):
    """Aplicar salva somente campos editados, preservando sensores e precisão."""
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle('Central da Bolha')
        self.setAccessibleName('Central da Bolha')
        self._loading = True
        self.checks = {}
        self.baseline = {}
        self.startup = False
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('Áreas da central da Bolha')
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        self._appearance_tab()
        self._behavior_tab()
        self._test_tab()
        self._privacy_tab()
        self._app_tab()
        self.status = _label()
        self.status.setMinimumHeight(32)
        self.status.setAccessibleName('Resultado das configurações')
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText('&Aplicar')
        self.apply_button.clicked.connect(self.apply_changes)
        buttons.button(QDialogButtonBox.Close).setText('&Fechar')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load(controller.store.preferences)
        try:
            self.startup = bool(controller.startup_enabled())
        except (OSError, ValueError):
            self.autostart.setEnabled(False)
            self._status('Não consegui consultar a inicialização com o Windows.', True)
        self.autostart.setChecked(self.startup)
        self._loading = False
        self._dirty()
        if getattr(controller.store, 'error', ''):
            self._status(controller.store.error, True)
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(1000)
        self.update_timer.timeout.connect(self.refresh_update)
        controller.updater.changed.connect(self.refresh_update)
        _fit(self, 610, 550)

    def _tab(self, title):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)
        return layout

    def _check(self, key, text, layout, description=''):
        control = QCheckBox(text)
        control.setObjectName(key)
        control.setAccessibleName(text)
        control.setToolTip(description)
        control.toggled.connect(self._dirty)
        self.checks[key] = control
        layout.addWidget(control)
        return control

    def _details(self, title, layout):
        toggle = QToolButton()
        toggle.setText(title)
        toggle.setAccessibleName(title)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)
        toggle.setCheckable(True)
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(16, 8, 0, 4)
        inner.setSpacing(10)
        body.hide()
        toggle.toggled.connect(body.setVisible)
        toggle.toggled.connect(lambda opened: toggle.setArrowType(Qt.DownArrow if opened else Qt.RightArrow))
        layout.addWidget(toggle)
        layout.addWidget(body)
        return inner

    def _spin(self, low, high, suffix, name):
        control = QSpinBox()
        control.setRange(low, high)
        control.setSuffix(suffix)
        control.setAccessibleName(name)
        control.valueChanged.connect(self._dirty)
        return control

    def _appearance_tab(self):
        layout = self._tab('Bolha')
        self._general_layout = layout
        layout.addWidget(_label('Sua companhia na área de trabalho.'))
        form = QFormLayout()
        self.avatar_size = self._spin(48, 200, ' px', 'Tamanho da Bolha')
        self.opacity = self._spin(20, 100, ' %', 'Opacidade da Bolha')
        form.addRow('&Tamanho:', self.avatar_size)
        self.toy_appearance=QComboBox()
        self.toy_appearance.setAccessibleName('Aparência do brinquedo')
        self.toy_appearance.addItem('Amendoim','peanut')
        self.toy_appearance.addItem('Bolinha original','ball')
        self.toy_appearance.currentIndexChanged.connect(self._dirty)
        form.addRow('&Brinquedo:',self.toy_appearance)
        layout.addLayout(form)
        self._check('roaming', 'Passear pela tela', layout,
                    'O passeio pausa durante o arrasto, o carinho e o uso dos painéis.')
        self._check('mischiefEnabled', 'Trazer memes e bilhetes', layout)
        appearance = self._details('Tamanhos e aparência', layout)
        advanced_form = QFormLayout()
        advanced_form.addRow('&Opacidade:', self.opacity)
        appearance.addLayout(advanced_form)
        self.object_scales = {}
        object_names = {'toy':'Brinquedo', 'notebook':'Caderno', 'reaction':'Reações',
                        'note':'Bilhetes', 'sign':'Placas', 'corner':'Cantinho', 'effects':'Efeitos'}
        appearance.addWidget(_label('Os objetos acompanham a Bolha. Ajuste cada tipo se precisar.'))
        for kind in OBJECT_SCALE_TYPES:
            control = QDoubleSpinBox()
            control.setRange(.6, 1.8)
            control.setSingleStep(.1)
            control.setDecimals(1)
            control.setSuffix('×')
            control.setAccessibleName(f'Tamanho: {object_names[kind]}')
            control.valueChanged.connect(self._dirty)
            self.object_scales[kind] = control
            advanced_form.addRow(f'{object_names[kind]}:', control)
        appearance.addWidget(_button('Restaurar tamanho e opacidade', self.reset_appearance))

    def _behavior_tab(self):
        layout = self._details('Comportamento e aprendizado', self._general_layout)
        self._check('popEnabled', 'Estourar após muitos arremessos fortes', layout,
                    'A contagem considera arremessos fortes numa janela de 1 minuto. A Bolha volta após 30 segundos.')
        pop_form = QFormLayout()
        self.pop_throw_limit = self._spin(5, 30, '', 'Arremessos fortes para estourar')
        pop_form.addRow('&Limite de arremessos fortes:', self.pop_throw_limit)
        layout.addLayout(pop_form)
        self._check('onlineReactions', 'Buscar memes e GIFs online', layout,
                    'Consulta ReactionGIFs e Nekos.best apenas com termos genéricos de humor; mídia fica só em memória.')
        form = QFormLayout()
        self.interval = self._spin(1, 30, ' min', 'Intervalo mínimo entre travessuras')
        self.object_limit = self._spin(1, 5, '', 'Máximo de objetos na tela')
        form.addRow('Intervalo &mínimo:', self.interval)
        form.addRow('Máximo de &objetos:', self.object_limit)
        layout.addLayout(form)
        self.checks['mischiefEnabled'].toggled.connect(self.interval.setEnabled)
        self.checks['mischiefEnabled'].toggled.connect(self.object_limit.setEnabled)
        self.checks['mischiefEnabled'].toggled.connect(self.checks['onlineReactions'].setEnabled)
        self.checks['popEnabled'].toggled.connect(self.pop_throw_limit.setEnabled)
        self._check('adaptiveBehavior', 'Usar objetivos e aprendizado adaptativo', layout)
        self._check('learnRoutine', 'Aprender hábitos por horário', layout)
        layout.addWidget(_label('O aprendizado fica neste computador. Desativar preserva a memória.'))
        self._general_layout.addStretch()

    def _test_tab(self):
        from .expression_lab import ExpressionLab
        layout = self._tab('Testar')
        self.lab = ExpressionLab()
        layout.addWidget(self.lab)
        layout.addWidget(_button('Ver o cérebro da minha Bolha', self.controller.show_neural))
        layout.addStretch()

    def _privacy_tab(self):
        layout = self._tab('Privacidade')
        layout.addWidget(_label('Escolha quais sinais locais a Bolha pode usar para entender o contexto. Cada leitura pode ser desligada separadamente.'))
        for key, text, description in (
            ('senseApp', 'Programa ativo', 'Lê o nome do processo, sem ler o título ou o conteúdo da janela.'),
            ('senseIdle', 'Tempo sem interação', 'Usa o tempo ocioso informado pelo sistema, sem registrar teclas.'),
            ('senseCursor', 'Posição do ponteiro', 'Usa a posição do ponteiro para reagir à sua presença.'),
            ('senseWindows', 'Posição e tamanho das janelas', 'Usa a geometria para pousar e evitar telas cheias, sem capturar imagens.'),
        ):
            self._check(key, text, layout, description)
        layout.addWidget(_label('Cada leitura pode ser desligada separadamente. Memes online usam só termos genéricos de humor; imagens ficam na memória RAM.'))
        layout.addStretch()

    def _app_tab(self):
        layout = self._tab('App')
        layout.addWidget(_label(f'Bolha {VERSION}'))
        self.autostart = QCheckBox('Iniciar com o Windows')
        self.autostart.setAccessibleName('Iniciar com o Windows')
        self.autostart.toggled.connect(self._dirty)
        layout.addWidget(self.autostart)
        self.update_label = _label()
        self.update_label.setAccessibleName('Estado da atualização')
        layout.addWidget(self.update_label)
        row = QHBoxLayout()
        self.check_update = _button('Verificar atualizações', self._check_update)
        self.defer_update = _button('Adiar por 1 hora', self._defer_update)
        row.addWidget(self.check_update)
        row.addWidget(self.defer_update)
        layout.addLayout(row)
        layout.addWidget(_label('Consulta ao abrir e a cada seis horas.'))
        maintenance = self._details('Diagnóstico e manutenção', layout)
        maintenance.addWidget(_button('Copiar diagnóstico local', self.copy_diagnostics))
        maintenance.addWidget(_label('O relatório fica local. Você escolhe onde compartilhar.'))
        maintenance.addWidget(_button('Apagar aprendizado…', self.reset_learning))
        layout.addStretch()

    def _values(self):
        return dict({key: control.isChecked() for key, control in self.checks.items()},
                    avatarSize=self.avatar_size.value(), opacity=self.opacity.value()/100,
                    objectScales={key: control.value() for key, control in self.object_scales.items()},
                    toyAppearance=self.toy_appearance.currentData(),
                    mischiefInterval=self.interval.value()*60, maxObjects=self.object_limit.value(),
                    popThrowLimit=self.pop_throw_limit.value())

    def _load(self, preferences, appearance_only=False):
        loading = self._loading
        self._loading = True
        values = dict(DEFAULTS, **preferences)
        self.avatar_size.setValue(int(values['avatarSize']))
        self.opacity.setValue(round(values['opacity']*100))
        scales = dict(DEFAULTS.get('objectScales', {}), **values.get('objectScales', {}))
        for key, control in self.object_scales.items():
            control.setValue(float(scales.get(key, 1.0)))
        if not appearance_only:
            self.toy_appearance.setCurrentIndex(self.toy_appearance.findData(values['toyAppearance']))
            self.interval.setValue(max(1, round(values['mischiefInterval']/60)))
            self.object_limit.setValue(int(values['maxObjects']))
            self.pop_throw_limit.setValue(int(values['popThrowLimit']))
            for key, control in self.checks.items():
                control.setChecked(values[key])
            self.interval.setEnabled(values['mischiefEnabled'])
            self.object_limit.setEnabled(values['mischiefEnabled'])
            self.checks['onlineReactions'].setEnabled(values['mischiefEnabled'])
            self.pop_throw_limit.setEnabled(values['popEnabled'])
        rendered = self._values()
        for key in ('avatarSize', 'opacity') if appearance_only else rendered:
            self.baseline[key] = rendered[key]
        self._loading = loading

    def _dirty(self, *_):
        if not self._loading:
            self.apply_button.setEnabled(self._values() != self.baseline or self.autostart.isChecked() != self.startup)

    def _status(self, text, error=False):
        self.status.setText(text)
        palette = self.palette()
        if error:
            palette.setColor(QPalette.WindowText, QColor('#9d202d' if palette.color(QPalette.Window).lightness() > 128 else '#f2b4bd'))
        self.status.setPalette(palette)

    def apply_changes(self):
        patch = {key: value for key, value in self._values().items() if self.baseline.get(key) != value}
        try:
            if patch:
                self._load(self.controller.save_preferences(patch))
            requested = self.autostart.isChecked()
            if requested != self.startup:
                actual = self.controller.set_startup(requested)
                if actual is not requested:
                    raise OSError('O Windows não confirmou a alteração.')
                self.startup = actual
        except (OSError, ValueError) as error:
            self._status(f'Não consegui concluir as alterações: {error}. Os dados já salvos foram preservados.', True)
            self._dirty()
            return
        self._dirty()
        self._status('Preferências salvas neste computador.')

    def reset_appearance(self):
        try:
            self._load(self.controller.reset_appearance(), appearance_only=True)
        except (OSError, ValueError) as error:
            self._status(f'Não consegui restaurar a aparência: {error}. Os dados anteriores foram preservados.', True)
            return
        self._dirty()
        self._status('Tamanho e opacidade restaurados. As outras preferências foram mantidas.')

    def copy_diagnostics(self):
        try:
            QApplication.clipboard().setText(self.controller.diagnostics_text())
        except (OSError, ValueError) as error:
            self._status(f'Não consegui preparar o diagnóstico: {error}.', True)
            return
        self._status('Diagnóstico copiado. Você escolhe onde compartilhar.')

    def reset_learning(self):
        question = QMessageBox(self)
        question.setWindowTitle('Apagar aprendizado da Bolha')
        question.setText('Reiniciar a memória, os hábitos e as associações aprendidas?')
        question.setInformativeText('As preferências serão mantidas. Essa ação só acontece após a confirmação.')
        erase = question.addButton('Apagar aprendizado', QMessageBox.DestructiveRole)
        cancel = question.addButton('Cancelar', QMessageBox.RejectRole)
        question.setDefaultButton(cancel)
        question.exec()
        if question.clickedButton() is not erase:
            return
        try:
            if not self.controller.reset_learning():
                raise OSError('Não foi possível concluir a gravação.')
        except (OSError, ValueError) as error:
            self._status(f'Não consegui reiniciar o aprendizado: {error}. Confira o diagnóstico local.', True)
            return
        self._status('Reinício solicitado. A Bolha guarda o backup antes de reiniciar; qualquer falha aparecerá no diagnóstico.')

    def _check_update(self):
        self.controller.updater.check()
        self.refresh_update()

    def _defer_update(self):
        self.controller.updater.defer()
        self.refresh_update()

    def refresh_update(self, *_):
        if not self.isVisible():
            return
        state = self.controller.updater.state
        phase = state.get('phase', 'idle')
        message = state.get('message')
        descriptions = dict(idle='Nenhuma atualização pendente.', checking='Consultando o GitHub…',
                            downloading=f"Baixando atualização: {max(0, min(100, _number(state.get('percent')))):.0f}%.",
                            ready=f"Versão {state.get('version', '')} pronta para instalar.",
                            verifying='Conferindo o instalador…', installing='Instalando. A Bolha será reaberta.',
                            error='A atualização falhou. Você pode continuar usando esta versão.')
        text = str(message or descriptions.get(phase, 'Aguardando atualização.'))
        deadline = _number(state.get('installAt'))
        if phase == 'ready' and deadline:
            seconds = max(0, math.ceil((deadline-time.time()*1000)/1000))
            text += f' Instalação em {seconds} s.' if seconds <= 60 else f' Instalação em {math.ceil(seconds/60)} min.'
        self.update_label.setText(text)
        self.check_update.setEnabled(phase in ('idle', 'error'))
        self.defer_update.setVisible(phase == 'ready')
        self.defer_update.setEnabled(phase == 'ready')

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_update()
        self.update_timer.start()

    def hideEvent(self, event):
        self.update_timer.stop()
        super().hideEvent(event)


class NeuralCanvas(QWidget):
    """Rede LIF real agrupada por pool; arestas vêm da matriz sináptica real."""
    COLORS = ('#ffd166', '#75c8ff', '#d1a5ff', '#8ee0b0')
    POOL_LABELS = {
        'MOTION':'Movimento', 'TYPING':'Teclado', 'NOVELTY':'Novidade', 'SILENCE':'Silêncio',
        'WORK':'Trabalho', 'PLAY':'Jogo', 'SOUND':'Som', 'SOCIAL':'Conversa', 'WEB':'Navegador',
        'FATIGUE':'Cansaço', 'POKE':'Cutucada', 'DRAG':'Arrasto', 'DISMISS':'Dispensa',
        'LONELY':'Carência', 'CARESS':'Carinho', 'ANTICIPATE':'Antecipação', 'TOY_NEAR':'Brinquedo perto',
        'TOY_TAKEN':'Brinquedo levado', 'THROW':'Arremesso', 'IMPACT':'Impacto', 'BOREDOM':'Tédio',
        'PEDIDO':'Pedido', 'PRESO':'Preso', 'LEMBRA_FUGA':'Lembra fuga', 'RECUSA':'Recusa',
        'PLACA':'Placa', 'ANTECIPA_PLACA':'Prevê placa', 'VISITA':'Visita', 'RECEIO':'Receio',
        'RANCOR':'Rancor', 'ALERT':'Alerta', 'FOCUS':'Foco', 'CURIOUS':'Curiosidade',
        'PLAYFUL':'Brincadeira', 'CALM':'Calma', 'TIRED':'Cansaço', 'QUIET':'Inibição suave',
        'INHIB':'Inibição', 'FRUSTRATION':'Frustração', 'GLOOM':'Tristeza', 'STARTLE':'Susto',
        'WATCH':'Observar', 'WANDER':'Passear', 'CHEER':'Animar', 'SETTLE':'Acalmar',
        'DROWSE':'Dormir', 'ANGRY':'Irritação', 'SAD':'Tristeza', 'SENTAR':'Sentar',
        'FUGIR':'Fugir', 'CARTAZ':'Cartaz', 'CANTO':'Cantinho', 'TRAVESSURA':'Travessura',
        'PAPEL':'Bolinha de papel', 'ACEITAR':'Aceitar',
    }

    def __init__(self):
        super().__init__()
        self.points = []
        self.pools = []
        self.weights = None
        self.selected_pool = None
        self.filter_kind = None
        self._edge_token = None
        self.edges = []
        self.setMinimumSize(280, 180)
        self.setAccessibleName('Atividade dos neurônios da Bolha')

    def set_network(self, positions, trace, kind, pools=(), weights=None):
        points = []
        for position, activity, category in zip(positions, trace, kind):
            if len(position) < 2:
                continue
            x, y = _number(position[0], .5), _number(position[1], .5)
            points.append((max(0., min(1., x)), max(0., min(1., y)),
                           max(0., min(1., _number(activity))), int(_number(category)) % 4))
        raw_pools = [(str(pool.get('name', 'Grupo')), int(pool.get('start', 0)),
                      int(pool.get('n', 0)), str(pool.get('group', 'inter')),
                      str(pool.get('kind', 'exc')))
                      for pool in pools if isinstance(pool, dict)]
        # Brain positions are clipped at the canvas boundary by the model. Lay
        # out existing indices by their real pool/type so overlaps are not shown
        # as if they were spatial anatomy. This changes display coordinates only.
        ranks = {}
        totals = {}
        sensory_index = 0
        pool_columns = {}
        for name, _, _, group, kind in raw_pools:
            if group == 'sensory':
                column = 'sensory_a' if sensory_index < 15 else 'sensory_b'
                sensory_index += 1
            else:
                column = 'motor' if group == 'motor' else 'inhib' if kind == 'inh' else 'exc'
            pool_columns[name] = column
            ranks[name] = totals.get(column, 0)
            totals[column] = ranks[name] + 1
        columns = {'sensory_a':.20, 'sensory_b':.40, 'exc':.60, 'inhib':.80, 'motor':.99}
        for name, start, count, group, kind in raw_pools:
            column = pool_columns[name]
            cy = .12 + (ranks[name] / max(1, totals[column]-1))*.76
            cx = columns[column]
            cols = min(4, max(1, int(math.ceil(math.sqrt(max(1, count))))))
            rows = int(math.ceil(count / cols))
            for offset in range(count):
                index = start + offset
                if index >= len(points):
                    break
                col, row = offset % cols, offset // cols
                points[index] = (max(.01, min(.99, cx + (col-(cols-1)/2)*.012)),
                                 max(.015, min(.985, cy + .025 + (row-(rows-1)/2)*.012)),
                                 points[index][2], points[index][3])
        self.points = points
        self.pools = [(name, start, count, group, kind,
                       columns[pool_columns[name]],
                       .12 + (ranks[name] / max(1, totals[pool_columns[name]]-1))*.76)
                      for name, start, count, group, kind in raw_pools]
        self.weights = weights
        self._pool_rank_cache = None
        self._prepare_edges()
        self.update()

    def set_selection(self, pool=None, kind=None):
        self.selected_pool, self.filter_kind = pool, kind
        self._prepare_edges()
        self.update()

    def _prepare_edges(self):
        pool = next((item for item in self.pools if item[0] == self.selected_pool), None)
        token = (id(self.weights), self.selected_pool, len(self.points))
        if token == self._edge_token:
            return
        self._edge_token = token
        self.edges = []
        if pool is None or self.weights is None:
            return
        _, start, count, _, _, _, _ = pool
        try:
            candidates = []
            for source in range(start, min(start + count, len(self.points))):
                for target, weight in enumerate(self.weights[source]):
                    weight = _number(weight)
                    if abs(weight) >= .06 and target < len(self.points):
                        candidates.append((abs(weight), source, target, weight))
            candidates.sort(reverse=True)
            self.edges = [(self.points[source][:2], self.points[target][:2], weight)
                          for _, source, target, weight in candidates[:70]]
        except (IndexError, TypeError, ValueError):
            self.edges = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(Qt.NoPen)
        bounds = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        from PySide6.QtGui import QPen, QFont
        painter.setFont(QFont(self.font().family(), 8))
        painter.setPen(self.palette().text().color())
        painter.drawText(QPointF(bounds.left()+bounds.width()*.27, bounds.top()+12), 'Sensores')
        painter.drawText(QPointF(bounds.left()+bounds.width()*.53, bounds.top()+12), 'Excitação')
        painter.drawText(QPointF(bounds.left()+bounds.width()*.73, bounds.top()+12), 'Inibição')
        painter.drawText(QPointF(bounds.left()+bounds.width()*.90, bounds.top()+12), 'Ações')
        painter.setFont(QFont(self.font().family(), 8))
        for name, start, count, group, kind, x, y in self.pools:
            selected = self.selected_pool == name
            label = self.POOL_LABELS.get(name, name)
            px, py = bounds.left()+x*bounds.width(), bounds.top()+y*bounds.height()
            painter.setPen(QPen(QColor('#f3f0f8' if selected else '#aaa5b7'), 1,
                                Qt.SolidLine if selected else Qt.DotLine))
            painter.drawText(QRectF(px-130, py-10, 102, 15), Qt.AlignRight | Qt.AlignVCenter, label)
            if selected:
                painter.setPen(QPen(self.palette().text().color(), 1, Qt.DotLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(px, py+7), 22, 10)
        for a, b, weight in self.edges:
            color = QColor('#67c7f2' if weight > 0 else '#e092c4')
            color.setAlpha(115)
            painter.setPen(QPen(color, min(2.2, .7 + abs(weight)*7)))
            painter.drawLine(QPointF(bounds.left()+a[0]*bounds.width(), bounds.top()+a[1]*bounds.height()),
                             QPointF(bounds.left()+b[0]*bounds.width(), bounds.top()+b[1]*bounds.height()))
        for index, (x, y, activity, category) in enumerate(self.points):
            if self.filter_kind is not None and category != self.filter_kind:
                continue
            color = QColor(self.COLORS[category])
            in_selected = self.selected_pool is None or any(
                name == self.selected_pool and start <= index < start + count
                for name, start, count, *_ in self.pools)
            color.setAlphaF((.25 + .75*activity) if in_selected else .18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            radius = 1.8 + activity*1.8
            painter.drawEllipse(QPointF(bounds.left()+x*bounds.width(), bounds.top()+y*bounds.height()), radius, radius)
        painter.end()


class NeuralDialog(QDialog):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._notice_until = 0.
        self.setWindowTitle('Cérebro da Bolha')
        self.setAccessibleName('Painel neural da Bolha')
        layout = QVBoxLayout(self)
        self.emotion = _label('Aguardando o estado da Bolha…')
        self.emotion.setAccessibleName('Emoção atual')
        layout.addWidget(self.emotion)
        row = QHBoxLayout()
        self.drives = {}
        for key, title in (('energy', 'Energia'), ('contact', 'Carência'), ('stimulation', 'Estímulo')):
            column = QVBoxLayout()
            column.addWidget(_label(title))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setAccessibleName(title)
            column.addWidget(bar)
            row.addLayout(column)
            self.drives[key] = bar
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('Informações do cérebro')
        layout.addWidget(self.tabs, 1)
        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        controls = QHBoxLayout()
        self.group_filter = QComboBox()
        self.group_filter.setAccessibleName('Selecionar grupo neural')
        self.group_filter.addItem('Toda a rede', None)
        self.group_filter.currentIndexChanged.connect(self._selection_changed)
        self.kind_filter = QComboBox()
        self.kind_filter.setAccessibleName('Filtrar tipo de neurônio')
        self.kind_filter.addItem('Todos os tipos', None)
        for kind, name in enumerate(('Sensor', 'Excitação', 'Inibição', 'Ação')):
            self.kind_filter.addItem(name, kind)
        self.kind_filter.currentIndexChanged.connect(self._selection_changed)
        controls.addWidget(self.group_filter)
        controls.addWidget(self.kind_filter)
        activity_layout.addLayout(controls)
        self.network_title = _label()
        activity_layout.addWidget(self.network_title)
        self.canvas = NeuralCanvas()
        self.canvas.setToolTip('A posição agrupa pools por tipo para facilitar a leitura. Não representa localização anatômica. Pontos, rastros e sinapses são do brain ativo.')
        activity_layout.addWidget(self.canvas, 1)
        activity_layout.addWidget(_label('Cada ponto é um neurônio. O brilho mostra seu rastro de atividade.'))
        activity_layout.addWidget(_label('Amarelo: sensores · Azul: excitação · Roxo: inibição · Verde: ação. O arranjo visual separa pools; não é anatômico.'))
        self.rates = _label()
        activity_layout.addWidget(self.rates)
        self.tabs.addTab(activity, 'Atividade')
        groups = QWidget()
        groups_layout = QVBoxLayout(groups)
        groups_layout.addWidget(_label('Grupos neurais com maior atividade, em disparos por segundo.'))
        self.pools = QTableWidget(0, 2)
        self.pools.setAccessibleName('Atividade dos grupos neurais')
        self.pools.setHorizontalHeaderLabels(['Grupo', 'Atividade (Hz)'])
        self.pools.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pools.verticalHeader().hide()
        self.pools.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pools.cellClicked.connect(self._pool_row_selected)
        groups_layout.addWidget(self.pools)
        self.tabs.addTab(groups, 'Grupos')
        self.learning = QPlainTextEdit()
        self.learning.setReadOnly(True)
        self.learning.setAccessibleName('Objetivos, hábitos e associações aprendidas')
        self.tabs.addTab(self.learning, 'Aprendizado')
        self.decision = _label('Aguardando uma decisão real do cérebro…')
        self.decision.setAccessibleName('Decisão e fatores do cérebro')
        activity_layout.addWidget(self.decision)
        diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics)
        self.metrics = _label()
        diagnostics_layout.addWidget(self.metrics)
        diagnostics_layout.addWidget(_label('RSS mede este aplicativo inteiro. A estimativa dos arrays inclui seus buffers NumPy, sem objetos e bibliotecas. Os arrays já fazem parte do RSS: não some essas medidas.'))
        diagnostics_layout.addWidget(_button('Copiar diagnóstico local', self.copy_diagnostics))
        self.reaction_button = _button('Mostrar uma reação agora', self.request_reaction)
        diagnostics_layout.addWidget(self.reaction_button)
        self.reaction_status = _label('Nenhum pedido de reação enviado.')
        self.reaction_status.setAccessibleName('Resultado do pedido de reação')
        diagnostics_layout.addWidget(self.reaction_status)
        diagnostics_layout.addStretch()
        self.tabs.addTab(diagnostics, 'Diagnóstico')
        self.status = _label()
        self.status.setAccessibleName('Estado do painel neural')
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('&Fechar')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        _fit(self, 800, 700)

    @staticmethod
    def _rates(values, limit=8):
        return sorted(((str(key), max(0., _number(value))) for key, value in values.items()),
                      key=lambda pair: pair[1], reverse=True)[:limit]

    def refresh(self):
        if not self.isVisible() or self.isMinimized():
            return
        try:
            game = self.controller.game
            brain = game.brain
            self.canvas.set_network(brain.pos, brain.trace, brain.kind,
                                    getattr(brain, 'pools', ()), getattr(brain, 'W', None))
            if self.group_filter.count() != len(self.canvas.pools) + 1:
                selected = self.group_filter.currentData()
                self.group_filter.blockSignals(True)
                self.group_filter.clear()
                self.group_filter.addItem('Toda a rede', None)
                for name, *_ in self.canvas.pools:
                    self.group_filter.addItem(self.canvas.POOL_LABELS.get(name, name), name)
                self.group_filter.setCurrentIndex(max(0, self.group_filter.findData(selected)))
                self.group_filter.blockSignals(False)
            self._selection_changed()
            emotion = dict(curioso='Curiosa', bravo='Brava', assustado='Assustada',
                           dramatico='Dramática', dormindo='Dormindo', sonolento='Sonolenta',
                           timido='Tímida', atento='Atenta', entediado='Entediada',
                           travesso='Travessa').get(game.state.emotion, str(game.state.emotion).capitalize())
            activity = dict(IDLE='Em pausa', AWAY='Ausente', PROGRAMMING='Programação',
                            DESIGNING='Criação', GAMING='Jogo', BROWSING='Navegação',
                            SOCIAL='Conversa', MUSIC='Mídia').get(game.activity, 'Outro contexto')
            self.emotion.setText(f'Emoção: {emotion} · Contexto: {activity}')
            self.network_title.setText(f'Rede local · {brain.N} neurônios')
            for key, bar in self.drives.items():
                bar.setValue(round(max(0., min(1., _number(getattr(game.drives, key))))*100))
            self.rates.setText('Impulsos: ' + ' · '.join(f'{key}: {value:.1f} Hz' for key, value in self._rates(game.rates, 3)))
            rates = self._rates(brain.pool_rates())
            self.pools.setRowCount(len(rates))
            for row, (name, value) in enumerate(rates):
                display_name = NeuralCanvas.POOL_LABELS.get(name, name)
                for col, text in enumerate((display_name, f'{value:.1f}')):
                    item = self.pools.item(row, col)
                    if item is None:
                        item = QTableWidgetItem(text)
                        if col == 0:
                            item.setData(Qt.UserRole, name)
                        self.pools.setItem(row, col, item)
                    elif item.text() != text:
                        item.setText(text)
            summary = game.intelligence.summary(game.activity, time.time())
            snapshot_fn = getattr(game, 'decision_snapshot', None)
            snapshot = snapshot_fn() if callable(snapshot_fn) else {}
            current = snapshot.get('current') if isinstance(snapshot, dict) else None
            previous_decision = False
            history = snapshot.get('history', []) if isinstance(snapshot, dict) else []
            if not isinstance(current, dict) and history and isinstance(history[-1], dict):
                current = history[-1]
                previous_decision = True
            if isinstance(current, dict):
                factors = current.get('factors', {})
                action_names = {'watch':'observar', 'explore':'explorar', 'attention':'pedir atenção',
                                'rest':'descansar', 'play':'brincar', 'work':'trabalhar',
                                'request_refused':'pedido recusado', 'attempt_online_reaction':'pedir uma reação online',
                                'blink':'piscar', 'wink':'piscadinha', 'stretch':'espreguiçar',
                                'sneeze':'espirrar', 'hiccup':'soluçar', 'doze':'cochilar', 'ear_wiggle':'sacudir orelhas',
                                'roam_move':'movimento do passeio', 'roam_target':'destino do passeio',
                                'roam_duration':'pausa do passeio', 'gaze_target':'direção do olhar',
                                'gaze_point':'ponto observado', 'continue_roam':'continuar o passeio',
                                'celebration':'comemorar', 'toy_play':'brincar com o brinquedo',
                                'toy_return':'devolver o brinquedo',
                                'sleep_cycle':'sono', 'mischief':'travessura', 'paper_throw':'jogar papel',
                                'punishment_sign':'mostrar cartaz', 'punishment_sign_text':'texto do cartaz',
                                'accept_punishment':'aceitar o perdão', 'escape_punishment':'fugir do castigo'}
                source_names = {'lif+episodic_policy':'rede e memória de experiências',
                                'lif_policy':'atividade neural', 'expression_policy':'expressão atual',
                                'explicit_user_request':'pedido manual', 'lif_hazard':'atividade neural',
                                'user_feedback':'interação com você'}
                action = str(current.get('action') or 'Sem ação registrada')
                target = current.get('target')
                if isinstance(target, (int, float)):
                    target = f'posição {target:.0f} px'
                elif target is None:
                    target = 'nenhum'
                labels = {'energy':'energia', 'contact':'carência', 'emotion':'emoção',
                          'memory':'memória', 'habit':'hábito', 'estimate':'previsão aprendida',
                          'familiarity':'familiaridade', 'attention':'busca de atenção', 'rest':'descanso'}
                influences = []
                mood = None
                if isinstance(factors, dict):
                    if isinstance(factors.get('emotion'), str):
                        mood = 'humor ' + factors['emotion']
                    for group in ('drives', 'memory', 'habit', 'neural'):
                        values = factors.get(group)
                        if not isinstance(values, dict):
                            continue
                        for key, value in values.items():
                            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                                title = labels.get(key, f'sinal neural {key}' if group == 'neural' else str(key))
                                influences.append((abs(float(value)), f'{title} {_number(value):.2f}'))
                influences = sorted((item for item in influences if isinstance(item, tuple)), reverse=True)[:3]
                influence_text = ' · '.join(([mood] if mood else []) + [text for _, text in influences])
                title = 'Última decisão registrada' if previous_decision else 'Agora'
                lines = [f"{title}: {action_names.get(action, action)}",
                         f"Alvo: {target} · Decidido por: {source_names.get(str(current.get('source')), 'cérebro da Bolha')}",
                         f"Intensidade {_number(current.get('intensity')):.2f} · duração {_number(current.get('duration')):.1f} s",
                         'Sinais associados: ' + (influence_text or 'nenhum fator numérico registrado.')]
                blocked = current.get('refusal_reason') or current.get('blocked_reason')
                if not blocked and current.get('action') == 'request_refused':
                    blocked = 'A recusa ainda não tem um motivo registrado.'
                if blocked:
                    reasons = {'network_or_mischief_disabled':'Reações online ou travessuras estão desligadas.',
                               'hidden_or_panicked':'A Bolha está escondida ou em modo de emergência.',
                               'hidden_panicked_or_no_active_display':'A Bolha está escondida, em emergência ou sem uma tela disponível.',
                               'sleeping':'A Bolha está dormindo.',
                               'being_dragged':'A Bolha está sendo arrastada.',
                               'maximum_objects_or_network_unavailable':'Limite de objetos atingido ou rede indisponível.'}
                    lines.append('Motivo: ' + reasons.get(str(blocked), str(blocked)))
                history = snapshot.get('history', [])
                if history:
                    previous = [action_names.get(str(record.get('action', '')), str(record.get('action', '')))
                                for record in history[-3:] if isinstance(record, dict)]
                    lines.extend(('', 'Decisões recentes: ' + ' · '.join(previous)))
                self.decision.setText('\n'.join(lines))
            else:
                self.decision.setText('As decisões aparecerão aqui conforme a Bolha interagir.')
            lines = [f"Objetivo: {summary.get('label', 'Seguindo os impulsos da rede')}",
                     'Objetivos adaptativos: ' + ('ativos' if summary.get('enabled') else 'pausados'),
                     f"Hábitos por horário: {summary.get('slots', 0)} registros",
                     f"Memórias de interações: {summary.get('episodes', 0)}",
                     f"Decisões adaptativas: {summary.get('decisions', 0)}", '', 'Associações aprendidas (pesos):']
            learned = brain.learned_summary(8)
            lines.extend(f'{source} → {target}: {_number(weight):+.4f}' for source, target, weight in learned)
            if not learned:
                lines.append('Ainda não há associações para mostrar.')
            if summary.get('compatibility'):
                lines.extend(('', str(summary['compatibility'])))
            text = '\n'.join(lines)
            if self.learning.toPlainText() != text:
                self.learning.setPlainText(text)
            rss, arrays = _number(game.app_rss_mib), _number(game.brain_array_mib)
            self.metrics.setText(f'Aplicativo inteiro (RSS): {f"{rss:.1f} MiB" if rss > 0 else "aguardando medição"}\n'
                                 f'Arrays da rede (estimativa): {f"{arrays:.2f} MiB" if arrays > 0 else "aguardando medição"}')
            if time.monotonic() >= self._notice_until:
                self.status.clear()
        except (AttributeError, TypeError, ValueError, OSError) as error:
            self.status.setText(f'Este quadro não pôde ser atualizado: {error}. O aplicativo pode continuar aberto.')

    def copy_diagnostics(self):
        try:
            QApplication.clipboard().setText(self.controller.diagnostics_text())
        except (OSError, ValueError) as error:
            self.status.setText(f'Não consegui preparar o diagnóstico: {error}.')
            return
        self.status.setText('Diagnóstico copiado. Nenhum envio automático.')
        self._notice_until = time.monotonic()+5

    def _selection_changed(self, *_):
        self.canvas.set_selection(self.group_filter.currentData(), self.kind_filter.currentData())

    def request_reaction(self):
        try:
            result = self.controller.request_reaction()
            status = self.controller.reaction_status()
            if isinstance(status, dict):
                if 'state' in status:
                    rows = [value for value in status.values() if isinstance(value, dict)]
                    latest = rows[-1] if rows else {}
                    labels = {'loading':'Carregando a reação…', 'network':'Aguardando a rede…',
                              'no-results':'A busca não encontrou reações.', 'decode':'Não foi possível abrir a reação.',
                              'memory':'A reação não coube na memória disponível.', 'canceled':'Busca cancelada.',
                              'ready':'Reação pronta para exibição.'}
                    state = latest.get('state', 'pending')
                    message = labels.get(state, 'Pedido enviado à cena.')
                    if latest.get('reason'):
                        message += ' ' + str(latest['reason'])
                else:
                    message = status.get('message') or status.get('reason') or ('Pedido aceito.' if result else 'Pedido recusado.')
            else:
                message = str(status or ('Pedido aceito.' if result else 'Pedido recusado.'))
            self.reaction_status.setText(str(message))
        except (AttributeError, OSError, ValueError) as error:
            self.reaction_status.setText(f'Não foi possível pedir a reação: {error}')

    def _pool_row_selected(self, row, _column):
        item = self.pools.item(row, 0)
        if item is not None:
            index = self.group_filter.findData(item.data(Qt.UserRole))
            if index >= 0:
                self.group_filter.setCurrentIndex(index)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if self.isMinimized():
            self.timer.stop()
        elif self.isVisible():
            self.timer.start()
