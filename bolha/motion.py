# SPDX-License-Identifier: GPL-3.0-only
"""Expressões visuais no relógio já existente; nunca modifica o corpo físico."""
import math
from .character import WINK_DURATION, wink_state

QUIRK_SECONDS = dict(stretch=2.3, sneeze=1.65, hiccup=1.6, doze=3.3,
                     ear_wiggle=1.5, wink=WINK_DURATION)
LANDING_POSES = ('pouso_em_pe', 'pouso_de_lado', 'pouso_invertido')
FLOOR_POSES = (*LANDING_POSES, 'deitada')


def _unit(value):
    return max(0., min(1., value))


def _ease(value):
    value = _unit(value)
    return value * value * (3 - 2 * value)


def animation_pose(mode, seconds, strength=1.):
    """Quadro determinístico compartilhado pelo aplicativo e pelas prévias Qt.

    Os campos de desenho mantêm a API do personagem. Os offsets e efeitos
    giram e deformam com a esfera, sem deslocar o centro físico.
    """
    t = max(0., float(seconds));strength = _unit(strength)
    pose = dict(emotion=mode, eye_open=1., ear_tilt=0., ear_raise=0., squash=0.,
                gaze=None, blink=0., blink_left=None, blink_right=None,
                angle_offset=0., zzz_strength=0., zzz_phase=t,
                effect=None, effect_strength=0., effect_phase=t, effect_angle=0., anger=0.,
                body_opacity=1.,visual_scale=1.)
    if mode == 'held':
        irritation = _ease((t - .7) / 3.)
        rage = _ease((t - 1.1) / 2.6) * (.55 + .45 * strength)
        pulse = .88 + .12 * math.sin(t * 14)
        pose.update(emotion='curioso' if t < .7 else 'entediado' if irritation < .3 else 'bravo',
                    eye_open=1.12 - .76 * irritation, ear_raise=1. - 5.4 * irritation,
                    ear_tilt=(16. + 2. * math.sin(t * 18) * rage) * irritation,
                    squash=.03 * irritation * math.sin(t * 6),
                    angle_offset=irritation * (math.sin(t * 5) + .5 * math.sin(t * 8)),
                    effect='bravo', effect_strength=irritation * strength,
                    anger=_unit((.22 * irritation + .78 * rage) * pulse))
    elif mode == 'sleeping':
        closing = _ease(t / 1.8);breath = math.sin(t * math.tau / 4.2)
        pose.update(emotion='sonolento' if t < 1.8 else 'dormindo',
                    eye_open=1. - closing, blink=closing,
                    ear_raise=-1. - 1.5 * closing + .7 * breath, ear_tilt=5. * closing,
                    squash=.055 * breath, angle_offset=1.4 * breath,
                    zzz_strength=_ease((t - 1.4) / 1.2))
    elif mode in ('caress', 'comemorando'):
        joy = .7 + .3 * strength
        pose.update(emotion='feliz' if mode == 'caress' else 'comemorando',
                    ear_raise=1.8 + 1.2 * math.sin(t * 10), ear_tilt=10 * math.sin(t * 11),
                    squash=-.13 * math.sin(t * 8) * joy, angle_offset=5. * math.sin(t * 6) * joy,
                    effect='carinho' if mode == 'caress' else 'comemorando', effect_strength=joy)
    elif mode == 'airborne':
        pose.update(emotion='assustado', eye_open=1.25, ear_raise=2.4,
                    squash=-.15 * strength, angle_offset=2 * math.sin(t * 7))
    elif mode == 'impact':
        rebound = math.exp(-t * 7) * math.cos(t * 18)
        pose.update(emotion='assustado', blink=max(0., 1 - t / .11),
                    ear_raise=-2. * rebound, squash=.23 * rebound * strength,
                    angle_offset=5. * math.exp(-t * 6) * math.sin(t * 16) * strength)
    elif mode == 'bravo':
        rage=(.55+.45*strength)*(.92+.08*math.sin(t*11.))
        pose.update(eye_open=.48-.10*rage,ear_raise=-3.5*rage,
                    ear_tilt=11.*rage,squash=.025*math.sin(t*17.)*rage,
                    angle_offset=2.2*math.sin(t*19.)*rage,
                    anger=rage,effect='bravo',effect_strength=.75*rage)
    elif mode == 'tonto':
        pose.update(emotion='tonto', ear_raise=-1.5, ear_tilt=9 * math.sin(t * 7),
                    squash=.07 * math.sin(t * 9), angle_offset=7 * math.sin(t * 5),
                    effect='tonto', effect_strength=.8)
    elif mode in ('birra', 'sacudir'):
        envelope = math.exp(-t * (1.1 if mode == 'birra' else 2.))
        pulse = .9 + .1 * math.sin(t * 18)
        pose.update(emotion='bravo' if mode == 'birra' else 'contente',
                    eye_open=.48 if mode == 'birra' else 1.,
                    blink=.95 if mode == 'sacudir' and t < .3 else 0.,
                    ear_tilt=18 * math.sin(t * 17) * envelope,
                    ear_raise=-2.6 * envelope if mode == 'birra' else -2 * envelope,
                    squash=.2 * math.sin(t * 15) * envelope * strength,
                    angle_offset=12 * math.sin(t * 16) * envelope * strength,
                    effect='bravo' if mode == 'birra' else None,
                    effect_strength=strength * envelope if mode == 'birra' else 0.,
                    anger=_unit((.45 + .55 * strength) * envelope * pulse) if mode == 'birra' else 0.)
    elif mode == 'preparar_bote':
        crouch = _ease(t / .8)
        pose.update(emotion='atento', eye_open=1.15 - .4 * crouch,
                    ear_raise=-1.5 * crouch, ear_tilt=-6 * crouch,
                    squash=.19 * crouch, angle_offset=4 * math.sin(t * 11) * crouch)
    elif mode == 'brinquedo_frustrado':
        # O abalo cresce com a intensidade, mas a esfera continua no mesmo centro.
        cooldown = 1. - _ease((t-2.05) / .75)
        rage = _ease(t / .24) * (.72 + .28 * strength) * cooldown
        pulse = .89 + .11 * math.sin(t * 9)
        pose.update(emotion='bravo', eye_open=.46 - .08 * rage,
                    ear_raise=-2.8 - 1.1 * rage,
                    ear_tilt=12 * math.sin(t * 22) * rage,
                    squash=.07 * math.sin(t * 19) * rage,
                    angle_offset=6.5 * math.sin(t * 20) * rage,
                    effect='bravo', effect_strength=_unit(rage * strength),
                    anger=_unit(rage * pulse))
    elif mode in ('correndo','brinquedo_perseguindo'):
        stride = t*math.tau*2.
        push = math.sin(stride)
        pose.update(emotion='atento', eye_open=1.16,
                    ear_raise=-1.4*strength+1.1*push,
                    ear_tilt=-9.-6.*strength-3.*math.cos(stride-.6),
                    squash=(.045*push-.035)*strength,
                    angle_offset=(9.+2.7*math.sin(stride-.3))*strength,
                    effect='perseguindo',effect_strength=.28+.4*strength)
    elif mode in ('pingpong_rebatida','brinquedo_rebatida'):
        impact = 1. - _ease(t/.09)
        stretch = _ease((t-.035)/.085)*(1.-_ease((t-.13)/.22))
        pose.update(emotion='atento', eye_open=1.-.56*impact+.24*stretch,
                    ear_raise=-3.2*impact+3.3*stretch, ear_tilt=12.*impact-11.*stretch,
                    squash=(-.20*impact+.17*stretch)*strength,
                    angle_offset=(-5.5*impact+7.5*stretch)*strength,
                    effect='rebatida', effect_strength=strength*(1.-_ease((t-.035)/.22)))
    elif mode == 'pop':
        rupture = t-.13
        squeeze = _ease(t/.075)*(1.-_ease((t-.075)/.055))
        swell = _ease((t-.075)/.055)*(1.-_ease(rupture/.13))
        dissolve = _ease(rupture/.13)
        pose.update(emotion='assustado',eye_open=1.+.3*swell-.4*squeeze,
                    blink=_ease(rupture/.085),ear_raise=2.8*swell-4.*squeeze,
                    ear_tilt=12.*squeeze*math.sin(t*85.),
                    angle_offset=5.*squeeze*math.sin(t*65.),
                    squash=.22*squeeze-.08*swell,
                    body_opacity=1.-dissolve,visual_scale=1.-.08*squeeze+.15*swell,
                    effect='pop',effect_phase=max(0.,rupture),effect_strength=float(rupture>=0.))
    elif mode == 'pop_return':
        pose.update(emotion='timido',eye_open=.98-.11*strength,
                    blink=math.exp(-((t-.73)/.095)**2),
                    ear_raise=-2.*strength,ear_tilt=5.*strength)
    elif mode in LANDING_POSES:
        settle = math.exp(-t*5.2)
        bounce = math.cos(t*20.)*settle
        force = .58+.42*strength
        if mode == 'pouso_em_pe':
            pose.update(emotion='atento',blink=max(0.,1.-t/.105),
                        eye_open=1.+.18*_ease(t/.14)*settle,
                        ear_raise=-3.6*bounce*force,ear_tilt=4.*math.sin(t*21.)*settle,
                        squash=.21*bounce*force)
        elif mode == 'pouso_de_lado':
            relax = _ease((t-.23)/.57)
            rock = math.cos(t*14.)*math.exp(-t*4.4)
            pose.update(emotion='assustado' if t<.22 else 'contente',
                        blink=1.-_ease(t/.18),eye_open=1.08-.37*relax,
                        ear_raise=-3.8*settle-1.4*relax,ear_tilt=14.*rock+5.*relax,
                        angle_offset=-19.*rock*force,squash=.28*bounce*force+.09*relax)
        else:
            pose.update(emotion='assustado' if t<.12 else 'tonto',
                        blink=max(0.,1.-t/.10),ear_raise=-3.7*settle,
                        ear_tilt=10.*math.sin(t*23.)*settle,
                        angle_offset=7.*math.sin(t*23.)*settle,
                        squash=.23*bounce*force,effect='tonto',
                        effect_strength=_ease((t-.08)/.12)*settle)
    elif mode == 'deitada':
        breath = .5-.5*math.cos(t*math.tau/2.4)
        blink = math.exp(-((t%4.7-2.9)/.16)**2)
        pose.update(emotion='contente',blink=blink,eye_open=.71+.13*breath,
                    ear_raise=-1.4+.7*breath,ear_tilt=5.+2.*breath,squash=.09-.027*breath)
    elif mode == 'bote_erro':
        flump = math.exp(-((t - .25) / .16) ** 2)
        wobble = math.sin(t * 13) * math.exp(-t * 1.8)
        pose.update(emotion='tonto' if .3 < t < 1.15 else 'timido',
                    blink=flump, ear_raise=-3 * flump, ear_tilt=12 * wobble,
                    squash=.24 * flump + .10 * wobble,
                    angle_offset=14 * wobble, effect='tonto',
                    effect_strength=.65 * _ease(t / .4) * (1 - _ease((t - 1.) / .6)))
    elif mode == 'brinquedo_susto':
        shock = math.exp(-t * 3)
        pose.update(emotion='assustado', eye_open=1.25, ear_raise=3 * shock,
                    ear_tilt=-12 * shock, squash=-.22 * shock,
                    angle_offset=10 * math.sin(t * 16) * shock)
    elif mode == 'fingir_trabalho':
        caught = _ease((t - .45) / .3)
        pose.update(emotion='entediado' if t < .45 else 'assustado' if t < .8 else 'atento',
                    eye_open=.5 + .7 * caught, ear_raise=-1 + 3 * caught,
                    gaze=(.15 * math.sin(t * 8), .65),
                    squash=.065 * math.sin(t * 15) * caught,
                    angle_offset=2.5 * math.sin(t * 12) * caught)
    elif mode == 'stretch':
        envelope = math.sin(math.pi * _unit(t / QUIRK_SECONDS[mode])) ** 2
        pose.update(emotion='contente', blink=envelope, ear_raise=4. * envelope,
                    ear_tilt=-12 * envelope, squash=-.24 * envelope,
                    angle_offset=9. * math.sin(t * 2.6) * envelope)
    elif mode == 'sneeze':
        anticipation = _ease(t / .7) * (1 - _ease((t - .85) / .25))
        burst = math.exp(-((t - .95) / .12) ** 2)
        recovery = math.exp(-max(0., t - 1.) * 7) * math.sin(max(0., t - 1.) * 19) if t > 1 else 0.
        pose.update(emotion='assustado' if t < .85 else 'contente', blink=_unit(anticipation + burst),
                    ear_raise=2.5 * anticipation - 3 * burst,
                    squash=-.15 * anticipation + .24 * burst + .10 * recovery,
                    angle_offset=-7 * anticipation + 13 * burst + 4 * recovery)
    elif mode == 'hiccup':
        pulse = math.exp(-((t - .35) / .09) ** 2) + .7 * math.exp(-((t - .95) / .09) ** 2)
        pose.update(emotion='curioso', eye_open=1. + .25 * pulse, ear_raise=3 * pulse,
                    squash=-.21 * pulse, angle_offset=7 * pulse)
    elif mode == 'doze':
        closing = _ease(t / 1.25) * (1 - _ease((t - 2.25) / .45))
        startle = math.exp(-((t - 2.65) / .15) ** 2)
        pose.update(emotion='sonolento' if t < 2.5 else 'assustado', blink=closing,
                    ear_raise=-2. * closing + 3. * startle, eye_open=1. + .2 * startle,
                    squash=.13 * closing - .18 * startle, angle_offset=12 * closing - 9 * startle)
    elif mode == 'ear_wiggle':
        envelope = math.sin(math.pi * _unit(t / QUIRK_SECONDS[mode])) ** 2
        pose.update(emotion='curioso', ear_tilt=23 * math.sin(t * 17) * envelope,
                    ear_raise=2. * math.sin(t * 11) * envelope,
                    angle_offset=4 * math.sin(t * 8) * envelope)
    elif mode == 'wink':
        wink = wink_state(_unit(t / WINK_DURATION))
        pose.update(emotion='contente', **{key: value for key, value in wink.items() if key != 'tilt'})
        pose['angle_offset'] = wink['tilt']
    elif mode == 'bravo':
        pulse = .92 + .08 * math.sin(t * 17)
        pose.update(eye_open=.56-.17*strength, ear_raise=-2.1-1.5*strength,
                    ear_tilt=6. * strength + 3. * math.sin(t * 16) * strength,
                    squash=.06 * math.sin(t * 12) * strength,
                    angle_offset=2.5 * math.sin(t * 13) * strength,
                    effect='bravo', effect_strength=strength,
                    anger=_unit((.58 + .42 * strength) * pulse))
    elif mode == 'triste':
        pose.update(ear_raise=-1.2 + .35 * math.sin(t * 2), eye_open=.8,
                    gaze=(0., .8), squash=.045 * math.sin(t * 2), angle_offset=2. * math.sin(t * 1.5))
    elif mode in ('curioso', 'atento', 'travesso'):
        pose.update(ear_tilt=8 * math.sin(t * 3.5), ear_raise=1.1 * math.sin(t * 4),
                    angle_offset=4 * math.sin(t * 2.2), eye_open=1. + .08 * math.sin(t * 3))
    elif mode in ('sonolento', 'entediado'):
        pose.update(ear_raise=-.6, eye_open=.65 + .13 * math.sin(t * 1.8),
                    squash=.045 * math.sin(t * 2), angle_offset=2. * math.sin(t * 1.6))
    elif mode == 'assustado':
        pose.update(eye_open=1.2, ear_raise=1.8, squash=-.08 * math.exp(-t * 2),
                    angle_offset=3. * math.sin(t * 11) * math.exp(-t * 2))
    elif mode in ('contente', 'feliz', 'timido', 'observando', 'dramatico'):
        pose.update(ear_raise=.7 * math.sin(t * 3.2), squash=.025 * math.sin(t * 3),
                    angle_offset=1.5 * math.sin(t * 2))
    pose['squash'] = max(-.25, min(.25, pose['squash']))
    return pose


class ExpressionMotion:
    """Seleciona a expressão a partir do cérebro e dos gestos, sem outra física."""
    def __init__(self, now):
        self.mode = 'observando';self.started = now;self.held_since = None;self.sleep_since = None
        self.last_landing = 0.;self.impact_since = -1e9;self.dizzy_until = 0.
        self.quirk = None;self.quirk_since = now;self.last_quirk = None
        self.blink_until = 0.
        self.run_phase = 0.
        self.run_tick = now
        self.pose = animation_pose(self.mode, 0)

    def update(self, game, now, press_since=None):
        body, state = game.body, game.state
        run_dt = max(0.,min(.05,now-self.run_tick))
        self.run_tick = now
        self.run_phase += abs(body.vx)*run_dt/max(24.,body.half_w)/3.4
        tones = state.tone.r
        held = press_since is not None or body.held
        if held and self.held_since is None:self.held_since = press_since if press_since is not None else now
        if not held:self.held_since = None
        if game.sleep.asleep and not held:
            if self.sleep_since is None:self.sleep_since = now
        else:self.sleep_since = None
        landing = game.landing
        if landing > .18 and self.last_landing < .08:self.impact_since = now
        self.last_landing = landing
        if state.dizzy(now) or abs(body.omega) > 450:self.dizzy_until = now + .8
        mode = state.emotion;strength = 1.;elapsed = None
        reaction = getattr(game, 'release_reaction', None) or {}
        returning = reaction.get('kind')=='pop_return'
        arriving = returning and now<reaction['arrives']
        landing_reaction = getattr(game, 'landing_reaction', None) or {}
        play_reaction = getattr(game, 'play_reaction', None) or {}
        pop_age = game.pop_effect_age(now)
        if pop_age is not None:
            mode='pop';elapsed=pop_age
        elif held:
            mode = 'held';elapsed = now - self.held_since
            # A irritação neural acelera o gesto; o relógio só interpola seus quadros.
            strength = .6 + .4 * tones['ANGRY'];elapsed *= .8 + .5 * tones['ANGRY']
        elif arriving:
            mode='pop_return';elapsed=now-reaction['started'];strength=_unit(reaction['intensity'])
        elif self.sleep_since is not None:mode = 'sleeping';elapsed = now - self.sleep_since
        elif state.feliz_fechado(now):mode = 'caress';strength = .5 + .5 * tones['CHEER']
        elif returning and now<reaction['until']:
            mode='pop_return';elapsed=now-reaction['started'];strength=_unit(reaction['intensity'])
        elif now < landing_reaction.get('until',0):
            mode=landing_reaction['kind'];elapsed=now-landing_reaction['started'];strength=_unit(landing_reaction['intensity'])
        elif now < self.dizzy_until:mode = 'tonto'
        elif not body.grounded and math.hypot(body.vx, body.vy) > 500:
            mode = 'airborne';strength = _unit(math.hypot(body.vx, body.vy) / 1500)
        elif now - self.impact_since < .5:mode = 'impact';elapsed = now - self.impact_since;strength = max(.35, landing)
        elif now < reaction.get('until',0):
            mode=reaction['kind'];elapsed=now-reaction['started'];strength=_unit(reaction['intensity'])
        elif now < play_reaction.get('until',0):
            mode=play_reaction['kind'];elapsed=now-play_reaction['started'];strength=_unit(play_reaction['intensity'])
        elif game.festa.fogos.isVisible():mode = 'comemorando';strength = tones['CHEER']
        elif mode == 'bravo':strength = .35 + .65 * tones['ANGRY']
        elif (body.grounded and 55.<=abs((body.angle+180.)%360.-180.)<=125.
              and mode in ('observando','contente','curioso','feliz','entediado','atento','neutro')):
            mode = 'deitada'
        elif (game.pingpong is None and body.grounded and body.upright() and abs(body.vx)>35.
              and mode in ('observando','contente','curioso','feliz','entediado','atento','neutro')):
            mode='correndo'
        running = mode in ('correndo','brinquedo_perseguindo') and body.grounded and abs(body.vx)>35.
        if running:
            strength=_unit(abs(body.vx)/360.)
            elapsed=self.run_phase
        elif mode=='brinquedo_perseguindo':
            # A perseguição pode continuar enquanto ela espera o brinquedo chegar.
            mode='atento'
        eligible = (game.visible() and body.grounded and not held and not game.hover and not game.panel
                    and mode in ('observando', 'contente', 'curioso', 'feliz', 'entediado'))
        if self.quirk is not None and (not eligible or now - self.quirk_since >= QUIRK_SECONDS[self.quirk]):
            self.quirk = None
        if eligible:
            choices = ['blink'] if self.quirk is not None else [key for key in (*QUIRK_SECONDS, 'blink') if key != self.last_quirk]
            choice = game.choose_expression(choices, now)
            if choice == 'blink':
                self.blink_until = now + .13
            elif choice in QUIRK_SECONDS:
                self.quirk = choice
                self.quirk_since = now;self.last_quirk = choice
        if self.quirk is not None:mode = self.quirk;elapsed = now - self.quirk_since
        if mode != self.mode:self.mode = mode;self.started = now
        self.pose = animation_pose(mode, elapsed if elapsed is not None else now - self.started, strength)
        if mode == 'pouso_de_lado' and landing_reaction.get('angle',0.) < 0.:
            self.pose['angle_offset'] *= -1.
        if mode == 'deitada':
            self.pose['gaze'] = tuple(.65*component for component in state.gaze)
        if running:
            direction=math.copysign(1.,body.vx)
            heading=0. if direction>0 else 180.
            self.pose['angle_offset']*=direction
            local_angle=math.radians(heading-body.angle-self.pose['angle_offset'])
            self.pose['gaze']=(math.cos(local_angle)*.86,math.sin(local_angle)*.86)
            self.pose['effect_angle']=heading-body.angle-self.pose['angle_offset']
        if mode == 'pop_return':
            inward = reaction['inward']
            glance = .47+.22*math.sin(elapsed*5.)*math.exp(-elapsed)
            self.pose['gaze'] = (inward*glance,.13*strength)
            if arriving:
                phase = _unit(elapsed/(reaction['arrives']-reaction['started']))
                peek = _ease(phase/.23)
                retreat = _ease((phase-.40)/.13)
                emerge = _ease((phase-.56)/.44)
                depth = -1.21+.99*peek-(.12+.12*strength)*retreat
                self.pose['corner_peek'] = (inward,depth,emerge)
                self.pose['angle_offset'] = inward*10.*peek*(1.-emerge)
        if mode in ('pingpong_rebatida','brinquedo_rebatida'):
            heading = play_reaction.get('heading',0.)
            follow = math.sin(math.pi*_unit(elapsed/.42))
            self.pose['angle_offset'] += 10.*math.sin(math.radians(heading))*follow
            local_angle = heading-body.angle-self.pose['angle_offset']
            self.pose['effect_angle'] = local_angle
            aim = math.radians(local_angle)
            self.pose['gaze'] = math.cos(aim),math.sin(aim)
        self.pose['blink'] = max(self.pose['blink'], float(now < self.blink_until))
        return self.pose
