# SPDX-License-Identifier: GPL-3.0-only
"""Aplicação Qt nativa: o Game é a única autoridade do cérebro e da física."""
import json
import os
from pathlib import Path
import queue
import statistics
import sys
import time
from collections import deque
from PySide6.QtCore import Qt,QTimer,QLockFile
from PySide6.QtGui import QIcon,QPixmap,QPainter,QCursor,QPalette,QColor
from PySide6.QtWidgets import QApplication,QMenu,QSystemTrayIcon,QMessageBox,QDialog,QVBoxLayout,QLabel,QPushButton
from . import VERSION
from .preferences import PreferencesStore
from .persistence import PersistenceWriter
from .platform import desktop_layout,PanicHotkey
from .pet import PetWindow
from .pingpong_view import PingPongView
from .scene import NativeScene
from .character import draw_character
from game import Game
from pestinha import store as brain_store
from pestinha.log import setup as setup_log,log,capturar_erros


def data_directory():
    if os.getenv('BOLHA_TEST')=='1' and os.getenv('BOLHA_TEST_USER_DATA'):
        return Path(os.environ['BOLHA_TEST_USER_DATA'])
    return Path(os.environ.get('APPDATA',Path.home()/'.config'))/'bolha'


def icon():
    pixmap=QPixmap(128,128);pixmap.fill(Qt.transparent)
    p=QPainter(pixmap);p.setRenderHint(QPainter.Antialiasing);draw_character(p,64,64,scale=1);p.end()
    return QIcon(pixmap)


def local_log_excerpt(data_dir):
    """Trecho solicitado: até64KiB e60linhas, nunca lê outro arquivo do PC."""
    path=Path(data_dir)/'logs'/'main.log'
    try:
        with path.open('rb') as stream:
            size=stream.seek(0,2);stream.seek(max(0,size-65536))
            text=stream.read(65536).decode('utf-8',errors='replace')
        lines=text.splitlines()
        if size>65536:lines=lines[1:]  # descarta a linha parcial na borda do limite
        return '\n'.join(lines[-60:])
    except FileNotFoundError:return ''
    except OSError as error:return '[aviso] Log local indisponível: '+str(error)


def palette(app):
    app.setStyle('Fusion');p=QPalette()
    for role,color in ((QPalette.Window,'#211d2d'),(QPalette.WindowText,'#ece7f5'),(QPalette.Base,'#17151f'),(QPalette.AlternateBase,'#292534'),(QPalette.Text,'#ece7f5'),(QPalette.Button,'#353040'),(QPalette.ButtonText,'#ece7f5'),(QPalette.Highlight,'#8062ac'),(QPalette.HighlightedText,'#ffffff'),(QPalette.ToolTipBase,'#353040'),(QPalette.ToolTipText,'#ece7f5')):p.setColor(role,QColor(color))
    app.setPalette(p)


class NativeApp:
    def __init__(self,qapp,data_dir=None):
        self.qapp=qapp;self.data_dir=Path(data_dir or data_directory());self.data_dir.mkdir(parents=True,exist_ok=True)
        self.lock=QLockFile(str(self.data_dir/'native.lock'));self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):raise RuntimeError('A Bolha já está aberta neste perfil.')
        self.started=time.monotonic();self.errors=[];self.quitting=False;self.updating=False;self.suspended=False
        self.frame_times=deque(maxlen=1800);self.think_times=deque(maxlen=600);self.first_paint=False;self.first_think=False;self.healthy=False
        self.dialogs=[];self.updater=None;self.connected_screens=set();self.update_dialog=None;self.reset_pending=False
        self._health(False)
        self.store=PreferencesStore(self.data_dir)
        content=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'assets'/'bolha'/'content'
        if not content.exists():content=Path(__file__).resolve().parents[1]/'assets'/'bolha'/'content'
        self.game=Game(self.data_dir/'brain',content)
        self.initial_errors=[e for e in brain_store.read_errors() if str(e[0]).startswith(str(self.data_dir))]
        self.writer=PersistenceWriter();brain_store.set_dispatcher(self.writer.submit)
        setup_log(self.data_dir/'logs'/'main.log');capturar_erros()
        self.game.configure(self.store.preferences)
        original_think=self.game.think
        def measured_think(*args):
            start=time.perf_counter();original_think(*args);self.think_times.append((time.perf_counter()-start)*1000);self.first_think=True
        self.game.think=measured_think
        self.pet=PetWindow(self.game);self.scene=NativeScene(self.game,on_scale_change=self.adjust_object_scale)
        self.pingpong_view = PingPongView()
        qapp.applicationStateChanged.connect(self._application_state_changed)
        self.pet.visual.painted.connect(self._painted)
        self.pet.menu_requested.connect(self.show_menu)
        self.tray=QSystemTrayIcon(icon(),qapp);self.tray.setToolTip('Bolha '+VERSION)
        self.tray.activated.connect(self._tray_activated)
        self.menu=self.make_menu();self.tray.setContextMenu(self.menu);self.tray.show()
        self.hotkey=PanicHotkey(lambda:self.interact('panic'));qapp.installNativeEventFilter(self.hotkey)
        qapp.screenAdded.connect(self._screens_changed);qapp.screenRemoved.connect(self._screens_changed)
        for screen in qapp.screens():self._connect_screen(screen)
        self.refresh_desktop()
        self.last_tick=time.monotonic()
        self.frame=QTimer();self.frame.setTimerType(Qt.PreciseTimer);self.frame.setInterval(16);self.frame.timeout.connect(self.tick);self.frame.start()
        self.status_timer=QTimer();self.status_timer.setInterval(250);self.status_timer.timeout.connect(self.poll);self.status_timer.start()
        self.profile_timer=QTimer();self.profile_timer.setInterval(30000);self.profile_timer.timeout.connect(self.save_preferences_async);self.profile_timer.start()
        from .updates import Updater
        self.updater=Updater(self.data_dir,VERSION,self.before_install,self.on_recover)
        self.updater.changed.connect(self.update_changed);self.updater.start()
        log('Bolha',VERSION,'pronta. Interface Qt nativa; cérebro',self.game.brain.N)
        if not self.game.visible():QTimer.singleShot(0,self.check_hidden_startup)
        if self.store.error:self.warn(self.store.error)
        for warning in self.initial_errors:self.warn(str(warning))
        if os.getenv('BOLHA_TEST')=='1':
            if os.getenv('BOLHA_TEST_EXIT_VERSION')==VERSION:QTimer.singleShot(45000,self.quit)
            duration=os.getenv('BOLHA_TEST_DURATION')
            if duration:
                try:QTimer.singleShot(int(max(1,min(120,float(duration)))*1000),self.quit)
                except ValueError:pass
    def check_hidden_startup(self):
        # Um perfil em pânico ou todas as telas ocupadas continua sendo uma
        # abertura saudável. Validar um ciclo inicial não mostra a personagem.
        if self.quitting:return
        try:
            self.pet.visual.grab()
            if not self.first_think:self.game.think(.001,time.monotonic())
        except Exception as error:self.warn('Validação inicial do cérebro falhou: '+str(error))
    def _health(self,ready):
        from .migration import atomic_json
        atomic_json(self.data_dir/'health.json',dict(version=VERSION,pid=os.getpid(),ready=ready,neurons=470 if ready else 0))
    def _painted(self):self.first_paint=True
    def _connect_screen(self,screen):
        key=id(screen)
        if key in self.connected_screens:return
        self.connected_screens.add(key)
        screen.destroyed.connect(lambda *_:self.connected_screens.discard(key))
        for signal in (screen.geometryChanged,screen.availableGeometryChanged,screen.logicalDotsPerInchChanged):signal.connect(self.refresh_desktop)
    def _screens_changed(self,*_):
        for screen in self.qapp.screens():self._connect_screen(screen)
        QTimer.singleShot(100,self.refresh_desktop)
    def refresh_desktop(self,*_):
        exclude=[int(self.pet.winId()),int(self.pet.visual.winId())]+self.scene.ids()+[int(d.winId()) for d in self.dialogs]
        if self.pingpong_view.isVisible():
            exclude.append(int(self.pingpong_view.winId()))
        self.game.desktop(desktop_layout(self.qapp,exclude));self.game.last_native=0;self.game.read_context(time.monotonic());self.pet.sync();self.scene.sync()
        self.sync_pingpong()
    def tick(self):
        if self.quitting or self.updating or self.suspended:
            self.cancel_interactions();return
        now=time.monotonic();dt=now-self.last_tick;self.last_tick=now;self.frame_times.append(dt*1000)
        try:
            self.pet.poll_interaction();self.scene.poll_interactions()
            if self.store.preferences.get('senseCursor',True):
                point=QCursor.pos();self.game.interact(dict(type='cursor',x=point.x(),y=point.y()))
            else:self.game.cursor=(self.game.body.x,self.game.body.y)
            self.game.tick(dt,now);self.pet.sync();self.scene.sync()
            self.sync_pingpong()
            self.game.excluded.update(self.scene.ids())
        except Exception as error:
            self.cancel_interactions();self.frame.stop();self.warn('A rotina foi pausada: '+str(error));log('[erro]',repr(error))
    def cancel_interactions(self):
        self.pet.cancel_interaction();self.scene.cancel_interactions()
    def _application_state_changed(self,state):
        self.suspended=state==Qt.ApplicationSuspended
        if self.suspended:
            self.cancel_interactions()
            self.game.stop_pingpong()
            self.sync_pingpong()
        else:self.last_tick=time.monotonic()
    def poll(self):
        test_profile=os.getenv('BOLHA_TEST_USER_DATA')
        if (os.getenv('BOLHA_TEST')=='1' and os.getenv('BOLHA_TEST_ALLOW_STOP')=='1' and test_profile
                and Path(test_profile).resolve()==self.data_dir.resolve()):
            # Pedido estático do driver isolado: conteúdo nunca é lido/executado.
            try:(self.data_dir/'test-stop.request').unlink()
            except FileNotFoundError:pass
            except OSError as error:self.warn('Não foi possível remover o pedido de parada do teste: '+str(error))
            else:self.quit();return
        while True:
            try:path,error=self.writer.errors.get_nowait()
            except queue.Empty:break
            self.warn('Não foi possível gravar '+Path(path).name+': '+error)
        if self.first_paint and self.first_think and self.frame.isActive() and not self.healthy and not self.initial_errors and not self.store.error and not self.writer.failure:
            try:self._health(True)
            except OSError as error:self.warn('Confirmação local falhou: '+str(error));return
            self.healthy=True
            if self.updater:self.updater.healthy()
        if self.updater and self.updater.state.get('phase')=='ready':
            deadline=self.updater.state.get('installAt')
            remaining=max(0,round((deadline-time.time()*1000)/1000)) if deadline else None
            self.tray.setToolTip('Bolha · atualização em '+str(remaining)+' segundos' if remaining is not None else 'Bolha · atualização adiada')
            if remaining is not None and remaining<=30:
                self.show_update_countdown(remaining)
            elif self.update_dialog:self.update_dialog.hide()
        elif self.update_dialog:self.update_dialog.hide()
    def warn(self,message):
        if message in self.errors:return
        self.errors.append(message);log('[aviso]',message)
        if hasattr(self,'tray'):self.tray.showMessage('Bolha',message,QSystemTrayIcon.Warning,7000)
    def interact(self,kind,**kwargs):
        result=self.game.interact(dict(type=kind,**kwargs));self.pet.sync();self.scene.sync()
        return result
    def sync_pingpong(self):
        self.pingpong_view.sync(self.game.pingpong,self.game.pingpong_paused(),cursor=self.game.cursor)
        if self.pingpong_view.isVisible():
            self.game.excluded.add(int(self.pingpong_view.winId()))
    def toggle_pingpong(self):
        result=self.interact('pingpong')
        self.sync_pingpong()
        if result:
            self.tray.showMessage('Pingue-pongue',result,QSystemTrayIcon.Information,5000)
    def request_reaction(self):
        before=set(self.game.objects)
        self.interact('reaction-now')
        if not (set(self.game.objects)-before):
            if not self.store.preferences.get('onlineReactions',True):reason='Ative as reações online nas configurações.'
            elif not self.store.preferences.get('mischiefEnabled',True):reason='Ative as travessuras nas configurações.'
            elif not self.game.visible():reason='Mostre a Bolha e saia do modo de emergência para tentar.'
            elif self.game.body.held:reason='Solte a Bolha antes de pedir uma reação.'
            elif self.game.sleep.asleep:reason='Acorde a Bolha antes de pedir uma reação.'
            else:reason='Não foi possível iniciar: libere um objeto da tela e tente novamente.'
            self.scene._status('request','canceled',reason)
        return self.reaction_status()
    def reaction_status(self):
        return dict(self.scene.reaction_status)
    def adjust_object_scale(self,kind,factor=None,reset=False):
        from .preferences import DEFAULTS
        if kind not in DEFAULTS['objectScales']:raise ValueError('Tipo de objeto inválido.')
        scales=dict(self.store.preferences['objectScales'])
        scales[kind]=1. if reset else factor
        return self.save_preferences({'objectScales':scales})
    def make_menu(self):
        menu=QMenu()
        action=menu.addAction('Central da Bolha…')
        action.triggered.connect(self.show_settings)
        play=menu.addMenu('Brincar')
        self.pingpong_action=play.addAction('Jogar pingue-pongue')
        self.pingpong_action.triggered.connect(self.toggle_pingpong)
        for label,kind in (('Mostrar / guardar brinquedo','ball'),('Vamos brincar','play'),
                           ('Notebook de brincadeira','notebook'),('Vem trabalhar comigo','work')):
            action=play.addAction(label)
            action.triggered.connect(lambda checked=False,k=kind:self.interact(k))
        interactions=menu.addMenu('Interagir')
        for label,kind in (('Carinho','caress'),('Dormir um pouco','sleep'),('Acordar','wake'),
                           ('Comemorar','celebrate'),('Uma travessura','mischief'),
                           ('Cantinho / perdão','corner'),('Sossega um pouquinho','quiet')):
            action=interactions.addAction(label)
            action.triggered.connect(lambda checked=False,k=kind:self.interact(k))
        action=interactions.addAction('Mostrar uma reação agora')
        action.triggered.connect(lambda:self.request_reaction())
        menu.addSeparator()
        action=menu.addAction('Mostrar / esconder');action.triggered.connect(lambda:self.interact('hide',value=not self.game.hidden))
        pause=menu.addAction('Pausar tudo')
        pause.setToolTip('Pausa de emergência · Ctrl+Alt+Shift+B')
        pause.triggered.connect(lambda:self.interact('panic'))
        menu.addSeparator();action=menu.addAction('Sair');action.triggered.connect(self.quit)
        menu.aboutToShow.connect(self._panel_opened);menu.aboutToHide.connect(self._panel_closed)
        menu.aboutToShow.connect(lambda:self.pingpong_action.setText(
            'Encerrar pingue-pongue' if self.game.pingpong else 'Jogar pingue-pongue'))
        menu.aboutToShow.connect(lambda:pause.setText('Retomar a Bolha' if self.game.panicked else 'Pausar tudo'))
        return menu
    def show_menu(self,point):self.menu.popup(point)
    def _tray_activated(self,reason):
        if reason==QSystemTrayIcon.DoubleClick:self.show_settings()
    def _panel_closed(self,*_):
        self.game.interact(dict(type='panel',value=any(dialog.isVisible() for dialog in self.dialogs)))
    def _panel_opened(self):
        self.cancel_interactions()
        self.game.interact(dict(type='panel',value=True))
    def _show_dialog(self,cls):
        self._panel_opened()
        for dialog in self.dialogs:
            if isinstance(dialog,cls):dialog.show();dialog.raise_();dialog.activateWindow();return
        dialog=cls(self);self.dialogs.append(dialog);dialog.finished.connect(self._panel_closed)
        dialog.show()
    def show_settings(self):
        from .dialogs import SettingsDialog
        self._show_dialog(SettingsDialog)
    def show_neural(self):
        from .dialogs import NeuralDialog
        self._show_dialog(NeuralDialog)
    def save_preferences(self,patch):
        result=self.store.save(patch);self.game.configure(result);self.pet.sync();self.scene.sync();return result
    def reset_appearance(self):
        result=self.store.reset_appearance();self.game.configure(result);return result
    def startup_enabled(self):
        from .installation import startup_enabled
        return startup_enabled()
    def set_startup(self,enabled):
        from .installation import set_startup
        return set_startup(enabled)
    def save_preferences_async(self):
        try:self.game.save()
        except (OSError,ValueError) as error:self.warn('Memória não gravada: '+str(error))
    def reset_learning(self):
        if self.reset_pending:return False
        from concurrent.futures import Future
        import threading
        try:self.game.save()
        except OSError as error:self.warn('A memória original será preservada antes de reiniciar: '+str(error))
        self.game.last_save=time.monotonic();self.writer.retry();self.reset_pending=True;future=Future()
        threading.Thread(target=lambda:future.set_result(self.writer.flush()),name='bolha-backup-flush',daemon=True).start()
        timer=QTimer(self.qapp);timer.setInterval(50)
        def finish():
            if not future.done():return
            if future.result() and not self.writer.flush(timeout=0):return
            timer.stop();timer.deleteLater();self.reset_pending=False
            if not future.result():self.warn('Aprendizado preservado: a gravação precisa ser recuperada antes do backup.');return
            try:
                self.scene.close();self.game.reset_learning();self.pet.body=self.game.body;self.initial_errors=[];self.frame.start();self.refresh_desktop()
            except OSError as error:self.warn('Aprendizado preservado; reinício cancelado: '+str(error))
        timer.timeout.connect(finish);timer.start()
        return True
    def before_install(self):
        from concurrent.futures import Future
        import threading
        self.game.stop_pingpong()
        self.sync_pingpong()
        self.game.save();self.writer.retry();future=Future()
        # O snapshot já é texto imutável; esperar disco não bloqueia o desenho.
        def finish():future.set_result(self.writer.flush())
        threading.Thread(target=finish,name='bolha-confirm-save',daemon=True).start()
        return future
    def on_recover(self):self.updating=False;self.last_tick=time.monotonic();self.pet.sync();self.scene.sync()
    def update_changed(self,state):
        phase=state.get('phase')
        if phase=='ready' and state.get('installAt') and not getattr(self,'update_notified',False):
            self.update_notified=True
            remaining=max(0,round((state['installAt']-time.time()*1000)/1000))
            message=('Instalação em '+str(remaining)+' segundos.') if remaining<=30 else 'O adiamento salvo foi mantido.'
            self.tray.showMessage('Bolha','Atualização pronta. '+message+' Você pode adiar por uma hora no menu da bandeja.',QSystemTrayIcon.Information,15000)
        if phase=='error':self.warn('Atualização: '+str(state.get('error',state.get('message','não foi possível concluir'))))
    def show_update_countdown(self,remaining):
        if self.update_dialog is None:
            dialog=QDialog(None,Qt.Tool|Qt.WindowStaysOnTopHint)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.setWindowTitle('Atualização da Bolha');layout=QVBoxLayout(dialog)
            self.update_label=QLabel();layout.addWidget(self.update_label)
            button=QPushButton('Adiar por uma hora');button.clicked.connect(lambda:self.updater.defer());layout.addWidget(button)
            dialog.rejected.connect(lambda:self.updater.defer());self.update_dialog=dialog
        self.update_label.setText(f'Uma nova versão está pronta.\nInstalação em {remaining} segundos.\nSeu aprendizado e preferências serão preservados.')
        self.update_dialog.show()
    def metrics(self):
        import psutil
        def p95(values):return round(sorted(values)[max(0,int(len(values)*.95)-1)],2) if values else 0
        return dict(version=VERSION,pid=os.getpid(),healthy=self.healthy,neurons=self.game.brain.N,frameP95Ms=p95(self.frame_times),
                    thinkP95Ms=p95(self.think_times),frameMaxMs=max(self.frame_times,default=0),thinkMaxMs=max(self.think_times,default=0),
                    appRssMiB=round(psutil.Process().memory_info().rss/1048576,2),brainArrayMiB=round(self.game.brain_array_mib,3),
                    frameCount=len(self.frame_times),thinkCount=len(self.think_times),uptimeSeconds=round(time.monotonic()-self.started,2),errors=list(self.errors))
    def diagnostics_text(self):
        metrics=self.metrics()
        return '\n'.join((f'Bolha {VERSION}',f'{sys.platform} {os.name} · Python {sys.version.split()[0]} · Qt nativo',f'Neurônios: {self.game.brain.N}',f"RSS total do aplicativo: {metrics['appRssMiB']:.1f} MiB",f'Arrays principais do cérebro: {self.game.brain_array_mib:.2f} MiB (não é RSS isolado)',f"Intervalo de quadros p95: {metrics['frameP95Ms']} ms",f"Ciclo do cérebro p95: {metrics['thinkP95Ms']} ms",'Leituras: '+json.dumps({k:v for k,v in self.store.preferences.items() if k.startswith('sense')}),'Reações online: '+json.dumps(self.reaction_status(),ensure_ascii=False),'Avisos: '+'; '.join(self.errors),'Log local (trecho):',local_log_excerpt(self.data_dir)))
    def quit(self):
        if self.quitting:return
        self.quitting=True
        if os.getenv('BOLHA_TEST')=='1' and os.getenv('BOLHA_TEST_REPORT'):
            try:
                from .migration import atomic_json
                atomic_json(Path(os.environ['BOLHA_TEST_REPORT']),dict(self.metrics(),diagnostics=self.diagnostics_text()))
            except OSError as error:self.warn('Relatório de teste não gravado: '+str(error))
        try:
            self.frame.stop();self.status_timer.stop();self.profile_timer.stop()
            if self.updater:self.updater.stop()
            self.hotkey.stop()
            try:self.game.save()
            except (OSError,ValueError) as error:self.warn('Não foi possível salvar ao sair: '+str(error))
            if not self.writer.close():self.warn('Alguns dados não puderam ser gravados. Os arquivos anteriores foram preservados.')
        finally:
            brain_store.set_dispatcher(None)
            self.pingpong_view.close();self.scene.close();self.pet.close();self.tray.hide();self.lock.unlock()
            for dialog in self.dialogs:dialog.close()
            if self.update_dialog:
                self.update_dialog.rejected.disconnect();self.update_dialog.close()
            self.qapp.quit()
