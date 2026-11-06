# SPDX-License-Identifier: GPL-3.0-only
"""Qt real fora da tela; controlador de teste não toca dados do usuário."""
import math
import time
from types import SimpleNamespace

import pytest
import numpy as np
from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from bolha.dialogs import SettingsDialog, NeuralDialog
from bolha.preferences import defaults, sanitize


class UpdaterStub(QObject):
    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.state = {'phase': 'idle'}
        self.checks = self.defers = 0

    def check(self):
        self.checks += 1
        self.state = {'phase': 'checking'}
        self.changed.emit(self.state)

    def defer(self):
        self.defers += 1
        self.state = dict(self.state, installAt=int(time.time()*1000)+3600000)
        self.changed.emit(self.state)


class BrainStub:
    N = 470

    def __init__(self):
        self.pos = [((i % 25)/25, (i // 25)/20) for i in range(self.N)]
        self.trace = [(i % 10)/10 for i in range(self.N)]
        self.kind = [i % 4 for i in range(self.N)]
        self.pools = [dict(name='SENSOR_A', group='sensory', start=0, n=6, center=(.2,.3)),
                      dict(name='MOTOR_A', group='motor', start=6, n=6, center=(.7,.7))]
        self.W = np.zeros((self.N, self.N), dtype=float)
        self.W[0, 6] = .2
        self.reads = 0

    def pool_rates(self):
        self.reads += 1
        return {'CARESS': 4.5, 'CALM': 8.2, 'CURIOUS': 3.1}

    def learned_summary(self, limit):
        return [('CARESS', 'CALM', .034)][:limit]


class ControllerStub:
    def __init__(self):
        self.store = SimpleNamespace(preferences=defaults(), error='')
        self.updater = UpdaterStub()
        self.startup = False
        self.startup_error = self.save_error = None
        self.saved = []
        self.resets = self.neural_requests = 0
        self.reaction_requests = 0
        self._reaction_status = {'message':'Reação exibida pelo controlador.'}
        self.game = SimpleNamespace(
            brain=BrainStub(), state=SimpleNamespace(emotion='feliz'),
            drives=SimpleNamespace(energy=.84, contact=.22, stimulation=.65),
            activity='IDLE', rates={'WATCH': 8.2, 'WANDER': 3.1},
            intelligence=SimpleNamespace(summary=lambda *_: dict(enabled=True,
                label='Observar com curiosidade', slots=4, episodes=12, decisions=27)),
            app_rss_mib=76.2, brain_array_mib=4.3,
        )
        self.game.decision_snapshot = lambda: {'current':dict(action='WANDER', target='screen-edge',
            intensity=.7, duration=1.4, source='policy', factors={'neural':{'WATCH':.4},
            'emotion':'observando','drives':{'energy':.2}}),
            'history':[dict(action='WATCH')]}

    def startup_enabled(self):
        return self.startup

    def set_startup(self, value):
        if self.startup_error:
            raise self.startup_error
        self.startup = value
        return value

    def save_preferences(self, patch):
        if self.save_error:
            raise self.save_error
        self.saved.append(dict(patch))
        self.store.preferences = sanitize(patch, self.store.preferences)
        return dict(self.store.preferences)

    def reset_appearance(self):
        return self.save_preferences({key: defaults()[key] for key in ('avatarSize', 'opacity')})

    def reset_learning(self):
        self.resets += 1
        return True

    def diagnostics_text(self):
        return 'Bolha 0.3.0\nmemória local: ♡\nsem envio automático'

    def show_neural(self):
        self.neural_requests += 1

    def request_reaction(self):
        self.reaction_requests += 1
        return True

    def reaction_status(self):
        return self._reaction_status


@pytest.fixture(scope='session')
def app(qt_application):
    application = qt_application
    application.setStyle('Fusion')
    palette = QPalette()
    for role, color in ((QPalette.Window, '#211d2d'), (QPalette.Base, '#17151f'),
                        (QPalette.WindowText, '#ece7f5'), (QPalette.Text, '#ece7f5'),
                        (QPalette.Button, '#353040'), (QPalette.ButtonText, '#ece7f5'),
                        (QPalette.Highlight, '#8062ac')):
        palette.setColor(role, QColor(color))
    application.setPalette(palette)
    yield application
    application.processEvents()


@pytest.fixture(autouse=True)
def cleanup(app):
    yield
    for window in app.topLevelWidgets():
        if isinstance(window, (SettingsDialog, NeuralDialog, QMessageBox)):
            window.close()
            window.deleteLater()
    app.processEvents()


def test_aplicar_preserva_sensores_desligados_e_valores_nao_editados(app):
    controller = ControllerStub()
    controller.store.preferences.update(senseApp=False, senseIdle=False, senseCursor=False,
                                        senseWindows=False, opacity=.333, mischiefInterval=245)
    dialog = SettingsDialog(controller)
    dialog.show()
    assert not dialog.apply_button.isEnabled()
    dialog.checks['roaming'].setChecked(False)
    dialog.apply_button.click()
    assert controller.saved == [{'roaming': False}]
    assert all(not controller.store.preferences[key] for key in ('senseApp','senseIdle','senseCursor','senseWindows'))
    assert controller.store.preferences['opacity'] == .333
    assert controller.store.preferences['mischiefInterval'] == 245
    assert not dialog.apply_button.isEnabled()


def test_central_pausa_a_previa_ao_trocar_de_area(app):
    dialog = SettingsDialog(ControllerStub())
    dialog.show()
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]==['Bolha','Testar','Privacidade','App']
    assert not dialog.lab.timer.isActive()
    dialog.tabs.setCurrentIndex(1)
    app.processEvents()
    assert dialog.lab.timer.isActive()
    dialog.tabs.setCurrentIndex(0)
    app.processEvents()
    assert not dialog.lab.timer.isActive()


def test_experimento_neural_isola_cena_memoria_e_dados(app,tmp_path):
    from pathlib import Path
    from game import Game
    from pestinha import scene
    from bolha.expression_lab import ExpressionLab
    live = Game(tmp_path, Path(__file__).resolve().parents[2]/'assets/bolha/content')
    learned = live.brain.learned.copy()
    existing = set(tmp_path.rglob('*'))
    lab = ExpressionLab()
    try:
        lab.mode.setCurrentIndex(1)
        lab.stimulus.setCurrentIndex(lab.stimulus.findData('throw'))
        lab.stimulate()
        assert lab.brain is not live.brain and lab.senses is not live.senses
        assert lab.senses.pulse['THROW']>0.
        lab.next_brain = 0.
        before = lab.brain.time_ms
        lab.tick()
        assert lab.brain.time_ms>before
        assert scene._current is live
        assert np.array_equal(live.brain.learned, learned)
        assert set(tmp_path.rglob('*'))==existing
        old = lab.brain
        lab.restart()
        assert lab.brain is not old and not np.any(lab.brain.learned)
    finally:
        lab.close()


def test_controles_de_retorno_sao_ptbr_editaveis_e_salvos_sem_afetar_outros_campos(app):
    controller = ControllerStub()
    dialog = SettingsDialog(controller)
    assert dialog.checks['popEnabled'].isChecked()
    assert dialog.pop_throw_limit.value() == 12
    assert dialog.pop_throw_limit.minimum() == 5 and dialog.pop_throw_limit.maximum() == 30
    assert dialog.checks['popEnabled'].text() == 'Estourar após muitos arremessos fortes'
    assert '1 minuto' in dialog.checks['popEnabled'].toolTip()
    dialog.checks['popEnabled'].setChecked(False)
    dialog.pop_throw_limit.setValue(20)
    dialog.apply_button.click()
    assert controller.saved[-1] == {'popEnabled': False, 'popThrowLimit': 20}
    assert controller.store.preferences['mischiefEnabled'] is True


def test_seletor_real_salva_reabre_e_preserva_privacidade(app,tmp_path,monkeypatch):
    from bolha.app import NativeApp
    from bolha.preferences import PreferencesStore
    monkeypatch.setenv('BOLHA_TEST','1')
    controller=NativeApp(app,tmp_path)
    try:
        sensors=dict(senseApp=False,senseIdle=False,senseCursor=False,senseWindows=False)
        controller.save_preferences(sensors)
        controller.show_settings();dialog=controller.dialogs[0]
        assert dialog.toy_appearance.currentData()=='peanut'
        body=controller.game.ball.body
        controller.game.brain.learned[0,0]=.04
        dialog.toy_appearance.setCurrentIndex(dialog.toy_appearance.findData('ball'))
        dialog.apply_button.click()
        assert controller.game.ball.appearance=='ball' and controller.game.ball.body is body
        assert controller.game.brain.learned[0,0]==pytest.approx(.04)
        persisted=PreferencesStore(tmp_path).preferences
        assert persisted['toyAppearance']=='ball' and all(persisted[key] is value for key,value in sensors.items())
        dialog.close();controller.show_settings()
        assert dialog.toy_appearance.currentData()=='ball' and not dialog.apply_button.isEnabled()
        assert all(not dialog.checks[key].isChecked() for key in sensors)
        reloaded=type(controller.game)(tmp_path/'reload-brain',controller.game.conteudo.proprio)
        reloaded.configure(persisted)
        assert reloaded.ball.appearance=='ball' and all(reloaded.prefs[key] is False for key in sensors)
    finally:controller.quit()


def test_falha_de_gravacao_preserva_dados_e_permite_tentar_novamente(app):
    controller = ControllerStub()
    before = dict(controller.store.preferences)
    controller.save_error = OSError('Disco indisponível')
    dialog = SettingsDialog(controller)
    dialog.checks['senseCursor'].setChecked(False)
    dialog.apply_button.click()
    assert controller.store.preferences == before
    assert 'Disco indisponível' in dialog.status.text()
    assert dialog.apply_button.isEnabled()
    controller.save_error = None
    dialog.apply_button.click()
    assert controller.store.preferences['senseCursor'] is False
    assert not dialog.apply_button.isEnabled()


def test_desligar_autostart_false_e_sucesso_e_falha_nao_finge_sucesso(app):
    controller = ControllerStub()
    controller.startup = True
    dialog = SettingsDialog(controller)
    dialog.autostart.setChecked(False)
    dialog.apply_button.click()
    assert controller.startup is False and not dialog.apply_button.isEnabled()
    controller.startup_error = OSError('Sem permissão')
    dialog.autostart.setChecked(True)
    dialog.apply_button.click()
    assert controller.startup is False
    assert 'Sem permissão' in dialog.status.text()
    assert dialog.apply_button.isEnabled()


def test_restaurar_aparencia_nao_apaga_edicoes_de_privacidade(app):
    controller = ControllerStub()
    controller.store.preferences.update(avatarSize=190, opacity=.45)
    dialog = SettingsDialog(controller)
    dialog.checks['senseWindows'].setChecked(False)
    dialog.reset_appearance()
    assert dialog.avatar_size.value() == defaults()['avatarSize']
    assert not dialog.checks['senseWindows'].isChecked()
    assert controller.store.preferences['senseWindows'] is True
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    assert controller.saved[-1] == {'senseWindows': False}


def test_diagnostico_unicode_e_adiamento_em_milissegundos(app):
    controller = ControllerStub()
    dialog = SettingsDialog(controller)
    dialog.show()
    dialog.tabs.setCurrentIndex(3)
    dialog.copy_diagnostics()
    assert QApplication.clipboard().text() == controller.diagnostics_text()
    controller.updater.state = dict(phase='ready', version='0.3.1', installAt=time.time()*1000+29000)
    controller.updater.changed.emit(controller.updater.state)
    assert '0.3.1' in dialog.update_label.text() and ' s.' in dialog.update_label.text()
    assert dialog.defer_update.isVisible() and not dialog.check_update.isEnabled()
    dialog.defer_update.click()
    assert controller.updater.defers == 1
    assert '60 min.' in dialog.update_label.text()
    controller.updater.state = {'phase':'error','message':'<b>Falhou</b>'}
    controller.updater.changed.emit(controller.updater.state)
    assert dialog.update_label.textFormat() == Qt.PlainText
    assert dialog.check_update.isEnabled()


def test_aprendizado_so_e_apagado_apos_confirmacao(app):
    controller = ControllerStub()
    dialog = SettingsDialog(controller)

    def choose(text):
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, QMessageBox)
        next(button for button in modal.buttons() if button.text() == text).click()

    QTimer.singleShot(0, lambda: choose('Cancelar'))
    dialog.reset_learning()
    assert controller.resets == 0
    QTimer.singleShot(0, lambda: choose('Apagar aprendizado'))
    dialog.reset_learning()
    assert controller.resets == 1


def test_teclado_fechamento_e_controles_cabem_em_tela_pequena(app):
    dialog = SettingsDialog(ControllerStub())
    finished = QSignalSpy(dialog.finished)
    dialog.resize(490, 430)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    dialog.avatar_size.setFocus()
    QTest.keyClick(dialog.avatar_size, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(dialog.avatar_size, '172')
    QTest.keyClick(dialog.avatar_size, Qt.Key_Tab)
    assert dialog.avatar_size.value() == 172
    assert QApplication.focusWidget() is not None
    dialog.tabs.setCurrentIndex(3)
    app.processEvents()
    assert dialog.apply_button.isVisible()
    assert dialog.apply_button.mapTo(dialog, dialog.apply_button.rect().bottomRight()).y() < dialog.height()
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert finished.count() == 1 and not dialog.update_timer.isActive()


def test_neural_so_consulta_quando_visivel_e_nao_persa_timer_fechado(app):
    controller = ControllerStub()
    dialog = NeuralDialog(controller)
    assert controller.game.brain.reads == 0 and not dialog.timer.isActive()
    dialog.show()
    assert dialog.timer.interval() == 250 and dialog.timer.isActive()
    QTest.qWait(540)
    assert controller.game.brain.reads >= 2
    assert len(dialog.canvas.points) == 470
    assert dialog.drives['energy'].value() == 84
    assert '76.2 MiB' in dialog.metrics.text()
    assert 'CARESS → CALM: +0.0340' in dialog.learning.toPlainText()
    dialog.hide()
    count = controller.game.brain.reads
    QTest.qWait(290)
    assert controller.game.brain.reads == count and not dialog.timer.isActive()


def test_neural_dados_invalidos_nao_encerram_dialogo_e_aviso_copia_persiste(app):
    controller = ControllerStub()
    dialog = NeuralDialog(controller)
    dialog.show()
    controller.game.drives.energy = math.nan
    controller.game.brain.trace[0] = math.inf
    dialog.refresh()
    assert dialog.drives['energy'].value() == 0
    positions = controller.game.brain.pos
    controller.game.brain.pos = None
    dialog.refresh()
    assert 'não pôde ser atualizado' in dialog.status.text() and dialog.isVisible()
    controller.game.brain.pos = positions
    dialog.refresh()
    assert not dialog.status.text()
    dialog.copy_diagnostics()
    QTest.qWait(290)
    assert 'Diagnóstico copiado' in dialog.status.text()


def test_neural_grupos_sinapses_decisao_e_reacao_usam_estado_do_controlador(app):
    controller = ControllerStub()
    dialog = NeuralDialog(controller)
    dialog.show()
    app.processEvents()
    assert dialog.group_filter.findData('SENSOR_A') > 0
    assert dialog.decision.text().startswith('Agora: WANDER')
    assert 'humor observando · sinal neural WATCH 0.40 · energia 0.20' in dialog.decision.text()
    dialog.group_filter.setCurrentIndex(dialog.group_filter.findData('SENSOR_A'))
    dialog.refresh()
    assert dialog.canvas.selected_pool == 'SENSOR_A'
    assert dialog.canvas.weights is controller.game.brain.W
    dialog.kind_filter.setCurrentIndex(dialog.kind_filter.findData(0))
    assert dialog.canvas.filter_kind == 0
    dialog.request_reaction()
    assert controller.reaction_requests == 1
    assert dialog.reaction_status.text() == 'Reação exibida pelo controlador.'
    controller.game.decision_snapshot = lambda: {'current':dict(action='request_refused',
        target=None, intensity=0, duration=0, source='explicit_user_request',
        refusal_reason='Reações desligadas', factors={}), 'history':[]}
    dialog.refresh()
    assert 'Motivo: Reações desligadas' in dialog.decision.text()


def test_ajuste_de_tamanho_do_avatar_e_objetos_e_editavel_sem_alcas(app):
    controller = ControllerStub()
    dialog = SettingsDialog(controller)
    assert dialog.avatar_size.minimum() == 48
    assert not hasattr(dialog, 'resize_handles')
    dialog.object_scales['toy'].setValue(1.3)
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    assert controller.store.preferences['objectScales']['toy'] == pytest.approx(1.3)


def test_canvas_decisao_e_reacao_usa_game_e_matriz_viva_sem_fixture_neural(app, tmp_path):
    from pathlib import Path
    from game import Game

    game = Game(tmp_path/'brain-real', Path(__file__).resolve().parents[2]/'assets'/'bolha'/'content')
    game.configure(defaults())

    class LiveController:
        def __init__(self): self.game = game
        def diagnostics_text(self): return 'Diagnóstico local.'
        def request_reaction(self):
            game.interact({'type':'reaction-now'})
            return game.intelligence.current_decision['action'] != 'request_refused'
        def reaction_status(self): return {}

    controller = LiveController()
    dialog = NeuralDialog(controller)
    dialog.show()
    app.processEvents()
    assert len(dialog.canvas.points) == game.brain.N == 470
    assert len(dialog.canvas.pools) == len(game.brain.pools)
    assert all(len(pool) == 7 for pool in dialog.canvas.pools)
    next(pool for pool in game.brain.pools if pool['name'] == 'MOTION')
    dialog.group_filter.setCurrentIndex(dialog.group_filter.findData('MOTION'))
    dialog.refresh()
    assert dialog.canvas.selected_pool == 'MOTION'
    assert dialog.canvas.weights is game.brain.W
    assert dialog.canvas.edges
    dialog.request_reaction()
    snapshot = game.decision_snapshot()
    assert snapshot['current']['source'] == 'explicit_user_request'
    assert snapshot['history'][-1]['action'] == snapshot['current']['action']
    dialog.refresh()
    assert 'pedido manual' in dialog.decision.text()
    dialog.close()


def test_painel_mostra_ultima_decisao_sem_fingir_que_esta_ativa(app):
    controller=ControllerStub()
    controller.game.panel=True
    controller.game.decision_snapshot=lambda: {'current':None,'history':[
        dict(action='explore',target=400,intensity=.3,duration=15,source='lif+episodic_policy',factors={'drives':{'energy':.8}})]}
    dialog=NeuralDialog(controller)
    dialog.show();dialog.refresh()
    assert 'Última decisão registrada: explorar' in dialog.decision.text()
    assert 'Agora: explorar' not in dialog.decision.text()
    dialog.close()
