# SPDX-License-Identifier: GPL-3.0-only
"""Desenho aprovado da Bolha nativa: somente olhos e orelhas.

O corpo e o rosto usam o mesmo centro, rotação e deformação. A expressão
permanece recortada ao interior da esfera em todos os quadros.
"""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

RADIUS = 49.0
FACE_RADIUS = 43.0
HALO_RADIUS = 59.0
EMOTIONS = ('observando', 'contente', 'feliz', 'curioso', 'bravo', 'triste', 'assustado', 'dramatico', 'dormindo', 'sonolento', 'timido', 'atento', 'entediado', 'travesso', 'tonto', 'comemorando')
GOLD = '#ffd364'

# Espiral vetorial pequena: a geometria não precisa ser recalculada por quadro.
_DIZZY_EYE = QPainterPath()
for _index in range(41):
    _phase = _index / 40
    _radius = .25 + 5.6 * _phase
    _point = QPointF(math.cos(_phase * math.tau * 1.55) * _radius,
                     math.sin(_phase * math.tau * 1.55) * _radius)
    if _index == 0: _DIZZY_EYE.moveTo(_point)
    else: _DIZZY_EYE.lineTo(_point)

# Quatro curvas do símbolo de raiva dos quadrinhos, com o centro aberto.
_ANGER_MARK = QPainterPath()
for _sx, _sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
    _ANGER_MARK.moveTo(1.7 * _sx, 8. * _sy)
    _ANGER_MARK.quadTo(2.2 * _sx, 2.2 * _sy, 8. * _sx, 1.7 * _sy)

# Recortes fixos preservam a silhueta do estouro de um quadro para o outro.
_POP_FLASH = QPainterPath(QPointF(0, -1))
for _x, _y in ((.17, -.19), (.83, -.45), (.36, -.05), (1, .24), (.22, .24),
               (.30, 1), (-.13, .39), (-.77, .73), (-.44, .07), (-1, -.10), (-.22, -.22)):
    _POP_FLASH.lineTo(_x, _y)
_POP_FLASH.closeSubpath()

_POP_DROP = QPainterPath(QPointF(-1.45, 0))
_POP_DROP.cubicTo(-.51, -.34, .05, -.69, .53, -.57)
_POP_DROP.cubicTo(1.26, -.41, 1.12, .44, .51, .57)
_POP_DROP.cubicTo(-.03, .68, -.59, .33, -1.45, 0)
_POP_DROP.closeSubpath()

_POP_FRAGMENTS = (
    (-169, 58, 4.5, '#f0b1ff'), (-142, 66, 2.3, '#fff1ba'),
    (-116, 61, 5.0, '#c0adff'), (-90, 68, 2.5, '#faefff'),
    (-62, 63, 4.4, '#f6adf0'), (-38, 57, 2.6, '#ffe6a0'),
    (-19, 66, 3.6, '#b8dbff'), (9, 64, 4.7, '#f0b1ff'),
    (35, 60, 2.5, '#fff1ba'), (59, 62, 4.2, '#d8b9ff'),
    (90, 57, 2.1, '#faefff'), (117, 62, 4.8, '#edb8ff'),
    (145, 65, 2.5, '#ffe6a0'), (163, 57, 3.2, '#b8dbff'),
)


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    return min(high, max(low, value)) if math.isfinite(value) else low


def _color(rgb, alpha=1.0):
    color = QColor(rgb)
    color.setAlphaF(alpha)
    return color


def _pen(color=GOLD, width=2.5, alpha=1.0):
    return QPen(_color(color, alpha), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _mix_color(first, second, amount, alpha=1.0):
    amount = _clamp(amount, 0.0, 1.0)
    a, b = QColor(first), QColor(second)
    color = QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * amount,
        a.greenF() + (b.greenF() - a.greenF()) * amount,
        a.blueF() + (b.blueF() - a.blueF()) * amount,
        _clamp(alpha, 0.0, 1.0),
    )
    return color


def _apply_pose_transform(painter, cx, cy, scale=1.0, angle=0.0, squash=0.0):
    scale = _clamp(scale, .05, 20)
    squash = _clamp(squash, -.25, .25)
    painter.translate(cx, cy)
    painter.rotate(_clamp(angle, -100000, 100000))
    painter.scale(scale * (1 + squash), scale * (1 - squash))


def _body(p, anger=0.0):
    anger = _clamp(anger, 0.0, 1.0)
    glow = QRadialGradient(QPointF(0, 0), HALO_RADIUS)
    for offset, calm_rgb, angry_rgb, alpha, boost in (
        (0, '#6f59c8', '#e01b38', 0, 0),
        (.77, '#6f59c8', '#e01b38', 0, 0),
        (.82, '#6f59c8', '#e01b38', .15, .14),
        (.88, '#9474ec', '#ff2a48', .32, .24),
        (.93, '#6b45ac', '#b8122a', .14, .12),
        (1, '#6b45ac', '#b8122a', 0, 0),
    ):
        glow.setColorAt(offset, _mix_color(calm_rgb, angry_rgb, anger, alpha + boost * anger))
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(0, 0), HALO_RADIUS, HALO_RADIUS)
    ring = QLinearGradient(-47, -47, 47, 47)
    ring.setColorAt(0, _mix_color('#b45da6', '#ff2e4c', anger))
    ring.setColorAt(.5, _mix_color('#8a79c1', '#de1d38', anger))
    ring.setColorAt(1, _mix_color('#6c96b5', '#a81428', anger))
    p.setBrush(ring)
    p.drawEllipse(QPointF(0, 0), RADIUS, RADIUS)
    core = QRadialGradient(QPointF(-15, -19), 91)
    core.setColorAt(0, _mix_color('#25252c', '#961e2e', anger))
    core.setColorAt(.55, _mix_color('#151519', '#52111c', anger))
    core.setColorAt(1, _mix_color('#0b0b0e', '#26080d', anger))
    p.setBrush(core)
    p.drawEllipse(QPointF(0, 0), 46.8, 46.8)
    if anger > 0:
        flush = QRadialGradient(QPointF(0, -8), 42)
        flush.setColorAt(0, _color('#e31e39', .42 * anger))
        flush.setColorAt(.65, _color('#9e1125', .22 * anger))
        flush.setColorAt(1, _color('#4a0812', 0))
        p.setBrush(flush)
        p.drawEllipse(QPointF(0, 0), 46.8, 46.8)


def _features(p, emotion, blink, gaze, ear_tilt=0.0, ear_raise=0.0, eye_open=1.0,
              blink_left=None, blink_right=None, anger=0.0, detail=1.0, ear_gaze=None):
    """Desenha somente olhos e orelhas. A metade inferior do rosto fica vazia."""
    clip = QPainterPath()
    clip.addEllipse(QPointF(0, 0), FACE_RADIUS, FACE_RADIUS)
    p.save()
    p.setClipPath(clip, Qt.IntersectClip)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(width=2.5*detail))
    # O rosto frontal é simétrico. Ao olhar de lado, o olho mais próximo se abre um pouco.
    profiles = {
        'observando': (5.2, 6.4, 0.0, 0.0, 0.0),
        'contente':   (5.2, 6.0, 0.0, 2.0, .4),
        'feliz':      (5.2, 6.4, 0.0, 6.0, 1.0),
        'curioso':    (5.7, 7.2, -.4, -5.0, 1.7),
        'bravo':      (5.8, 5.4, .2, -26.0, -2.2),
        'triste':     (5.4, 6.1, 1.3, 28.0, -3.2),
        'assustado':  (6.1, 9.8, -.3, -6.0, 2.8),
        'dramatico':  (5.7, 7.4, -.1, -11.0, 1.4),
        'dormindo':   (5.2, 6.4, 1.0, 21.0, -2.9),
        'sonolento':  (5.4, 3.2, 1.0, 12.0, -1.4),
        'timido':     (4.9, 4.8, 1.1, -11.0, -.5),
        'atento':     (5.4, 7.4, -.7, 0.0, 2.2),
        'entediado':  (5.7, 2.5, 1.1, 17.0, -2.1),
        'travesso':   (5.6, 4.7, -.1, -7.0, .9),
        'tonto':      (5.8, 6.2, .2, 19.0, -.9),
        'comemorando':(6.4, 7.2, -.3, 7.0, 2.0),
    }
    rx, ry, eye_y, tilt, raise_units = profiles[emotion]
    rx *= 1 + .2*(detail-1)
    ry *= 1 + .2*(detail-1)
    tilt = _clamp(tilt + ear_tilt, -35, 35)
    raise_units = _clamp(raise_units + ear_raise, -5, 5)
    gx,gy = gaze
    ex,ey = gaze if ear_gaze is None else ear_gaze
    if emotion == 'dormindo':
        gx = gy = ex = ey = 0.
    for side in (-1, 1):
        p.save()
        p.translate(side*17.5 + ex*4.4, -18.-raise_units+ey*2.8-side*ex*1.2)
        p.rotate(side*tilt+ex*14.)
        ear = QPainterPath(QPointF(-4.8, -2))
        ear.quadTo(-1, -12, 0, -12)
        ear.quadTo(1, -12, 4.8, -2)
        p.drawPath(ear)
        p.restore()
    opening = _clamp(eye_open, 0, 1.3)
    if emotion == 'dormindo': blink = 1.0
    closing = max(blink, 1 - min(1, opening))
    intentional = blink_left is not None or blink_right is not None
    for side in (-1, 1):
        individual = blink_left if side < 0 else blink_right
        closing_eye = closing if individual is None else max(closing,_clamp(individual,0,1))
        turn = side*gx
        x = side*18*(1.-.12*abs(gx))+gx*7.1
        y = eye_y+gy*3.6+.65*turn*gy
        if closing_eye > .94 or emotion == 'feliz' and not intentional:
            happy = emotion == 'feliz' and closing_eye <= .94
            eye = QPainterPath(QPointF(x - 5.3, y + (2 if happy else -1)))
            eye.quadTo(x, y + (-5 if happy else 3), x + 5.3, y + (2 if happy else -1))
            p.setBrush(Qt.NoBrush)
            p.setPen(_pen(width=2.5*detail))
            p.drawPath(eye)
        elif emotion == 'tonto':
            p.save()
            p.translate(x, y)
            p.scale(1, max(.12, (1 - closing_eye) * opening))
            p.setBrush(Qt.NoBrush)
            p.setPen(_pen(width=1.9*detail))
            p.drawPath(_DIZZY_EYE)
            p.restore()
        elif emotion == 'comemorando':
            eye = QPainterPath(QPointF(x, y - 7 * (1 - closing_eye)))
            for dx, dy in ((1.9, -2.2), (6.3, 0), (1.9, 2.2), (0, 7),
                           (-1.9, 2.2), (-6.3, 0), (-1.9, -2.2)):
                eye.lineTo(x + dx, y + dy * (1 - closing_eye))
            eye.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GOLD))
            p.drawPath(eye)
        else:
            width = rx*(1.+.16*turn)
            height = (ry * (1 - closing_eye) * max(1.0, opening) + .7 * closing_eye)*(1.+.07*turn)
            eye = QPainterPath()
            eye.addEllipse(QPointF(x, y), width, height)
            if emotion in ('bravo', 'triste', 'entediado', 'sonolento', 'travesso'):
                # As pálpebras fazem parte dos olhos, sem acrescentar boca ou sobrancelhas.
                slope = side * ((-.43 - .14 * anger) if emotion == 'bravo' else .26 if emotion == 'triste' else 0)
                lid_y = y - height * ((.14 - .12 * anger) if emotion == 'bravo' else .30 if emotion == 'triste' else .48)
                edge = width+1.
                lid = QPainterPath(QPointF(x-edge,lid_y-slope*edge))
                lid.lineTo(x+edge,lid_y+slope*edge)
                lid.lineTo(x+edge,y+height+1)
                lid.lineTo(x-edge,y+height+1)
                lid.closeSubpath()
                eye = eye.intersected(lid)
            p.setPen(Qt.NoPen)
            p.setBrush(_color(GOLD, .12))
            p.drawEllipse(QPointF(x, y), width+1., height+1.)
            p.setBrush(QColor(GOLD))
            p.drawPath(eye)
            if height > 3:
                p.save()
                p.setClipPath(eye, Qt.IntersectClip)
                p.setBrush(QColor('#fff4cf'))
                p.drawEllipse(QPointF(x-1.2+gx*1.45,y-2.+gy*1.1),1.05,1.05)
                p.restore()
    p.restore()


def draw_character(painter, cx, cy, scale=1.0, angle=0.0, emotion='observando',
                   blink=0.0, gaze=(0.0, 0.0), squash=0.0,
                   ear_tilt=0.0, ear_raise=0.0, eye_open=1.0, body_opacity=1.0,
                   blink_left=None, blink_right=None, anger=None, ear_gaze=None):
    """Pinta Bolha somente com olhos e orelhas: nunca desenha boca.

    ``blink``: 0 aberto, 1 fechado; ``eye_open``: abertura 0..1.3;
    ``ear_tilt``: graus espelhados; ``ear_raise``: elevação canônica.
    Escala, rotação e squash afetam corpo e rosto juntos.
    """
    emotion = {'calma': 'observando', 'tímido': 'timido', 'dramático': 'dramatico'}.get(emotion, emotion)
    emotion = emotion if emotion in EMOTIONS else 'observando'
    anger = (.75 if emotion == 'bravo' else 0.0) if anger is None else _clamp(anger, 0.0, 1.0)
    gaze = (_clamp(gaze[0], -1, 1), _clamp(gaze[1], -1, 1))
    if ear_gaze is not None:
        ear_gaze = (_clamp(ear_gaze[0],-1,1),_clamp(ear_gaze[1],-1,1))
    painter.save()
    _apply_pose_transform(painter, cx, cy, scale, angle, squash)
    painter.save()
    painter.setOpacity(painter.opacity() * _clamp(body_opacity, .2, 1))
    _body(painter, anger)
    painter.restore()
    _features(painter, emotion, _clamp(blink, 0, 1), gaze,
              _clamp(ear_tilt, -35, 35), _clamp(ear_raise, -5, 5), _clamp(eye_open, 0, 1.3),
              blink_left,blink_right,anger,detail=max(1.,min(1.3,.7/max(.05,scale))),ear_gaze=ear_gaze)
    painter.restore()


def draw_sleep_marks(painter, cx, cy, scale=1.0, phase=0.0, strength=1.0, angle=0.0, squash=0.0):
    """Três zzz vetoriais sobem em 2,4s; acompanham a pose do corpo, sem entrada."""
    strength = _clamp(strength, 0, 1)
    if strength == 0: return
    phase = _clamp(phase, -1000000000, 1000000000)
    painter.save()
    _apply_pose_transform(painter, cx, cy, scale, angle, squash)
    painter.setBrush(Qt.NoBrush)
    for index in range(3):
        progress = (phase / 2.4 + index / 3) % 1
        opacity = min(1, progress / .2, (1-progress) / .25) * strength
        size = 4.2 + progress * 2.3
        x, y = 31 + progress * 8, -25 - progress * 20
        mark = QPainterPath(QPointF(x, y-size))
        mark.lineTo(x+size*.8, y-size)
        mark.lineTo(x, y)
        mark.lineTo(x+size*.8, y)
        painter.setPen(_pen(width=1.25, alpha=opacity))
        painter.drawPath(mark)
    painter.restore()


def _draw_anger_marks(painter, phase, strength):
    """Um símbolo grande pulsa, seguido de outro menor e faíscas breves."""
    painter.setBrush(Qt.NoBrush)
    for x, y, size, tilt, delay in ((-37., -36., 1., -13., 0.), (47., -18., .68, 18., .23)):
        beat = (.5 + .5 * math.cos((phase-delay)*math.tau*1.8)) ** 2
        pop = .76 + .20 * strength * beat
        painter.save()
        painter.translate(x, y - 1.5 * beat)
        painter.rotate(tilt + 4. * math.sin((phase-delay)*8))
        painter.scale(size * pop, size * pop)
        painter.setPen(_pen('#3b1026', 5.1, .90 * strength))
        painter.drawPath(_ANGER_MARK)
        painter.setPen(_pen('#ff455f', 3.2, strength))
        painter.drawPath(_ANGER_MARK)
        painter.setPen(_pen('#ffbec2', 1.2, (.68 + .32 * beat) * strength))
        painter.drawPath(_ANGER_MARK)
        painter.restore()

    for index, direction in enumerate((-2.77, -1.92, -.55)):
        progress = (phase * 1.55 + .15 * index) % 1.
        if progress >= .60:
            continue
        distance = 50. + 12. * progress
        x, y = math.cos(direction), math.sin(direction)
        fade = math.sin(math.pi * progress / .60)
        painter.setPen(_pen('#ff5f6d', 1.8, strength * strength * .78 * fade))
        painter.drawLine(QPointF(x*distance, y*distance), QPointF(x*(distance+3.), y*(distance+3.)))


def _draw_pop_marks(painter, phase, strength):
    """O centro pisca, a casca racha e as gotas se afastam antes de apagar."""
    progress = _clamp(phase/.62, 0., 1.)
    spread = 1.-(1.-progress)**3.2
    flash = (1.-_clamp(phase/.14, 0., 1.))**1.6 * strength
    if flash > 0:
        glow = QRadialGradient(QPointF(0, 0), 39.)
        glow.setColorAt(0., _color('#fff2ba', .56*flash))
        glow.setColorAt(.45, _color('#f4b0ff', .48*flash))
        glow.setColorAt(1., _color('#e399ff', 0.))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), 39., 39.)
        painter.save()
        flash_size = 21.+13.*spread
        painter.scale(flash_size, flash_size)
        painter.setBrush(_color('#fff5d7', flash))
        painter.drawPath(_POP_FLASH)
        painter.restore()

    shell_alpha = (1.-_clamp(phase/.46, 0., 1.))**1.35 * strength
    radius = 41.+23.*spread
    shell = QRectF(-radius, -radius, radius*2., radius*2.)
    painter.setBrush(Qt.NoBrush)
    for start, arc, color in ((12, 47, '#eed0ff'), (78, 46, '#fff1b7'),
                              (148, 54, '#b9d4ff'), (225, 54, '#dfa6ff'), (309, 37, '#ffd4fb')):
        gap = round(11.*spread)
        painter.setPen(_pen(color, 7.-3.*spread, .24*shell_alpha))
        painter.drawArc(shell, (start+gap)*16, (arc-gap*2)*16)
        painter.setPen(_pen(color, 3.4-1.7*spread, shell_alpha))
        painter.drawArc(shell, (start+gap)*16, (arc-gap*2)*16)

    drop_alpha = (1.-progress**1.65)**1.25 * strength
    fall = 6.*progress*progress
    for index, (degrees, reach, size, color) in enumerate(_POP_FRAGMENTS):
        direction = math.radians(degrees)
        distance = 35.+(reach-35.)*spread
        size *= 1.-.55*progress
        painter.save()
        painter.translate(math.cos(direction)*distance, math.sin(direction)*distance+fall)
        painter.rotate(degrees + (index%3-1)*25.*progress)
        painter.scale(size, size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_color(color, .25*drop_alpha))
        painter.drawEllipse(QPointF(0., 0.), 1.6, 1.)
        painter.setBrush(_color(color, drop_alpha))
        painter.drawPath(_POP_DROP)
        painter.setBrush(_color('#fff9e5', .86*drop_alpha))
        painter.drawEllipse(QPointF(.47, -.22), .28, .14)
        painter.restore()


def draw_reaction_marks(painter, cx, cy, scale=1.0, phase=0.0, kind='carinho', strength=1.0,
                        angle=0.0, squash=0.0, effect_angle=0.0):
    """Marcas decorativas presas à pose do corpo, sem hitbox."""
    strength = _clamp(strength, 0, 1)
    if strength == 0 or kind not in ('carinho', 'tonto', 'bravo', 'perseguindo', 'comemorando', 'rebatida', 'pop'): return
    phase = _clamp(phase, -1000000000, 1000000000)
    painter.save()
    _apply_pose_transform(painter, cx, cy, scale, angle, squash)
    if kind == 'pop':
        _draw_pop_marks(painter, phase, strength)
    elif kind == 'carinho':
        for index in range(3):
            progress = (phase / 1.8 + index / 3) % 1
            opacity = min(1, progress / .2, (1-progress) / .3) * strength
            x = (-34 if index % 2 == 0 else 35) + math.sin(progress*math.pi)*2
            y = -24 - progress*20
            size = 3.7 + progress*1.8
            heart = QPainterPath(QPointF(x, y+size))
            heart.cubicTo(x-size*2, y-size*.2, x-size, y-size*1.7, x, y-size*.5)
            heart.cubicTo(x+size, y-size*1.7, x+size*2, y-size*.2, x, y+size)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_color(GOLD, opacity))
            painter.drawPath(heart)
    elif kind == 'tonto':
        painter.setPen(Qt.NoPen)
        painter.setBrush(_color(GOLD, strength*.85))
        for index in range(3):
            orbit = phase*2.6 + index*math.tau/3
            x, y = math.cos(orbit)*40, -41+math.sin(orbit)*6
            size = 3.1 + .5*math.sin(orbit*2)
            star = QPainterPath(QPointF(x, y-size))
            for dx, dy in ((.7,-.7),(size,0),(.7,.7),(0,size),(-.7,.7),(-size,0),(-.7,-.7)):
                star.lineTo(x+dx,y+dy)
            star.closeSubpath()
            painter.drawPath(star)
    elif kind in ('perseguindo', 'comemorando'):
        if kind=='perseguindo':
            painter.rotate(_clamp(effect_angle,-360.,360.))
        painter.setPen(Qt.NoPen)
        for index in range(3):
            phase_i = phase * (8 if kind == 'perseguindo' else 2.5) + index * math.tau / 3
            if kind == 'perseguindo':
                # Os rastros ficam sempre atrás da direção real da corrida.
                x = -48 - 2.*math.sin(phase_i)
                y = (index-1)*11.
                painter.setPen(_pen(color='#a8efff', width=1.7 + index * .35,
                                    alpha=strength * (.45 + .18 * index)))
                painter.drawLine(QPointF(x-5.,y),QPointF(x+2.,y))
                painter.setPen(Qt.NoPen)
            else:
                x = 34 * math.cos(phase_i)
                y = -30 + 10 * math.sin(phase_i)
                size = 3.2 + .7 * math.sin(phase_i * 2)
                star = QPainterPath(QPointF(x, y - size))
                for dx, dy in ((1, -1), (size, 0), (1, 1), (0, size),
                               (-1, 1), (-size, 0), (-1, -1)):
                    star.lineTo(x + dx, y + dy)
                star.closeSubpath()
                painter.setBrush(_color(GOLD, strength * .9))
                painter.drawPath(star)
    elif kind == 'bravo':
        _draw_anger_marks(painter, phase, strength)
    elif kind == 'rebatida':
        direction = math.radians(_clamp(effect_angle,-180.,180.))
        deformation = _clamp(squash,-.25,.25)
        # Corrige a direção antes de deformar, para o arco manter o rumo do brinquedo.
        painter.rotate(math.degrees(math.atan2(math.sin(direction)/(1.-deformation),
                                               math.cos(direction)/(1.+deformation))))
        progress = _clamp(phase/.24,0.,1.)
        x, height = 47.+6.*progress, 7.+4.*progress
        arc = QPainterPath(QPointF(x-2.,-height))
        arc.quadTo(x+7.,0.,x-2.,height)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(_pen('#6ce7f3',4.4,strength*.45))
        painter.drawPath(arc)
        painter.setPen(_pen('#d5ffff',1.8,strength))
        painter.drawPath(arc)
        painter.setPen(_pen('#ffd364',1.8,strength))
        for side in (-1,1):
            painter.drawLine(QPointF(x+2.,side*(height+1.)),QPointF(x+5.,side*(height+4.)))
    painter.restore()




WINK_DURATION = 1.12

def wink_state(progress):
    """Dois gestos rápidos com120ms totalmente fechados e final aberto."""
    progress=_clamp(progress,0,1);t=progress*WINK_DURATION
    def pulse(start):
        local=t-start
        if local<0 or local>=.34:return 0.
        if local<.10:return .5-.5*math.cos(math.pi*local/.10)
        if local<.22:return 1.
        return .5+.5*math.cos(math.pi*(local-.22)/.12)
    left,right=pulse(.03),pulse(.43)
    envelope=math.sin(math.pi*progress)**2
    return dict(blink_left=left,blink_right=right,ear_tilt=10*math.sin(progress*math.tau)*envelope,
                ear_raise=1.8*envelope,tilt=5*math.sin(progress*math.tau)*envelope)
