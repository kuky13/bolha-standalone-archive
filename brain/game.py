# SPDX-License-Identifier: GPL-3.0-only
"""Modelo único da Bolha: cérebro, comportamento e física do Pestinha."""
import math
import random
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from pestinha import config
from pestinha.core.nervous_system import LIFBrain
from pestinha.core.homeostasis import Drives
from pestinha.core.emotion import EmotionState
from pestinha.core.episodic import EpisodicMemory
from pestinha.core.conditioning import Conditioning
from pestinha.core.protesto import Protesto
from pestinha.core.physics import Body
from pestinha.body.behavior import Behavior
from pestinha.body.pet_state import PetState
from pestinha.body.brincadeira import Play
from pestinha.body.toy import ToyTracker, bounce_off, push_from_cursor
from pestinha.mind.sleep import SleepController
from pestinha.mind.mesa import MesaController, pull
from pestinha.mind.protest_ctl import ProtestController
from pestinha.mind.castigo_ctl import CastigoController
from pestinha.mind.mischief_ctl import MischiefController
from pestinha.mind.festa import FestaController
from pestinha.mind.revolucao import RevolucaoController
from pestinha.world.mischief import MischiefEngine
from pestinha.sense.senses import ComputerSenses, ActivityTracker, detect_activity
from pestinha.paths import PetPaths, ConteudoPaths
from pestinha.store import read_json, write_json, preserve_invalid, clear_protection_after_backup
from pestinha.scene import set_scene, Ball, FloatingThing
from pestinha.scene import object_scale
from geometry import fullscreen_monitors
from intelligence import Intelligence
from pingpong import PingPong

POP_EFFECT_SECONDS = .75
POP_RETURN_SECONDS = 30.
THROW_WINDOW_SECONDS = 60.


class Game:
    def __init__(self, data_dir, content_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.objects = {}
        self.next_id = 1
        set_scene(self)
        self.prefs = {}
        self.areas = [(0., 0., 1280., 760.)]
        self.monitors = list(self.areas)
        self.displays = []
        self.blocked = set()
        self.cursor = (640., 350.)
        self.last_cursor = self.cursor
        self.last_input = time.monotonic()
        self.mouse_moved_at = 0.
        self.hover = False
        self.scene_dragging = False
        self.panel = False
        self.hidden = False
        session=read_json(self.data_dir / 'session.json',default={})
        self.panicked = session.get('panicked') is True if isinstance(session,dict) else False
        self.monitor_open = False
        self.paused_at = None
        self.excluded = set()
        self.activity = 'IDLE'
        self.idle = 0.
        self.last_native = self.last_save = self.last_think = 0.
        memory = self.data_dir / 'bolha'
        legacy = self.data_dir / 'drippy'
        # Conserva o caminho original para a versão anterior continuar lendo após recuperação.
        if not memory.exists() and legacy.is_dir():
            memory = legacy
        self.pet_paths = PetPaths(memory)
        self.conteudo = ConteudoPaths(Path(content_dir), Path(content_dir))
        self.prof = dict(config.PROFILES['normal'])
        self.brain = LIFBrain(seed=1313, temperament={'CURIOUS': 1.3, 'PLAYFUL': 1.2, 'DRAG->FRUSTRATION': 0.45})
        if not self.brain.load(self.pet_paths.nervous) and self.pet_paths.nervous.exists():
            preserve_invalid(self.pet_paths.nervous,'Aprendizado neural inválido; original preservado e gravação protegida.')
        self.drives = Drives()
        if not self.drives.load(self.pet_paths.drives,self.prof) and self.pet_paths.drives.exists():
            preserve_invalid(self.pet_paths.drives,'Necessidades inválidas; original preservado e gravação protegida.')
        self.memory = EpisodicMemory(self.pet_paths.episodes, self.pet_paths.preferences, random.Random(1313))
        self.memory.load()
        self.conditioning = Conditioning(self.pet_paths.conditioning, self.prof['cond_rate'])
        self.conditioning.load()
        self.emotion = EmotionState()
        self.state = PetState()
        self.body = Body(950., 300., 68., 68., circular=True)
        saved_position=read_json(self.data_dir / 'position.json',default={})
        if isinstance(saved_position,dict) and all(isinstance(saved_position.get(k),(int,float)) and math.isfinite(saved_position[k]) for k in ('x','y')):
            self.body.x,self.body.y=saved_position['x'],saved_position['y']
        self.pet = SimpleNamespace(body=self.body, isVisible=self.visible, raise_=lambda: None)
        self.senses = ComputerSenses()
        self.tracker = ActivityTracker()
        self.mischief = MischiefEngine(self.conteudo)
        self.behavior = Behavior(self.body, self.state, self.mischief)
        self.play = Play({'bola': 1., 'arremesso': 0.5, 'postit': 0.5})
        self.behavior.play = self.play
        self.ball = Ball(800., 650.)
        self.ball.show()
        self.behavior.ball = self.ball
        self.toy_tracker = ToyTracker()
        self.sleep = SleepController(self.emotion, self.drives, self.memory, lambda: False)
        self.protest = Protesto(self.conteudo.signs, self.pet_paths.protest)
        self.protest.load(self.prof)
        self.sad = Protesto(self.conteudo.signs, self.pet_paths.sad_protest, 'tristeza')
        self.sad.load(self.prof)
        self.protest_ctl = ProtestController(self.protest, self.body, self.behavior, self.senses, self.drives, self.state, lambda: False)
        self.sad_ctl = ProtestController(self.sad, self.body, self.behavior, self.senses, self.drives, self.state, lambda: False)
        self.mesa = MesaController(lambda: False, self)
        self.mischief_ctl = MischiefController(self.mischief, self.memory, self.drives, self.senses, self.behavior, self.emotion, lambda: False)
        self.mischief.dismissed.connect(lambda thing, elapsed: self.mischief_ctl.on_dismissed(thing, elapsed, self.prof, time.monotonic()))
        self.castigo = CastigoController(self, lambda: False)
        self.festa = FestaController(lambda: False, self)
        self.revolucao = RevolucaoController(self.play, lambda: False)
        self.rates = self.brain.motor_activity()
        self.inputs = {}
        self.in_flight = False
        self.ball_stored = False
        self.pingpong = None
        self._pingpong_origin = None
        self.request_refused = 0.
        self.prev_distance = None
        self.cursor_toy_near = False
        self.cursor_sample = None
        self.cursor_velocity = (0., 0.)
        self.last_toy_push = -1e9
        self.next_toy_attention = 0.
        self.held_since = None
        self.release_reaction = {}
        self.play_reaction = {}
        self.last_play_attempt = None
        self.next_play_scene = 0.
        self.senses_app = None
        self.native_error = None
        self.quiet_until = 0.
        self.landing = 0.
        self.landing_reaction = {}
        self.strong_throws = deque()
        self.pop_started = None
        self.pop_return_at = 0.
        self.last_monitor_snapshot = -1.
        self.intelligence = Intelligence(self.memory, self.pet_paths.base / 'habits.json')
        self.behavior.policy = self.intelligence
        self.play.policy = self.intelligence
        self.play.rates = self.rates
        self.mischief_ctl.policy = self.intelligence
        self.revolucao.policy = self.intelligence
        self.festa.policy = self.intelligence
        self.sleep.policy = self.intelligence
        self.mischief.policy = self.intelligence
        self.protest.policy = self.sad.policy = self.intelligence
        self.last_intelligence = self.last_metrics = 0.
        self.app_rss_mib = 0.
        self.brain_array_mib = 0.

    def available_areas(self):
        return [area for i, area in enumerate(self.areas) if i not in self.blocked]

    def bounds(self, point=None):
        areas = self.available_areas() or self.areas
        x, y = point or (self.body.x, self.body.y)
        for area in areas:
            if area[0] <= x < area[2] and area[1] <= y < area[3]: return area
        return min(areas, key=lambda a: math.hypot(x - (a[0] + a[2]) / 2, y - (a[1] + a[3]) / 2))

    def fit(self, body, margin=4.):
        a = self.bounds((body.x, body.y))
        ex, ey = body.extents()
        old = (body.x, body.y)
        body.x = max(a[0] + ex + margin, min(a[2] - ex - margin, body.x))
        body.y = max(a[1] + ey + margin, min(a[3] - ey - margin, body.y))
        if old != (body.x, body.y): body.grounded = False; body.platform = None

    def visible(self):
        return not self.hidden and not self.panicked and bool(self.available_areas())

    def pop_effect_age(self, now):
        if self.pop_started is not None:
            age = now-self.pop_started
            if 0 <= age < POP_EFFECT_SECONDS:
                return age
        return None

    def pet_visible(self, now=None):
        now = time.monotonic() if now is None else now
        return self.visible() and (self.pop_started is None or self.pop_effect_age(now) is not None)

    def pet_interactive(self):
        return self.visible() and self.pop_started is None

    def configure(self, prefs):
        if self.pingpong is not None and any(
            key in prefs and prefs[key] != self.prefs.get(key)
            for key in ('senseCursor', 'avatarSize', 'objectScales')
        ):
            self.stop_pingpong()
        self.prefs.update(prefs)
        if not self.prefs.get('popEnabled',True):
            self.strong_throws.clear()
            if self.pop_started is not None:
                self.pop_return_at = min(self.pop_return_at,time.monotonic())
        if not self.prefs.get('senseCursor', True):
            self._reset_cursor_motion()
        if self.prefs.get('toyAppearance','peanut') in ('peanut','ball'):
            self.ball.appearance=self.prefs.get('toyAppearance','peanut')
        self.intelligence.enabled = self.prefs.get('adaptiveBehavior', True)
        self.intelligence.learn_routine = self.prefs.get('learnRoutine', True)
        if not self.intelligence.enabled:
            self.intelligence.clear_goal()
            self.behavior.adaptive_goal = None
        size = float(self.prefs.get('avatarSize', 136)) / 2
        self.body.half_w = self.body.half_h = max(24., min(100., size))
        for item in self.objects.values():
            if hasattr(item, 'apply_scale'):
                item.apply_scale(object_scale(item, self.prefs.get('avatarSize', 136), self.prefs.get('objectScales', {})))
            if hasattr(item, 'body'):
                self.fit(item.body, margin=0.)
                item.place(item.body.x, item.body.y)
            elif hasattr(item, 'place'):
                area = self.bounds((item._cx, item._cy))
                item.place(max(area[0]+item.width()/2, min(area[2]-item.width()/2, item._cx)),
                           max(area[1]+item.height()/2, min(area[3]-item.height()/2, item._cy)))
        if self.mesa.sentado:
            self.mesa.ancora = (self.mesa.caderno.x(), self.mesa.caderno.y())
            self.state.desk_top = self.mesa.caderno.y()
        self.mischief.interval = self.prefs.get('mischiefInterval', 300)
        self.mischief.max_objects = self.prefs.get('maxObjects', 3)
        self.mischief.online_reactions = self.prefs.get('onlineReactions', True)
        if not self.prefs.get('onlineReactions', True): self.mischief_ctl.clear_memes()
        if not self.prefs.get('mischiefEnabled', True): self.mischief_ctl.clear()
        self.fit(self.body)

    def desktop(self, data):
        self.displays = data['areas']
        self.areas = [(a['x'], a['y'], a['x'] + a['width'], a['y'] + a['height']) for a in self.displays]
        self.monitors = [(a.get('monitorX', a['x']), a.get('monitorY', a['y']), a.get('monitorX', a['x']) + a.get('monitorWidth', a['width']), a.get('monitorY', a['y']) + a.get('monitorHeight', a['height'])) for a in self.displays]
        if self.pingpong is not None and self.pingpong.area not in self.areas:
            self.stop_pingpong()
        self.blocked.clear()
        self.excluded = set(data.get('exclude', []))
        self.fit(self.body)
        self.fit(self.ball.body, margin=0.)
        for obj in self.objects.values():
            if isinstance(obj, FloatingThing):
                area = self.bounds((obj._cx, obj._cy))
                obj.place(max(area[0] + obj.width()/2, min(area[2] - obj.width()/2, obj._cx)), max(area[1] + obj.height()/2, min(area[3] - obj.height()/2, obj._cy)))
        if self.mesa.sentado: self.mesa.ancora = (self.mesa.caderno.x(), self.mesa.caderno.y())

    def native_point(self, x, y):
        for a in self.displays:
            scale = a.get('scaleFactor', 1)
            nx, ny = a.get('nativeX', a['x']), a.get('nativeY', a['y'])
            if nx <= x < nx + a.get('monitorWidth', a['width']) * scale and ny <= y < ny + a.get('monitorHeight', a['height']) * scale:
                return a.get('monitorX', a['x']) + (x - nx) / scale, a.get('monitorY', a['y']) + (y - ny) / scale
        return x, y

    def read_context(self, now):
        if now - self.last_native < .5: return
        self.last_native = now
        import sys
        if sys.platform != 'win32': return
        try:
            from pestinha.plataforma import windows as native
            self.idle = native.ocioso_segundos() if self.prefs.get('senseIdle', True) else None
            active = native.processo_ativo() if self.prefs.get('senseApp', True) else 'unknown'
            self.activity = detect_activity(active, self.idle or 0., self.prof['away_after'])
            self.senses.on_events(self.tracker.observe(active, self.activity))
            self.platforms = []
            previous_blocked=set(self.blocked)
            self.blocked.clear()
            if self.prefs.get('senseWindows', True):
                windows = []
                for hwnd, (left, top, right, _bottom), maximized in native.janelas_visiveis(self.excluded):
                    style = native.win32gui.GetWindowLong(hwnd, native.win32con.GWL_STYLE)
                    extended = native.win32gui.GetWindowLong(hwnd, native.win32con.GWL_EXSTYLE)
                    if extended & native.win32con.WS_EX_LAYERED:
                        continue
                    windows.append(((left, top, right, _bottom), maximized, bool(style & (native.win32con.WS_CAPTION | native.win32con.WS_THICKFRAME))))
                    left, top = self.native_point(left, top)
                    right, _ = self.native_point(right, _bottom)
                    if not maximized: self.platforms.append((hwnd, left + 10, right, top))
                self.blocked = fullscreen_monitors(windows, self.displays)
            if self.available_areas():
                if previous_blocked != self.blocked:
                    self.fit(self.body)
                    self.fit(self.ball.body, margin=0.)
                    for obj in self.objects.values():
                        area=self.bounds((obj._cx,obj._cy))
                        obj.place(max(area[0]+obj.width()/2,min(area[2]-obj.width()/2,obj._cx)),max(area[1]+obj.height()/2,min(area[3]-obj.height()/2,obj._cy)))
                    if self.mesa.sentado:self.mesa.ancora=(self.mesa.caderno.x(),self.mesa.caderno.y())
            self.native_error = None
        except Exception as error:
            self.native_error = str(error)

    def interact(self, event):
        now = time.monotonic()
        kind = event.get('type')
        if kind == 'pingpong':
            if self.pingpong is not None:
                self.stop_pingpong()
                return None
            return self.start_pingpong(now)
        if self.pingpong is not None:
            if kind in ('hold-start','drag-start','drag','drag-end','poke','spin'):
                return
            if kind in ('panic','hide','sleep','quiet','ball','play','work','notebook',
                        'corner','mischief','celebrate','reaction-now','reset-memory'):
                self.stop_pingpong()
        if kind == 'panic':
            self.panicked = not self.panicked
            if self.panicked:self._cancel_holds(now)
            self.save();return
        if kind == 'hide':
            self.hidden = bool(event.get('value'))
            if self.hidden:self._cancel_holds(now)
            return
        if kind == 'monitor':
            self.monitor_open = bool(event.get('value'))
            self.last_monitor_snapshot = -1.
            return
        if kind == 'panel':
            self.panel = bool(event.get('value'))
            if self.panel:
                self._reset_cursor_motion()
                if self.pingpong is None:
                    self.play.stop_chase()
                    self.play_reaction = {}
            return
        if kind == 'reaction-now':
            visible = self.visible()
            enabled = self.prefs.get('mischiefEnabled', True) and self.prefs.get('onlineReactions', True)
            allowed = visible and enabled
            accepted = self.mischief_ctl.request_online_reaction(
                now, self.state.emotion,
                enabled=(allowed and not self.body.held))
            reason = None if accepted else ('hidden_panicked_or_no_active_display' if not visible else
                      'network_or_mischief_disabled' if not enabled else
                      'being_dragged' if self.body.held else
                      'maximum_objects_or_network_unavailable')
            decision = dict(action='attempt_online_reaction' if accepted else 'request_refused', target=None,
                            intensity=1., duration=0., source='explicit_user_request',
                            refusal_reason=reason,
                            factors=dict(emotion=self.state.emotion, drives=dict(energy=self.drives.energy,
                            contact=self.drives.contact), neural={k: self.rates.get(k, 0.) for k in ('CHEER','WATCH','DROWSE')}))
            self.intelligence.current_decision = decision
            self.intelligence.history.append(dict(decision))
            return
        if kind == 'hover': self.hover = bool(event.get('value')); return
        if kind == 'reset-memory': self.reset_learning(); return
        if kind == 'cursor':
            if self.prefs.get('senseCursor', True):
                self.cursor = (event['x'], event['y'])
                self._track_cursor(now)
            else:
                self._reset_cursor_motion()
            return
        if kind == 'hold-end':
            self._release_hold(now,event.get('cancelled',False) or self.panicked or self.hidden)
            return
        if self.panicked or self.hidden: return
        if self.pop_started is not None and (
            kind in ('hold-start','poke','spin','caress','sleep','wake','work','play','celebrate','corner')
            or kind in ('drag-start','drag','drag-end') and event.get('id') is None
        ):
            return
        self.last_input = now
        if kind == 'hold-start':
            self._start_hold(now)
        elif kind in ('drag-start', 'drag', 'drag-end'):
            item_id = event.get('id')
            target = self.objects.get(str(item_id)) if item_id is not None else None
            if item_id is not None and target is None:
                return
            pet_was_held = target is None and self.held_since is not None
            body = target.body if target and hasattr(target, 'body') else self.body
            if target and not hasattr(target, 'body'):
                self.scene_dragging = kind != 'drag-end'
                target.place(event['x'], event['y'])
                return
            moved = math.hypot(event['x']-body.x, event['y']-body.y) >= 3.
            body.held = kind != 'drag-end'
            body.vx=body.vy=body.omega=0.
            body.x, body.y = event['x'], event['y']
            if target: target.dragging = body.held; target.last_handled = now
            else:
                if kind!='drag-end':self._start_hold(now)
                self.senses.set_dragging(body.held)
                self.state.pressing = body.held
                self.drives.touched('drag')
                self.conditioning.outcome(now)
            self.fit(body)
            if (target is self.ball and not event.get('cancelled')
                    and (kind == 'drag-start' or moved)):
                self._notice_toy_move(now)
            if kind == 'drag-end':
                body.grounded=False;body.platform=None
                if target is None:
                    self._release_hold(now,event.get('cancelled',False))
                if not event.get('cancelled') and (target is None or target.kind=='ball'):
                    for axis in ('vx','vy'):
                        value=event.get(axis,0.)
                        setattr(body,axis,max(-2500.,min(2500.,value)) if type(value) in (int,float) and -math.inf<value<math.inf else 0.)
                    body.omega=body.vx*.35
                    speed=math.hypot(body.vx,body.vy)
                    if target is None and speed>=700:
                        self.senses.thrown(min(1.,speed/2000.))
                        self.drives.stimulate('throw');self.drives.touched('throw')
                        self.in_flight=True
                        if pet_was_held:
                            self._record_strong_throw(now)
        elif kind == 'poke':
            self.senses.poke(); self.drives.touched('poke'); self.drives.stimulate('poke'); self.memory.on_interaction(); self.conditioning.outcome(now)
            if self.sleep.asleep: self.sleep.wake(True)
        elif kind == 'caress':
            if self.intelligence.enabled: self.intelligence.feedback(.8, now)
            self.state.mark_caress(now); self.drives.touched('caress'); self.memory.on_interaction()
            if self.release_reaction.get('until',0)>now:
                shortened=now+(self.release_reaction['until']-now)*.35
                self.release_reaction['until']=max(shortened,self.release_reaction.get('arrives',now))
                self.release_reaction['intensity']*=.5
        elif kind == 'quiet':
            self.intelligence.feedback(-.8, now)
            self.quiet_until = now+30
            self.behavior.adaptive_goal = 'watch'
            self.behavior.drop_carried()
            self.play.stop_chase()
            decision = dict(action='watch', target=None, intensity=1., duration=30.,
                            source='explicit_user_command', factors=dict(reason='quiet command'))
            self.intelligence.current_decision = decision
            self.intelligence.history.append(dict(decision))
        elif kind == 'spin': self.body.omega += max(-500, min(500, event.get('value', 0)))
        elif kind == 'sleep':
            self.play.stop_chase()
            self.play_reaction = {}
            self.drives.energy = .1
            self.sleep.fall_asleep()
            self.state.emotion = 'dormindo';self.behavior.on_emotion('dormindo', now)
            self.intelligence.current_decision = dict(action='sleep',target='asleep',intensity=1.,duration=0.,source='explicit_user_command',factors={})
            self.intelligence.history.append(dict(self.intelligence.current_decision))
        elif kind == 'wake':
            self.sleep.wake(startled=False)
            self.state.emotion = self.emotion.current
            self.behavior.on_emotion(self.state.emotion, now)
            self.intelligence.current_decision = dict(action='wake',target='awake',intensity=1.,duration=0.,source='explicit_user_command',factors={})
            self.intelligence.history.append(dict(self.intelligence.current_decision))
        elif kind == 'work':
            allowed = (not self.sleep.asleep and self.drives.energy > .25
                       and self.state.emotion not in ('triste','bravo','dramatico','dormindo'))
            if allowed: self.mesa.pedir(now)
            self.intelligence.current_decision = dict(action='work' if allowed else 'request_refused',target='notebook' if allowed else None,
                    intensity=1.,duration=0.,source='explicit_user_request',
                    refusal_reason=None if allowed else 'low_energy_or_unwilling_mood',factors=dict(emotion=self.state.emotion,energy=self.drives.energy,neural={'SENTAR':self.rates.get('SENTAR',0.)}))
            self.intelligence.history.append(dict(self.intelligence.current_decision))
        elif kind == 'play':
            distance = math.dist((self.body.x,self.body.y),(self.ball.body.x,self.ball.body.y))
            allowed = (self.visible() and not self.sleep.asleep and not self.body.held and self.body.grounded
                       and not self.mesa.sentado and not self.behavior.mission and not self.state.protest_stage and self.drives.energy > .2
                       and self.body.upright() and not self.state.castigo and not self.behavior.canto
                       and self.behavior.fuga_alvo is None and not self.state.caressing(now)
                       and not self.ball_stored and self.ball.isVisible() and not self.ball.dragging and distance <= 220
                       and self.state.emotion in ('feliz','curioso','contente','bravo'))
            actions = ['throw'] if self.state.emotion == 'bravo' else ['kick']
            action = self.intelligence.choose('play_request',actions,rates=self.rates,emotion=self.state.emotion,
                    energy=self.drives.energy,contact=self.drives.contact,duration=1.,source='explicit_user_request') if allowed else None
            if action:
                self.play.requested_action=action;self.play.next_at=0.
                self.intelligence.clear_goal();self.behavior.adaptive_goal=None;self.quiet_until=0.
            self.intelligence.current_decision = dict(action='play' if action else 'request_refused',target=action,
                    intensity=1.,duration=1.,source='explicit_user_request',
                    refusal_reason=None if action else 'toy_unavailable_or_low_energy_or_unwilling_mood',
                    factors=dict(emotion=self.state.emotion,energy=self.drives.energy,distance=distance))
            self.intelligence.history.append(dict(self.intelligence.current_decision))
        elif kind == 'celebrate':
            allowed = (self.visible() and not self.sleep.asleep and self.drives.energy > .2
                       and not self.body.held
                       and not self._shy_returning(now)
                       and self.state.emotion in ('feliz','contente') and now >= self.festa.request_ready_at)
            if allowed: self.festa.requested=True
            self.intelligence.current_decision = dict(action='celebrate' if allowed else 'request_refused',target='fireworks' if allowed else None,
                    intensity=1.,duration=3.2,source='explicit_user_request',
                    refusal_reason=None if allowed else 'low_energy_or_unwilling_mood_or_cooldown',
                    factors=dict(emotion=self.state.emotion,energy=self.drives.energy,neural={'CHEER':self.rates.get('CHEER',0.)}))
            self.intelligence.history.append(dict(self.intelligence.current_decision))
        elif kind == 'notebook': self.mesa.alternar_notebook()
        elif kind == 'corner': self.castigo.toggle(self.bounds())
        elif kind == 'ball':
            self.ball_stored = not self.ball_stored
            self.ball.setVisible(not self.ball_stored)
            self.play.stop_chase()
            self.play_reaction = {}
        elif kind == 'mischief': self.mischief_ctl.pedir(now)
        elif kind == 'dismiss':
            obj = self.objects.get(str(event.get('id')))
            if obj and obj.kind in ('meme','note','sign'): obj.clicked.emit(obj)

    def _start_hold(self,now):
        self.in_flight=False
        if self.held_since is None:
            self.held_since=now
            self.release_reaction={}
            self.drives.touched('drag')
            if self.mesa.sentado:
                self.mesa.levantar_arrancado(now)
                self.mesa.caderno.set_working(False)
                self.state.at_desk=False;self.state.desk_top=None
        self.body.held=True;self.state.pressing=True;self.senses.set_dragging(True)
        self.body.grounded=False;self.body.platform=None
        self.body.vx=self.body.vy=self.body.omega=0.
        self.conditioning.set_cue('PRESS',True,now)

    def start_pingpong(self, now):
        """Reserva os dois corpos existentes para uma partida e guarda a posição de passeio."""
        if self.pingpong is not None:
            return None
        if not self.visible():
            return 'Mostre a Bolha para começar uma partida.'
        if self.pop_started is not None or now<self.release_reaction.get('arrives',0.):
            return 'A Bolha ainda está voltando. Tente daqui a pouco.'
        if not self.prefs.get('senseCursor',True):
            return 'Ative a leitura do cursor nas configurações para usar a raquete.'
        if self.sleep.asleep or self.drives.energy <= .16:
            return 'A Bolha está descansando. Tente quando ela estiver acordada.'
        if self.castigo.dentro or self.body.held or self.ball.dragging:
            return 'Libere a Bolha e o brinquedo antes de iniciar a partida.'
        try:
            match = PingPong(self.bounds(),self.body.half_w,self.ball.body.half_w)
        except ValueError:
            return 'A área disponível nesta tela é pequena para jogar pingue-pongue.'
        self._pingpong_origin = (
            [(body.x,body.y,body.angle,body.grounded,body.surface,body.platform)
             for body in (self.body,self.ball.body)],
            self.ball_stored,self.ball.isVisible(),self.ball.roll_angle,
        )
        self.play.stop_chase()
        self.play_reaction = {}
        self.release_reaction = {}
        self.play.requested_action = None
        self.festa.requested = False
        self.ball.last_handled = -math.inf
        self.toy_tracker.away = False
        self.behavior.drop_carried()
        self.intelligence.clear_goal()
        self.behavior.adaptive_goal = None
        if self.mesa.sentado:
            self.mesa.levantar_arrancado(now)
            self.mesa.caderno.set_working(False)
        self.state.at_desk = False
        self.state.desk_top = None
        self.state.emotion = 'atento'
        self.landing = 0.
        self.ball_stored = False
        self.ball.show()
        self.pingpong = match
        self._place_pingpong_actors()
        return None

    def stop_pingpong(self):
        if self.pingpong is None:
            return
        self.pingpong = None
        poses,self.ball_stored,toy_visible,self.ball.roll_angle = self._pingpong_origin
        self._pingpong_origin = None
        for body,pose in zip((self.body,self.ball.body),poses):
            body.x,body.y,body.angle,body.grounded,body.surface,body.platform = pose
            body.vx = body.vy = body.omega = 0.
            self.fit(body,margin=0.)
        self.ball.setVisible(toy_visible)
        self.ball.place()
        self.play_reaction = {}
        self.state.emotion = self.behavior.emotion = self.emotion.current
        self._reset_cursor_motion()

    def pingpong_paused(self):
        if self.pingpong is None or self.pingpong.finished:
            return False
        left,top,right,bottom = self.pingpong.area
        return self.panel or not (left<=self.cursor[0]<right and top<=self.cursor[1]<bottom)

    def _place_pingpong_actors(self):
        match = self.pingpong
        body,toy = self.body,self.ball.body
        body.angle = max(-12.,min(12.,(match.pet_y-body.y)*2.))
        body.x,body.y = match.pet_x,match.pet_y
        toy.x,toy.y = match.ball_x,match.ball_y
        for actor in (body,toy):
            actor.vx = actor.vy = actor.omega = 0.
            actor.grounded = True
            actor.platform = None
        self.ball.place()
        self._look_at_point((toy.x,toy.y))

    def _tick_pingpong(self, dt, now):
        match = self.pingpong
        if self.pingpong_paused():
            match.clear_pointer()
            return
        if match.finished:
            return
        if now-self.last_think >= .1:
            self.think(min(.1,now-self.last_think),now)
            self.last_think = now
        before = match.ball_x
        event = match.step(dt,self.cursor,self.state.tone.vigor())
        self.ball.roll_angle += (match.ball_x-before) / max(1.,self.ball.body.half_w)
        self._place_pingpong_actors()
        if event in ('player_hit','pet_hit'):
            self.senses.kick('NOVELTY',.22)
            self.drives.stimulate('novelty',.3)
            self.drives.touched('poke',.2)
        if event in ('pet_hit','player_point','pet_point'):
            kind = {'pet_hit':'pingpong_rebatida','player_point':'assustado','pet_point':'feliz'}[event]
            if match.finished and match.winner=='pet':
                kind='comemorando'
            duration = .42 if event == 'pet_hit' else 1.15
            self.play_reaction = dict(kind=kind,started=now,until=now+duration,intensity=.8)
            if event == 'pet_hit':
                speed = math.hypot(match.vx,match.vy)/match.speed_scale
                self.play_reaction['intensity'] = .62+.38*min(1.,speed/780.)
                self.play_reaction['heading'] = math.degrees(math.atan2(match.vy,match.vx))
        if now-self.last_save >= 30:
            self.save()
            self.last_save = now

    def _cancel_holds(self,now):
        self._release_hold(now,True)
        self.scene_dragging=False
        for item in self.objects.values():
            if hasattr(item,'body') and (item.body.held or item.dragging):
                item.body.held=item.dragging=False
                item.body.vx=item.body.vy=item.body.omega=0.
                item.body.grounded=False;item.body.platform=None

    def _record_strong_throw(self, now):
        """Só solturas fortes da personagem entram na janela móvel de um minuto."""
        if not self.prefs.get('popEnabled',True):
            return
        while self.strong_throws and now-self.strong_throws[0] >= THROW_WINDOW_SECONDS:
            self.strong_throws.popleft()
        self.strong_throws.append(now)
        if len(self.strong_throws) < self.prefs.get('popThrowLimit',12):
            return
        self.strong_throws.clear()
        self.pop_started = now
        self.pop_return_at = now+POP_RETURN_SECONDS
        self.festa.requested = False
        self.body.vx = self.body.vy = self.body.omega = 0.
        self.body.grounded = False
        self.in_flight = False
        self.landing = 0.
        self.landing_reaction = {}
        self.release_reaction = {}
        self.play_reaction = {}
        self.play.stop_chase()
        self.behavior.drop_carried()
        self.behavior.adaptive_goal = None
        self.intelligence.clear_goal()
        if self.sleep.asleep:
            self.sleep.wake(startled=False)
        self.senses.impact(.85)

    def _return_from_pop(self, now):
        left,top,right,bottom = self.bounds()
        body = self.body
        inset = min((right-left)/2.,body.half_w+16.)
        anchor = self.cursor[0] if self.prefs.get('senseCursor',True) else body.x
        body.x = left+inset if anchor>(left+right)/2. else right-inset
        body.y = max(top+body.half_h,bottom-body.half_h)
        body.angle = 0.
        body.grounded = True
        body.surface = bottom
        body.platform = None
        self.pop_started = None
        self.pop_return_at = 0.
        anticipation = self.conditioning.V.get('PRESS',0.)
        tone = self.state.tone.r
        shy = min(1.,max(.4,.58+.27*tone.get('SAD',0.)+.2*anticipation-.16*tone.get('SETTLE',0.)))
        inward = 1. if body.x<(left+right)/2. else -1.
        self.release_reaction = dict(kind='pop_return',started=now,until=now+3.+3.*shy,
                                     intensity=shy,inward=inward,arrives=now+1.3+.3*shy)
        self.state.emotion = self.behavior.emotion = 'timido'
        self.senses.kick('NOVELTY',.32)

    def _track_landing(self, now):
        if self.body.landing_contact is None:
            return
        speed,angle = self.body.landing_contact
        if speed < 125.:
            return
        orientation = abs(angle)
        kind = ('pouso_em_pe' if orientation<45. else
                'pouso_de_lado' if orientation<135. else 'pouso_invertido')
        duration = .9 if kind=='pouso_de_lado' else .62
        self.landing_reaction = dict(kind=kind,started=now,until=now+duration,
                                     intensity=max(.3,min(1.,speed/1050.)),angle=angle)

    def _shy_returning(self, now):
        return self.release_reaction.get('kind')=='pop_return' and now<self.release_reaction['until']

    def _release_hold(self,now,cancelled=False):
        started=self.held_since
        if self.body.held or started is not None:
            self.body.vx=self.body.vy=self.body.omega=0.
            self.body.grounded=False;self.body.platform=None
        self.body.held=False;self.state.pressing=False;self.senses.set_dragging(False)
        self.held_since=None
        if cancelled:self.in_flight=False
        if started is None:return
        elapsed=max(0.,now-started)
        if cancelled:
            self.release_reaction={}
        elif elapsed>=1.2:
            # O mesmo gesto muda com os motores e a associação aprendida de PRESS.
            motors=self.state.tone.r
            anger=motors.get('ANGRY',0)
            anticipation=self.conditioning.V.get('PRESS',0)
            intensity=min(1.,.45*anger+.35*min(1.,elapsed/5)+.2*anticipation)
            if anticipation>.55 or motors.get('SAD',0)>anger+.3:kind='timido'
            elif anger>.55 and elapsed>=4:kind='birra'
            elif motors.get('SETTLE',0)>.5 and anger<.4:kind='sacudir'
            else:kind='bravo'
            self.release_reaction=dict(kind=kind,started=now,until=now+2+3*intensity,intensity=intensity)
            self.conditioning.outcome(now)
        self.conditioning.set_cue('PRESS',False,now)

    def _reset_cursor_motion(self):
        self.cursor_sample = None
        self.cursor_velocity = (0., 0.)
        self.mouse_moved_at = -1e9
        self.cursor_toy_near = False

    def _track_cursor(self, now):
        if self.cursor_sample is None:
            self.cursor_sample = (self.cursor, now)
            self.cursor_velocity = (0., 0.)
            return False
        prev_cursor, prev_now = self.cursor_sample
        dt = now - prev_now
        if math.dist(self.cursor, prev_cursor) > 1.:
            self.cursor_velocity = (((self.cursor[0] - prev_cursor[0]) / dt,
                                     (self.cursor[1] - prev_cursor[1]) / dt)
                                    if .001 <= dt <= .15 else (0., 0.))
            self.cursor_sample = (self.cursor, now)
            self.mouse_moved_at = now
            return True
        if dt > .05 or dt < 0:
            self.cursor_velocity = (0., 0.)
            self.cursor_sample = (self.cursor, now)
        return 0 <= now - self.mouse_moved_at <= .02

    def _sense_toy_cursor(self,now):
        if not self.prefs.get('senseCursor',True) or not self.visible():
            self._reset_cursor_motion()
            return
        if (self.panel or self.ball_stored or not self.ball.isVisible()
                or self.ball.dragging or self.ball.body.held
                or self.body.held or self.held_since is not None
                or self.state.pressing or self.scene_dragging):
            self.cursor_toy_near = False
            return
        moved=self._track_cursor(now)
        radius=self.ball.body.half_w+24
        near=math.dist(self.cursor,(self.ball.body.x,self.ball.body.y))<radius
        if near and not self.cursor_toy_near and now>=self.next_toy_attention:
            self.senses.kick('NOVELTY',.35)
            self.behavior.look_at(self.ball.body.x,self.ball.body.y,now)
            self.next_toy_attention=now+2.5
        if near and moved:
            pushed_at = push_from_cursor(
                self.ball,self.cursor,self.cursor_velocity,now,self.last_toy_push,radius=radius)
            if pushed_at != self.last_toy_push:
                self.last_toy_push = pushed_at
                self.ball.last_handled = now
                self._notice_toy_move(now)
        self.cursor_toy_near=near

    def _notice_toy_move(self, now):
        if (not self.prefs.get('roaming',True) or not self.visible() or self.panel
                or self.ball_stored or not self.ball.isVisible() or self.sleep.asleep
                or self.body.held or self.castigo.dentro or now < self.quiet_until
                or self.pop_started is not None or self._shy_returning(now)):
            return
        reaction = self.play.notice_toy_move(now, self.body, self.ball)
        if reaction == 'taken':
            self.senses.kick('TOY_TAKEN', .45 if self.play.teases == 1 else .9)
            if self.play.teases >= 2:
                anger = self.state.tone.r.get('ANGRY',0.)
                self.play_reaction = dict(kind='brinquedo_frustrado',started=now,until=now+2.8,
                                          intensity=min(1.,.70+.10*(self.play.teases-2)+.30*anger))

    def _focus_gaze(self, now):
        if (self.panel or self.sleep.asleep or self.state.dizzy(now) or self.state.caressing(now)
                or self.state.at_desk or self.state.castigo or self.state.protest_stage==3):
            return
        reaction = self.release_reaction
        released_angry = reaction.get('until',0)>now and reaction.get('kind') in ('bravo','birra')
        toy_angry = (self.play_reaction.get('until',0)>now
                     and self.play_reaction.get('kind')=='brinquedo_frustrado')
        cursor_enabled = self.prefs.get('senseCursor',True)
        nearby = math.dist(self.cursor,(self.body.x,self.body.y)) < 390.
        if cursor_enabled and (released_angry or toy_angry):
            point = self.cursor
        elif self.behavior.toy_action in ('chase','hop'):
            point = self.ball.body.x,self.ball.body.y
        elif cursor_enabled and nearby and now-self.mouse_moved_at < 1.8:
            point = self.cursor
        else:
            return
        self._look_at_point(point)

    def _look_at_point(self, point):
        dx,dy = point[0]-self.body.x,point[1]-self.body.y
        distance = math.hypot(dx,dy) or 1.
        angle = math.radians(self.body.angle)
        self.state.gaze = ((dx*math.cos(angle)+dy*math.sin(angle))/distance,
                           (-dx*math.sin(angle)+dy*math.cos(angle))/distance)

    def _toy_contact(self, previous_pet, previous_toy, now):
        """O contato circular reflete o brinquedo, inclusive entre dois quadros."""
        pet, toy = self.body, self.ball.body
        if (self.ball_stored or not self.ball.isVisible() or self.panel or pet.held
                or toy.held or self.ball.dragging or self._shy_returning(now)):
            return
        if math.dist(previous_pet,(pet.x,pet.y))>250. or math.dist(previous_toy,(toy.x,toy.y))>250.:
            return
        radius = pet.half_w+toy.half_w
        start = previous_toy[0]-previous_pet[0],previous_toy[1]-previous_pet[1]
        end = toy.x-pet.x,toy.y-pet.y
        delta = end[0]-start[0],end[1]-start[1]
        distance = math.hypot(*end)
        normal = end
        if math.hypot(*start)>radius:
            a = delta[0]**2+delta[1]**2
            b = 2.*(start[0]*delta[0]+start[1]*delta[1])
            c = start[0]**2+start[1]**2-radius**2
            discriminant = b*b-4.*a*c
            if a<=1e-12 or discriminant<0.:
                return
            contact = (-b-math.sqrt(discriminant))/(2.*a)
            if not 0.<=contact<=1.:
                return
            normal = start[0]+delta[0]*contact,start[1]+delta[1]*contact
        elif distance>=radius:
            return
        length=math.hypot(*normal)
        nx,ny=(normal[0]/length,normal[1]/length) if length>1e-8 else (1.,0.)
        toy.x,toy.y=pet.x+nx*(radius+.5),pet.y+ny*(radius+.5)
        incoming=(toy.vx-pet.vx)*nx+(toy.vy-pet.vy)*ny
        if incoming<0.:
            restitution=.78 if incoming < -80. else 0.
            toy.vx-=(1.+restitution)*incoming*nx
            toy.vy-=(1.+restitution)*incoming*ny
            toy.grounded=False;toy.platform=None
        self.fit(toy,margin=0.)
        self.ball.place()
        if incoming>=-90.:
            return
        strength=min(1.,-incoming/1200.)
        self.senses.impact(strength*.35)
        self.senses.kick('NOVELTY',.35)
        asleep=self.sleep.asleep
        if asleep:
            self.sleep.wake(startled=True)
        playing=(not asleep and self.drives.energy>.18
                 and self.state.emotion in ('feliz','contente','curioso','atento','observando')
                 and now>=self.quiet_until)
        self.play_reaction=dict(kind='brinquedo_rebatida' if playing else 'brinquedo_susto',
                                started=now,until=now+(.42 if playing else .75),
                                intensity=max(.35,strength),
                                heading=math.degrees(math.atan2(toy.vy,toy.vx)))
        self._look_at_point((toy.x,toy.y))

    def _play_expression(self,now):
        attempt=self.behavior.last_play
        kind=None;duration=1.6
        if attempt and attempt['started']!=self.last_play_attempt:
            self.last_play_attempt=attempt['started']
            if attempt['action']:
                kind='brinquedo_rebatida';duration=.42
            else:
                return
        elif self.behavior.toy_action in ('chase','hop'):
            current = self.play_reaction
            if current.get('kind')=='brinquedo_perseguindo':
                current['until'] = now+.3
            elif now >= current.get('until',0.):
                self.play_reaction = dict(kind='brinquedo_perseguindo',started=now,until=now+.3,intensity=.8)
            return
        elif (now>=self.next_play_scene and not self.body.held and self.body.grounded
                and not self.panel and not self.sleep.asleep and not self.state.caressing(now)):
            near=not self.ball_stored and self.ball.isVisible() and math.dist(
                (self.body.x,self.body.y),(self.ball.body.x,self.ball.body.y))<190
            if near and self.state.tone.r.get('STARTLE',0)>.35:
                kind='brinquedo_susto';duration=1.3
            elif self.mesa.sentado and self.behavior.play_pull>.5:
                kind='fingir_trabalho';duration=2.2
            elif near and self.behavior.adaptive_goal=='play' and self.behavior.play_pull>.3:
                kind='preparar_bote';duration=.8
        if kind:
            intensity=max(.35,min(1.,self.behavior.play_pull+self.state.tone.r.get('CHEER',0)*.3))
            self.play_reaction=dict(kind=kind,started=now,until=now+duration,intensity=intensity)
            if kind=='brinquedo_rebatida':
                self.play_reaction['heading']=math.degrees(math.atan2(self.ball.body.vy,self.ball.body.vx))
            self.next_play_scene=now+12

    def reset_learning(self):
        preferences, displays = dict(self.prefs), list(self.displays)
        panicked, excluded = self.panicked, list(self.excluded)
        import os
        backup = self.data_dir / 'backups' / ('learning-' + str(time.time_ns()))
        if self.pet_paths.base.exists():
            backup.parent.mkdir(parents=True,exist_ok=True)
            os.replace(self.pet_paths.base,backup)
            clear_protection_after_backup(self.pet_paths.base)
        # Reinicia a memória escolhida, sem cair numa pasta legada antiga após o backup.
        self.pet_paths.base.mkdir(parents=True,exist_ok=True)
        self.__init__(self.data_dir, self.conteudo.proprio)
        self.panicked = panicked
        self.configure(preferences)
        if displays: self.desktop(dict(areas=displays, exclude=excluded))
        self.save()

    def adapt(self, now):
        if now-self.last_intelligence < 1: return
        self.last_intelligence = now
        allowed = ['watch', 'rest']
        if self.prefs.get('roaming', True):
            allowed += ['explore']
            if not self.ball_stored and self.ball.isVisible() and self.drives.energy > .18:
                allowed += ['play']
            if self.prefs.get('senseCursor', True): allowed += ['attention']
        if not self.mesa.escondido and self.activity in ('PROGRAMMING', 'DESIGNING'): allowed += ['work']
        if self.panel or self.hover or self.body.held or self.sleep.asleep or self.castigo.dentro or self.castigo.fuga or self.protest.stage or self.sad.stage or self.behavior.mission: allowed = []
        decisions_before = self.intelligence.decisions
        try:
            goal = self.intelligence.tick(now, time.time(), self.activity, self.state.emotion, self.rates, self.drives.energy, self.drives.contact, allowed, self.sleep.asleep)
            self.behavior.adaptive_goal = goal
            if not goal:
                self.behavior.adaptive_target = None
            elif self.intelligence.decisions != decisions_before:
                area = self.bounds()
                decision = self.intelligence.current_decision
                record = self.intelligence.history[-1]
                self.behavior.adaptive_target = None
                if goal == 'explore':
                    margin = min(90., (area[2]-area[0])/2)
                    targets = [round(area[0]+margin+(area[2]-area[0]-2*margin)*i/4, 2) for i in range(5)]
                    picked = self.intelligence.choose('explore_target', [str(value) for value in targets],
                                                       rates=self.rates, emotion=self.state.emotion,
                                                       energy=self.drives.energy, contact=self.drives.contact,
                                                       duration=decision['duration'], source='lif+episodic_policy')
                    self.behavior.adaptive_target = float(picked) if picked is not None else targets[2]
                    decision['target'] = self.behavior.adaptive_target
                    self.intelligence.current_decision = decision
                elif goal == 'attention':
                    self.behavior.adaptive_target = max(area[0]+90, min(area[2]-90, self.cursor[0]+170))
                    decision['target'] = self.behavior.adaptive_target
                elif goal in ('play', 'work'):
                    decision['target'] = 'toy' if goal == 'play' else 'notebook'
                record['target'] = decision['target']
        except Exception as error:
            self.intelligence.compatibility = f'Autonomia adicional pausada: {type(error).__name__}'
            self.intelligence.clear_goal()
            self.behavior.adaptive_goal = None
        if now-self.last_metrics >= 30:
            import psutil
            self.app_rss_mib = psutil.Process().memory_info().rss/1048576
            import numpy as np
            self.brain_array_mib = sum(v.nbytes for v in vars(self.brain).values() if isinstance(v,np.ndarray) and v.base is None)/1048576
            self.last_metrics = now

    def decision_snapshot(self):
        return self.intelligence.snapshot()

    def choose_expression(self, candidates, now=None):
        now = time.monotonic() if now is None else now
        return self.intelligence.choose_expression(candidates, self.rates, self.state.emotion,
                                                   self.drives.energy, self.drives.contact, now)

    def think(self, dt, now):
        moving = min(1., abs(self.body.vx) / 200 + (0 if self.body.grounded else 1))
        caressing = self.state.caressing(now)
        self.drives.update(dt, self.prof, self.sleep.asleep, moving, self.emotion.arousal, self.activity == 'AWAY', engaged=self.activity in ('PROGRAMMING', 'DESIGNING'), preso=self.castigo.dentro, visitado=self.castigo.visita > .5)
        if caressing: self.drives.stimulate('caress', dt); self.drives.touched('caress', dt)
        self.castigo.tick_lento(dt)
        inputs = self.senses.update(self.activity, self.idle if self.prefs.get('senseIdle',True) else None, self.drives.channels(), caressing, self.prefs.get('senseCursor',True) and math.dist(self.cursor,self.last_cursor) > 2)
        self.last_cursor = self.cursor
        self.conditioning.set_cue('PRESS', self.state.pressing, now)
        distance = math.dist(self.cursor,(self.body.x,self.body.y))
        self.conditioning.set_cue('APPROACH', self.prefs.get('senseCursor',True) and self.prev_distance is not None and distance < 220 and (self.prev_distance - distance) / max(.01,dt) > 500, now)
        self.prev_distance = distance
        self.conditioning.set_cue('PLACA', self.castigo.perto_da_placa(self.body), now)
        self.conditioning.tick(now)
        inputs['ANTICIPATE'] = self.conditioning.strength()
        inputs['ANTECIPA_PLACA'] = self.conditioning.strength(cues=('PLACA',))
        taken, near = self.toy_tracker.update((self.ball.body.x,self.ball.body.y),(self.body.x,self.body.y),self.ball.handled_by_user(now))
        if taken and not self.ball_stored: self.senses.kick('TOY_TAKEN', .9)
        inputs['TOY_NEAR'] = near if not self.ball_stored else 0
        inputs['PEDIDO'] = max(self.mesa.intensidade_pedido(now), .5 if self.behavior.adaptive_goal == 'work' else 0.)
        inputs.update(self.castigo.sinais(self.body))
        inputs['RECUSA'] = self.request_refused; self.request_refused = 0
        self.brain.stimulate(inputs)
        self.brain.step(min(100, max(1, round(dt * 1000))))
        self.inputs = inputs
        self.rates = self.brain.motor_activity()
        self.state.tone.update(self.rates,dt)
        if self.pingpong is not None or self.pop_started is not None or self._shy_returning(now):
            return
        self.sleep.rates = self.rates
        for protest in (self.protest, self.sad):
            protest.rates = self.rates
            protest.energy = self.drives.energy
            protest.contact = self.drives.contact
        for controller in (self.protest_ctl,self.sad_ctl):
            change = controller.tick(dt,self.state.tone,self.prof,caressing,now,self.drives.channels()['LONELY'])
            if change: controller.on_stage(*change)
        self.state.protest_stage = self.protest.stage if not self.sleep.asleep else 0
        reward = (1. if caressing else 0.) - (1. if self.mischief_ctl.penalty_active(now) else 0.) + self.castigo.punicao(now)
        self.brain.learn(reward,dt,self.prof['learn_rate'])
        emotion = self.emotion.update(self.rates,dt,self.prof,now)
        if self.state.dizzy(now): emotion = 'dramatico'
        self.state.emotion = emotion
        self.behavior.on_emotion(emotion,now)
        self.behavior.canto = self.rates.get('CANTO',0) > 5 and self.sad.stage > 0
        can_sit = self.body.grounded and not self.body.held and not self.sleep.asleep and not self.castigo.dentro and self.castigo.fuga is None
        self.mesa.tick(now,self.brain.pool_rates(),self.rates['SENTAR'],can_sit,self.play)
        self.state.at_desk = self.mesa.sentado
        self.state.desk_top = self.mesa.caderno.y() if self.mesa.sentado else None
        self.behavior.play_pull = pull(self.brain.pool_rates())
        self.play.rates = self.rates
        self.play.energy = self.drives.energy
        self.play.contact = self.drives.contact
        if self.mesa.pop_recusa(): self.request_refused = min(1., .4 + .2 * self.mesa.pedidos_recentes())
        self.sleep.tick(now,self.body,self.in_flight,self.protest.stage,self.behavior.mission)
        if self.sleep.asleep: self.state.emotion = 'dormindo'; self.behavior.on_emotion('dormindo',now)
        self.adapt(now)

    def tick(self, dt, now=None):
        now = time.monotonic() if now is None else now
        dt = min(.05, max(0.,dt))
        if not self.panicked and not self.hidden: self.read_context(now)
        frozen = self.panicked or self.hidden or not self.available_areas()
        if frozen:
            self.festa.requested=False
            self.stop_pingpong()
            self._cancel_holds(now)
            self._reset_cursor_motion()
            self.play.stop_chase()
            if self.paused_at is None: self.paused_at = now
            return
        if self.paused_at is not None:
            elapsed = now - self.paused_at
            self.castigo.deslocar(elapsed); self.mesa.deslocar(elapsed)
            self.memory.deslocar(elapsed)
            self.intelligence.until += elapsed
            self.paused_at = None; self.last_think = now
        if self.pop_started is not None:
            if now >= self.pop_return_at:
                self._return_from_pop(now)
            else:
                if now-self.last_think >= .1:
                    self.think(min(.1,now-self.last_think),now)
                    self.last_think = now
                if not self.ball_stored:
                    self.ball.step(dt,self.bounds((self.ball.body.x,self.ball.body.y)),
                                   self.available_areas(),
                                   [monitor for i,monitor in enumerate(self.monitors) if i not in self.blocked],
                                   [display for i,display in enumerate(self.displays) if i not in self.blocked])
                return
        if self.pingpong is not None:
            if self.pingpong.area in self.available_areas():
                self._tick_pingpong(dt,now)
                return
            self.stop_pingpong()
        self._sense_toy_cursor(now)
        if now - self.last_think >= .1:
            self.think(min(.1,now-self.last_think),now); self.last_think = now
        area = self.bounds()
        areas = self.available_areas()
        monitors = [monitor for i, monitor in enumerate(self.monitors) if i not in self.blocked]
        self.behavior.screen_areas = areas
        self.behavior.rates = self.rates
        self.behavior.energy = self.drives.energy
        self.behavior.contact = self.drives.contact
        self.behavior.toy = (self.ball.body.x,self.ball.body.y) if not self.ball_stored else None
        platforms = getattr(self,'platforms',[]) if self.prefs.get('senseWindows',True) else []
        self.castigo.act(now,self.body,area,self.cursor if self.prefs.get('senseCursor',True) else (1e9,1e9),self.state,self.rates,self.sleep.asleep)
        manual_play = self.play.requested_action is not None
        shy_return = self._shy_returning(now)
        resting = (self.hover or self.panel or shy_return or now < self.quiet_until or not self.prefs.get('roaming',True)) and not manual_play
        self.behavior.tick(dt,now,self.cursor,area,self.prof,platforms,not resting,
                           self.prefs.get('senseCursor',True))
        if manual_play:
            # A situação pode mudar entre o clique e o próximo quadro.
            self.play.requested_action = None
        self._play_expression(now)
        previous_pet=self.body.x,self.body.y
        previous_toy=self.ball.body.x,self.ball.body.y
        self.body.step(dt,area,platforms,areas,monitors,[d for i,d in enumerate(self.displays) if i not in self.blocked])
        self._track_landing(now)
        if self.body.grounded:self.in_flight=False
        if self.mesa.sentado and self.mesa.pin(self.body,now): self.mesa.levantar_arrancado(now); self.protest_ctl.provoke(.1)
        if not self.ball_stored:
            self.ball.step(dt,self.bounds((self.ball.body.x,self.ball.body.y)),areas,monitors,[d for i,d in enumerate(self.displays) if i not in self.blocked])
            self._toy_contact(previous_pet,previous_toy,now)
        self._focus_gaze(now)
        impacts = self.body.pop_impacts()
        self.landing *= math.exp(-dt * 12)
        for strength in impacts:
            self.senses.impact(min(1.,strength / 1600))
            self.landing = max(self.landing,min(1.,strength / 1000))
        self.mesa.set_visible(not self.mesa.escondido)
        self.protest_ctl.carry(now,self.sleep.asleep); self.sad_ctl.carry(now,self.sleep.asleep)
        self.mischief.tick(dt,area[3])
        self.mischief.rates = self.rates
        self.mischief.energy = self.drives.energy
        self.mischief.contact = self.drives.contact
        perms = dict(config.DEFAULT_PERMISSIONS, travessuras=self.prefs.get('mischiefEnabled',True), memes=self.prefs.get('onlineReactions',True), online_reactions=self.prefs.get('onlineReactions',True), fotos=False)
        if not shy_return and not self.castigo.dentro and not self.hover and not self.panel and now >= self.quiet_until and self.intelligence.goal not in ('watch','rest','work'):
            self.mischief_ctl.maybe_act(now,dt,area,self.cursor,self.body,motores=self.rates,activity=self.activity,emotion=self.state.emotion,perms=perms,prof=self.prof,fullscreen=False,asleep=self.sleep.asleep,protest_stage=self.protest.stage,working=self.activity in ('PROGRAMMING','DESIGNING') and not self.mesa.sentado)
        self.festa.rates = self.rates
        self.festa.energy = self.drives.energy
        self.festa.contact = self.drives.contact
        self.festa.tick(now,self.rates,self.state.emotion,self.body,
                        not shy_return and self.visible() and not self.sleep.asleep
                        and not self.body.held and not self.panel and now>=self.quiet_until,dt)
        self.revolucao.rates = self.rates
        self.revolucao.energy = self.drives.energy
        self.revolucao.contact = self.drives.contact
        self.revolucao.tick(now,dt,area,self.cursor,(0,0),self.body,self.visible(),self.protest.stage == 4,[],self.rates.get('PAPEL',0))
        self.memory.tick(now,self.prof["episode_ok"],self.prof["episode_window"])
        if now - self.last_save >= 30: self.save(); self.last_save = now

    def save(self):
        write_json(self.data_dir / 'session.json',dict(panicked=self.panicked))
        self.brain.save(self.pet_paths.nervous)
        self.drives.save(self.pet_paths.drives)
        self.conditioning.save()
        self.memory.save()
        self.intelligence.habits.save()
        self.protest_ctl.save(); self.sad_ctl.save(); self.castigo.salvar()
        x,y = (self._pingpong_origin[0][0][:2] if self._pingpong_origin is not None
               else (self.body.x,self.body.y))
        write_json(self.data_dir / 'position.json',dict(x=x,y=y))

    def snapshot(self):
        now = time.monotonic()
        objects = []
        for obj in list(self.objects.values()):
            data = obj.snapshot()
            if obj.isVisible() and self.visible(): objects.append(data)
        pose = ('held' if self.body.held else 'airborne' if not self.body.grounded else
                'sleeping' if self.sleep.asleep else 'working' if self.mesa.sentado else
                'lying' if not self.body.upright() else 'idle')
        data = dict(ready=True,blocked=list(self.blocked),panicked=self.panicked,x=self.body.x,y=self.body.y,angle=self.body.angle,emotion=self.state.emotion,visible=self.visible(),held=self.body.held,caressing=self.state.feliz_fechado(now),gaze=self.state.gaze,objects=objects,energy=self.drives.energy,stimulation=self.drives.stimulation,lonely=self.drives.contact,protest=self.protest.stage,castigo=self.castigo.dentro,escapes=self.castigo.vitorias['fugir'],activity=self.activity,motors=self.rates,learned=[],neurons=self.brain.N,error=self.native_error,
                    pose=pose,grounded=self.body.grounded,surface=self.body.surface if self.body.grounded else self.bounds()[3],vx=self.body.vx,vy=self.body.vy,landing=self.landing)
        if self.monitor_open:
            if now - self.last_monitor_snapshot >= .25:
                data.update(
                    intelligence=dict(self.intelligence.summary(self.activity,time.time()),appRssMiB=self.app_rss_mib,brainArrayMiB=self.brain_array_mib),
                    learned=self.brain.learned_summary(8),
                    neural=dict(positions=self.brain.pos.tolist(),trace=self.brain.trace.tolist(),kind=self.brain.kind.tolist(),pools=self.brain.pool_rates()))
                self.last_monitor_snapshot = now
        return data
