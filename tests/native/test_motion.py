# SPDX-License-Identifier: GPL-3.0-only
"""Expressões reais respeitam cérebro, relógio e a única autoridade física."""
from pathlib import Path
import math
import time
import pytest
from game import Game
from bolha.motion import animation_pose, ExpressionMotion, QUIRK_SECONDS

CONTENT = Path(__file__).resolve().parents[2] / 'assets/bolha/content'


def game_at_rest(tmp_path):
    game = Game(tmp_path, CONTENT)
    game.body.grounded = True
    game.body.vx = game.body.vy = game.body.omega = 0
    return game


def test_segurar_irrita_aos_poucos_e_atividade_neural_modula_gesto(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    before = vars(game.body).copy()
    early = motion.update(game, 100.1, 100)
    late = motion.update(game, 104.2, 100)
    assert early['emotion'] == 'curioso' and late['emotion'] == 'bravo'
    assert late['eye_open'] < early['eye_open'] and late['ear_raise'] < early['ear_raise']
    assert late['effect_strength'] > early['effect_strength']
    calm = ExpressionMotion(100).update(game, 102, 100)
    game.state.tone.r['ANGRY'] = 1
    irritated = ExpressionMotion(100).update(game, 102, 100)
    assert irritated['eye_open'] < calm['eye_open']
    assert irritated['effect_strength'] > calm['effect_strength']
    assert vars(game.body) == before


def test_adormecer_fecha_olhos_gradualmente_respira_e_so_entao_soltar_zzz(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    game.sleep.asleep = True
    first = motion.update(game, 100)
    middle = motion.update(game, 100.9)
    asleep = motion.update(game, 102.1)
    breathe = motion.update(game, 103.1)
    assert first['eye_open'] > middle['eye_open'] > asleep['eye_open']
    assert first['zzz_strength'] == middle['zzz_strength'] == 0
    assert asleep['zzz_strength'] > 0 and asleep['emotion'] == 'dormindo'
    assert asleep['squash'] != breathe['squash']
    held = motion.update(game, 103.2, 103.2)
    assert held['zzz_strength'] == 0 and motion.mode == 'held'


def test_manias_and_blink_are_selected_and_traced_by_policy(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    game.intelligence.enabled = False
    game.rates.update(CHEER=30., WATCH=0., DROWSE=0., ANGRY=0.)
    for now in (100., 110., 200.):
        motion.update(game, now)
        choice = game.decision_snapshot()['current']
        assert choice and choice['source'] == 'expression_policy'
        assert choice['action'] in (*QUIRK_SECONDS, 'blink')
    motion.update(game, 500, 500)
    assert motion.quirk is None and motion.mode == 'held'
    game.panel = True;motion.update(game, 501)
    assert motion.quirk is None


def test_reacao_de_soltura_vem_do_cerebro_e_carinho_tem_prioridade(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    game.release_reaction = dict(kind='birra', started=100, until=104, intensity=.9)
    pose = motion.update(game, 100.4)
    assert motion.mode == 'birra' and pose['emotion'] == 'bravo'
    game.state.mark_caress(100.5)
    pose = motion.update(game, 100.6)
    assert motion.mode == 'caress' and pose['effect'] == 'carinho'
    game.state.feliz_ate = 0
    pose = motion.update(game, 105)
    assert motion.mode == game.state.emotion


def test_pop_dissolve_retorno_timido_e_pousos_sao_visuais(tmp_path):
    game=game_at_rest(tmp_path);motion=ExpressionMotion(100.)
    body_before=vars(game.body).copy()
    game.pop_started=100.
    squeeze=motion.update(game,100.075)
    swell=motion.update(game,100.125)
    dissolve=motion.update(game,100.2)
    gone=motion.update(game,100.7)
    assert squeeze['squash']>.2 and swell['visual_scale']>1.1
    assert squeeze['effect_strength']==swell['effect_strength']==0.
    assert dissolve['effect']=='pop' and 0.<dissolve['body_opacity']<1.
    assert gone['body_opacity'] < .002
    game.pop_started=None
    game.release_reaction=dict(kind='pop_return',started=100.62,arrives=102.1,
                               until=105.,intensity=.7,inward=1.)
    peek=motion.update(game,100.8)
    assert peek['emotion']=='timido' and peek['corner_peek'][0]==1.
    assert peek['body_opacity']==1. and peek['visual_scale']==1.
    for kind in ('pouso_em_pe','pouso_de_lado','pouso_invertido'):
        game.release_reaction={}
        game.landing_reaction=dict(kind=kind,started=101.,until=101.8,intensity=.8,angle=-1.)
        pose=motion.update(game,101.12)
        assert pose['emotion'] in ('assustado','atento','tonto')
        assert pose['squash'] != 0
    assert vars(game.body)==body_before


def test_queda_de_lado_espelha_a_inclinacao_e_transita_para_repouso(tmp_path):
    game=game_at_rest(tmp_path)
    game.state.emotion='observando'
    for side in (-1.,1.):
        game.body.angle=side*90.
        game.landing_reaction=dict(kind='pouso_de_lado',started=100.,until=100.9,
                                   intensity=.8,angle=game.body.angle)
        motion=ExpressionMotion(100.)
        contact=motion.update(game,100.)
        assert contact['angle_offset']*side<0 and contact['squash']>.2
        settle=motion.update(game,100.89)
        resting=motion.update(game,100.91)
        assert motion.mode=='deitada'
        assert resting['squash']==pytest.approx(settle['squash'],abs=.02)
        assert resting['eye_open']<contact['eye_open']
        assert motion.update(game,102.1)['squash']<resting['squash']
    assert game.body.angle==90.


@pytest.mark.parametrize('inward',[1.,-1.])
def test_espiada_recorta_a_borda_e_libera_o_mouse_ao_sair(qt_application,tmp_path,monkeypatch,inward):
    import numpy as np
    from PySide6.QtGui import QImage
    from bolha.pet import PetWindow

    clock=[100.]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=game_at_rest(tmp_path)
    game.desktop({'areas':[
        dict(x=x,y=0,width=900,height=700,id=i,scaleFactor=1.)
        for i,x in enumerate((-1800,-900,0))
    ]})
    game.configure({'avatarSize':200})
    game.body.x=-450.
    game.cursor=(-450.+250.*inward,350.)
    game._return_from_pop(clock[0])
    arrival=game.release_reaction['arrives']
    edge=-900 if inward>0 else 0
    pet=PetWindow(game)
    try:
        clock[0]+=.30*(arrival-clock[0])
        pet.sync()
        image=pet.visual.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
        pixels=np.frombuffer(image.bits(),dtype=np.uint8).reshape(image.height(),image.width(),4)
        cutoff=round((edge-pet.visual.x())*image.devicePixelRatio())
        hidden,visible=(pixels[:,:cutoff],pixels[:,cutoff:]) if inward>0 else (pixels[:,cutoff:],pixels[:,:cutoff])
        assert hidden.size and not hidden[:,:,3].any()
        assert visible[:,:,3].max()==255 and not pet.isVisible()
        assert game.start_pingpong(clock[0])=='A Bolha ainda está voltando. Tente daqui a pouco.'

        clock[0]=arrival
        pet.sync()
        assert pet.isVisible() and 'corner_peek' not in pet.motion.pose
        assert pet.x()+pet.width()/2==game.body.x
    finally:
        pet.close()


def test_cena_comedia_vem_da_brincadeira_real_e_nao_escolhe_politica_na_view(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    game.play_reaction = dict(kind='bote_erro', started=100, until=102, intensity=.9)
    assert motion.update(game, 100.6)['emotion'] == 'tonto'
    assert motion.mode == 'bote_erro'
    game.play_reaction = dict(kind='fingir_trabalho', started=101, until=103, intensity=.9)
    assert motion.update(game, 101.9)['emotion'] == 'atento'
    assert motion.mode == 'fingir_trabalho'
    assert motion.update(game, 104)['emotion'] == game.state.emotion


def test_rebatida_real_do_pingpong_comprime_estica_e_fecha_o_efeito(tmp_path,monkeypatch):
    monkeypatch.setattr(time,'monotonic',lambda:100.)
    game=game_at_rest(tmp_path)
    game.interact({'type':'pingpong'})
    match=game.pingpong
    game.interact(dict(type='cursor',x=920.,y=450.))
    game.last_think=100.
    match.serve_delay=0.
    match.ball_x=match.pet_x+match.pet_radius+match.toy_radius+2.
    match.ball_y=match.pet_y+8.
    match.vx=-430.
    game.tick(.016,100.)
    assert match.rally==1 and match.vx>0.
    assert game.play_reaction['kind']=='pingpong_rebatida'
    motion=ExpressionMotion(100.)
    impact=motion.update(game,100.)
    stretch=motion.update(game,100.13)
    settled=motion.update(game,100.38)
    assert impact['squash']<-.1 and impact['effect']=='rebatida'
    assert stretch['squash']>.1 and stretch['ear_raise']>0.
    local = math.degrees(math.atan2(stretch['gaze'][1],stretch['gaze'][0]))
    assert local+game.body.angle+stretch['angle_offset']==pytest.approx(game.play_reaction['heading'])
    assert settled['squash']==0. and settled['effect_strength']==0.
    assert motion.update(game,100.5)['effect'] is None


def test_reacoes_a_perseguir_e_keep_away_sao_visuais_sem_alterar_a_fisica(tmp_path):
    game = game_at_rest(tmp_path);motion = ExpressionMotion(100)
    body_before = vars(game.body).copy()
    game.play_reaction = dict(kind='brinquedo_frustrado', started=100, until=102,
                              intensity=.9)
    frustrated = motion.update(game, 100.55)
    assert frustrated['emotion'] == 'bravo'
    assert frustrated['anger'] > .6 and frustrated['effect'] == 'bravo'
    assert frustrated['ear_raise'] < -3 and frustrated['eye_open'] < .5
    cooling = animation_pose('brinquedo_frustrado', 2.7, .9)
    assert cooling['anger'] < .15 and cooling['effect_strength'] < .15
    game.play_reaction = dict(kind='brinquedo_perseguindo', started=101, until=103,
                              intensity=.8)
    waiting = motion.update(game,101.3)
    assert waiting['emotion']=='atento' and waiting['effect'] is None
    game.body.vx=300.
    chase = motion.update(game, 101.4)
    assert chase['emotion'] == 'atento' and chase['effect'] == 'perseguindo'
    assert chase['gaze'][0]>.7 and chase['effect_strength']>.5
    game.body.vx=0.
    game.play_reaction = dict(kind='comemorando', started=102, until=104, intensity=.9)
    cheer = motion.update(game, 102.3)
    assert cheer['emotion'] == 'comemorando' and cheer['effect'] == 'comemorando'
    assert vars(game.body) == body_before


def test_corrida_espelha_olhar_inclinacao_e_rastros_sem_mover_o_corpo(tmp_path):
    game=game_at_rest(tmp_path)
    game.state.emotion='observando'
    poses=[]
    for velocity in (-280.,280.):
        game.body.vx=velocity
        before=vars(game.body).copy()
        pose=ExpressionMotion(100.).update(game,100.04)
        assert pose['gaze'][0]*velocity>0.
        assert pose['angle_offset']*velocity>0.
        assert pose['effect']=='perseguindo'
        assert vars(game.body)==before
        poses.append(pose)
    assert poses[0]['angle_offset']==pytest.approx(-poses[1]['angle_offset'])
    assert poses[0]['squash']==poses[1]['squash']
    game.body.vx=0.
    assert ExpressionMotion(100.).update(game,100.04)['effect'] is None


def test_rebatida_do_brinquedo_livre_usa_a_direcao_do_rebote(tmp_path):
    game=game_at_rest(tmp_path)
    game.body.angle=-20.
    game.play_reaction=dict(kind='brinquedo_rebatida',started=100.,until=100.42,
                            intensity=.8,heading=142.)
    pose=ExpressionMotion(100.).update(game,100.13)
    aim=math.degrees(math.atan2(pose['gaze'][1],pose['gaze'][0]))
    assert aim+game.body.angle+pose['angle_offset']==pytest.approx(142.)
    assert pose['effect']=='rebatida'


def test_raiva_visual_responde_a_intensidade_tambem_na_previa():
    mild=animation_pose('bravo',.6,.1)
    furious=animation_pose('bravo',.6,.95)
    assert furious['anger']>mild['anger']>.4
    assert furious['effect']=='bravo' and furious['eye_open']<mild['eye_open']


@pytest.mark.parametrize('reason',['ungrab','hidden'])
def test_cancelar_segurada_imovel_libera_corpo_e_hover(qt_application,tmp_path,reason):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QEnterEvent, QMouseEvent
    from bolha.pet import PetWindow
    game = game_at_rest(tmp_path)
    game.configure({'senseCursor':False,'toyAppearance':'ball'})
    preferences = dict(game.prefs);pet = PetWindow(game)
    local = QPointF(pet.width()/2,pet.height()/2)
    position = QPointF(game.body.x,game.body.y)
    try:
        qt_application.sendEvent(pet,QEnterEvent(local,local,position))
        qt_application.sendEvent(pet,QMouseEvent(QEvent.MouseButtonPress,local,position,
                                                Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
        assert game.body.held and game.senses.dragging and not pet.dragging and game.hover
        qt_application.sendEvent(pet,QEvent(QEvent.Leave))
        assert game.hover
        if reason=='ungrab':
            qt_application.sendEvent(pet,QEvent(QEvent.UngrabMouse))
        else:
            game.interact({'type':'hide','value':True});pet.sync()
            game.interact({'type':'hide','value':False});pet.sync()
            assert pet.isVisible()
        assert not game.body.held and game.held_since is None and pet.press is None
        assert not game.hover and not game.state.pressing and not game.senses.dragging
        assert game.prefs == preferences
    finally:pet.close()


def test_soltar_apos_arrasto_herda_movimento_recente_sem_poke(qt_application,tmp_path,monkeypatch):
    import time
    from PySide6.QtCore import QPointF, Qt
    from types import SimpleNamespace
    from bolha.pet import PetWindow
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game = game_at_rest(tmp_path);pet = PetWindow(game);events=[]
    original=game.interact
    def interact(event):events.append(event.copy());return original(event)
    game.interact=interact
    def mouse(x,y):return SimpleNamespace(button=lambda:Qt.LeftButton,globalPosition=lambda:QPointF(x,y))
    try:
        game.body.vx,game.body.vy,game.body.omega=400,-500,300
        pet.mousePressEvent(mouse(game.body.x+8,game.body.y+9))
        clock[0]+=.08
        pet.mouseMoveEvent(mouse(game.body.x+128,game.body.y-71))
        position=(game.body.x,game.body.y)
        pet.mouseReleaseEvent(mouse(game.body.x+8,game.body.y+9))
        assert not game.body.held and not game.body.grounded
        assert (game.body.x,game.body.y)==position
        assert game.body.vx==pytest.approx(1500)
        assert game.body.vy==pytest.approx(-1000)
        assert game.body.omega==pytest.approx(525)
        assert [event['type'] for event in events]==['hold-start','drag-start','drag-end','hold-end']
        assert 'vx' in events[-2] and 'vy' in events[-2]
    finally:pet.close()


@pytest.mark.parametrize('mode', ['held', 'sleeping', 'caress', 'airborne', 'impact',
                                 'tonto', 'comemorando', 'birra', 'sacudir', 'preparar_bote',
                                 'brinquedo_frustrado', 'brinquedo_perseguindo',
                                 'bote_erro', 'brinquedo_susto', 'fingir_trabalho', *QUIRK_SECONDS])
def test_deformacoes_limitadas_e_sem_movimento_do_centro(mode):
    for frame in range(181):
        pose = animation_pose(mode, frame / 30)
        assert -.25 <= pose['squash'] <= .25
        assert 0 <= pose['eye_open'] <= 1.3
        assert 'x' not in pose and 'y' not in pose


def test_janela_visual_com_geleia_preserva_centro_e_mascara_fisica(qt_application,tmp_path):
    from bolha.pet import PetWindow
    game = game_at_rest(tmp_path);game.configure(dict(avatarSize=200))
    pet = PetWindow(game)
    try:
        assert pet.width() == pet.height() == 256
        assert pet.visual.width() == pet.visual.height() == 320
        assert pet.x() + pet.width() / 2 == pet.visual.x() + pet.visual.width() / 2 == game.body.x
        assert pet.y() + pet.height() / 2 == pet.visual.y() + pet.visual.height() / 2 == game.body.y
        mask = pet.mask()
        for t in (.5, 1, 1.4):
            pet.motion.pose = animation_pose('stretch', t)
            image = pet.visual.grab().toImage()
            assert all(image.pixelColor(x, 0).alpha() == image.pixelColor(x, 319).alpha() == 0 for x in range(320))
            assert all(image.pixelColor(0, y).alpha() == image.pixelColor(319, y).alpha() == 0 for y in range(320))
            assert pet.mask() == mask
        game.body.angle=90.
        game.body.surface=game.bounds()[3]
        game.body.y=game.body.surface-game.body.half_w
        game.state.emotion='observando'
        pet.sync()
        assert pet.motion.mode=='deitada'
        resting=pet.mask().boundingRect()
        assert resting.width()>mask.boundingRect().width()
        assert resting.height()<mask.boundingRect().height()
        assert resting.bottom()==mask.boundingRect().bottom()
    finally:pet.close()
