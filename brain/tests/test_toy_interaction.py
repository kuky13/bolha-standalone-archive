# SPDX-License-Identifier: GPL-3.0-only
"""Interações chegam ao cérebro real e preservam a física e o aprendizado."""
from pathlib import Path
import time
import pytest
from game import Game

CONTENT=Path(__file__).resolve().parents[2]/'assets/bolha/content'


def test_segurando_sem_arrastar_alimenta_drag_e_press_do_cerebro(tmp_path,monkeypatch):
    clock=[100.]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.interact({'type':'hold-start'})
    before=game.body.x,game.body.y
    game.body.step(.05,game.bounds(),[])
    assert (game.body.x,game.body.y)==before and game.body.held
    for _ in range(15):
        clock[0]+=.1;game.think(.1,clock[0])
    assert game.inputs['DRAG']>.75
    assert 'PRESS' in game.conditioning.active
    assert game.brain.time_ms>0 and game.brain.N==470
    game.interact({'type':'hold-end'})
    assert not game.body.held and not game.senses.dragging and not game.state.pressing
    assert game.release_reaction['until']>clock[0]
    clock[0]+=2;game.conditioning.tick(clock[0])
    assert game.conditioning.V['PRESS']>0


@pytest.mark.parametrize('angry,settle,learned,expected',[
    (.9,.1,.1,'birra'),(.2,.7,.1,'sacudir'),(.2,.1,.8,'timido'),(.3,.1,.1,'bravo')])
def test_reacao_ao_soltar_depende_dos_motores_e_condicionamento(tmp_path,monkeypatch,angry,settle,learned,expected):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.interact({'type':'hold-start'})
    game.state.tone.r.update(ANGRY=angry,SETTLE=settle)
    game.conditioning.V['PRESS']=learned
    clock[0]+=5
    game.interact({'type':'hold-end'})
    assert game.release_reaction['kind']==expected
    reaction=game.release_reaction.copy()
    game.interact({'type':'hold-end'})
    assert game.release_reaction==reaction  # Release e cancel não duplicam uma reação.
    game.interact({'type':'caress'})
    assert game.release_reaction['until']<reaction['until']
    assert game.release_reaction['intensity']<reaction['intensity']


@pytest.mark.parametrize('sensor',[True,False])
@pytest.mark.parametrize('angry,elapsed,kind',[(.3,2.,'bravo'),(.9,5.,'birra')])
def test_soltar_bravo_encara_ponteiro_apesar_de_glance_e_respeita_sensor(tmp_path,monkeypatch,sensor,angry,elapsed,kind):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT);game.configure({'senseCursor':sensor})
    game.body.x,game.body.y=500,300;game.cursor=(700,300)
    game.behavior.glance=(300,300);game.behavior.next_glance=1e9
    game.interact({'type':'hold-start'})
    game.state.tone.r['ANGRY']=angry
    clock[0]+=elapsed;game.interact({'type':'hold-end'})
    assert game.release_reaction['kind']==kind
    game.last_think=clock[0]
    game.behavior.tick(.016,clock[0],game.cursor,game.bounds(),game.prof)
    assert game.state.gaze==(-1.,0.)
    clock[0]+=.016;game.tick(.016,clock[0])
    if sensor:
        assert game.state.gaze[0] > .999 and -.01 < game.state.gaze[1] < 0.
    else:
        assert game.state.gaze == (-1.,0.)
    assert game.body.y>300 and game.body.vy>0


@pytest.mark.parametrize('event',[{'type':'hide','value':True},{'type':'panic'}])
def test_cancelamento_escondido_libera_pega_sem_reacao(tmp_path,event):
    game=Game(tmp_path,CONTENT)
    game.interact({'type':'hold-start'})
    game.interact(event)
    assert not game.body.held and game.held_since is None
    assert not game.state.pressing and not game.senses.dragging
    assert not game.release_reaction


@pytest.mark.parametrize('event',[{'type':'hide','value':True},{'type':'panic'}])
def test_esconder_tambem_cancela_pega_do_brinquedo(tmp_path,event):
    game=Game(tmp_path,CONTENT)
    game.interact(dict(type='drag-start',id=game.ball.id,x=500,y=300))
    game.interact(event)
    assert not game.ball.body.held and not game.ball.dragging
    assert game.ball.body.vx==game.ball.body.vy==game.ball.body.omega==0
    assert not game.ball.body.grounded


def test_aparencia_do_brinquedo_nao_substitui_corpo_ou_aprendizado(tmp_path):
    game=Game(tmp_path,CONTENT);body=game.ball.body
    game.brain.learned[0,0]=.04
    game.configure({'toyAppearance':'ball'})
    assert game.ball.appearance=='ball'
    game.configure({'toyAppearance':'peanut'})
    assert game.ball.appearance=='peanut' and game.ball.body is body
    assert game.brain.learned[0,0]==pytest.approx(.04)


def test_pedido_para_brincar_move_o_brinquedo_sem_impulso_neural_espontaneo(tmp_path,monkeypatch):
    clock = 100.
    monkeypatch.setattr(time, 'monotonic', lambda: clock)
    game = Game(tmp_path, CONTENT)
    game.configure({'senseApp':False,'senseIdle':False,'senseCursor':False,'senseWindows':False})
    game.last_think = clock
    game.state.emotion = game.behavior.emotion = 'contente'
    game.body.grounded = True
    game.ball_stored = False
    game.ball.show()
    game.ball.body.x, game.ball.body.y = game.body.x + 75, game.body.y
    assert game.behavior.play_pull == 0.
    game.interact({'type':'play'})
    assert game.decision_snapshot()['current']['action'] == 'play'
    game.tick(.016, clock + .016)
    assert game.ball.body.vx > 0 and game.ball.body.vy < 0
    assert game.play.requested_action is None


@pytest.mark.parametrize('target',[None,'toy'])
@pytest.mark.parametrize('velocity',[(0,0),(1800,-1500)])
def test_soltar_substitui_velocidade_antiga_pelo_gesto_recente(tmp_path,target,velocity,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    item=game.ball if target else None
    body=item.body if item else game.body
    event={'id':item.id} if item else {}
    body.vx,body.vy,body.omega=900,-800,250
    body.grounded=True;body.platform=55
    game.interact(dict(event,type='drag-start',x=500,y=300))
    assert body.held and body.vx==body.vy==body.omega==0
    vx,vy=velocity
    game.interact(dict(event,type='drag-end',x=500,y=300,vx=vx,vy=vy))
    assert not body.held and not body.grounded and body.platform is None
    assert (body.vx,body.vy,body.omega)==(vx,vy,vx*.35)
    before=body.y
    clock[0]+=.016;game.tick(.016,clock[0])
    if vx:
        assert body.x>500 and body.y<before and body.vy>vy
    else:assert body.x==500 and body.y>before and body.vy>0
    assert bool(game.senses.pulse['THROW'])==(target is None and vx!=0)


def test_pegar_no_notebook_desprende_e_cai_sem_esperar_pensamento(tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.mesa.decisao.at_desk=True
    game.mesa.ancora=(game.mesa.caderno.x(),game.mesa.caderno.y())
    game.mesa.caderno.set_working(True)
    game.state.at_desk=True;game.state.desk_top=game.mesa.caderno.y()
    game.body.x,game.body.y=500,300;game.body.grounded=True
    game.interact({'type':'hold-start'})
    assert not game.mesa.sentado and not game.state.at_desk and game.state.desk_top is None
    assert not game.mesa.caderno.working
    game.last_think=100
    clock[0]+=.016;game.tick(.016,clock[0])
    assert game.body.y==300 and game.body.held
    game.interact({'type':'hold-end'})
    clock[0]+=.016;game.tick(.016,clock[0])
    assert game.body.x==500 and game.body.y>300 and game.body.vy>0
    assert not game.mesa.sentado


def test_proximidade_atencao_e_impulso_com_cooldown_sem_repetir_todo_quadro(tmp_path):
    game=Game(tmp_path,CONTENT)
    game.configure({'senseCursor':True})
    x0,y0=game.ball.body.x,game.ball.body.y
    game.cursor=(x0+60,y0)
    game._sense_toy_cursor(99.9)
    game.cursor=(x0+10,y0)
    game._sense_toy_cursor(100)
    assert game.cursor_toy_near and game.senses.pulse['NOVELTY']==pytest.approx(.35)
    assert game.ball.body.vx<0 and game.ball.body.vy<0 and not game.ball.body.grounded
    assert (game.ball.body.x,game.ball.body.y)==(x0,y0)
    assert game.behavior.look[:2]==(x0,y0)
    first_vx,first_vy=game.ball.body.vx,game.ball.body.vy
    game.ball.body.vx=game.ball.body.vy=0.
    game._sense_toy_cursor(100.016)
    assert game.senses.pulse['NOVELTY']==pytest.approx(.35)
    assert game.ball.body.vx==game.ball.body.vy==0.
    # Ainda em cooldown de cursor (0.25s) e atenção (2.5s).
    game.cursor=(0,0);game._sense_toy_cursor(100.1)
    game.cursor=(x0-10,y0);game._sense_toy_cursor(100.2)
    assert game.senses.pulse['NOVELTY']==pytest.approx(.35)
    assert game.ball.body.vx==game.ball.body.vy==0.
    # Após o cooldown, aproximar do lado esquerdo chuta para a direita.
    game.cursor=(0,0);game._sense_toy_cursor(103)
    game.cursor=(x0-10,y0);game._sense_toy_cursor(103.1)
    assert game.senses.pulse['NOVELTY']==pytest.approx(.7)
    assert game.ball.body.vx>abs(first_vx) and game.ball.body.vy<0


@pytest.mark.parametrize('disabled',['sensor','hidden','dragging','held','pet-held','panel','app-hidden','panic','blocked'])
def test_proximidade_nao_observa_nem_move_brinquedo_quando_desativado(tmp_path,disabled):
    game=Game(tmp_path,CONTENT)
    game.cursor=(game.ball.body.x-10,game.ball.body.y)
    if disabled=='sensor':game.configure({'senseCursor':False})
    elif disabled=='hidden':game.interact({'type':'ball'})
    elif disabled=='dragging':game.ball.dragging=True
    elif disabled=='held':game.ball.body.held=True
    elif disabled=='pet-held':game.body.held=True
    elif disabled=='panel':game.panel=True
    elif disabled=='app-hidden':game.hidden=True
    elif disabled=='panic':game.panicked=True
    else:game.blocked={0}
    before=vars(game.ball.body).copy()
    game._sense_toy_cursor(100)
    assert not game.cursor_toy_near and game.senses.pulse['NOVELTY']==0
    assert vars(game.ball.body)==before


@pytest.mark.parametrize('appearance',['peanut','ball'])
@pytest.mark.parametrize('side,expected_sign',[('left',1),('right',-1)])
def test_passagem_do_mouse_move_amendoim_e_bolinha_para_o_lado_oposto(tmp_path,monkeypatch,appearance,side,expected_sign):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.configure(dict(senseCursor=True,senseWindows=False,senseIdle=False,senseApp=False,
                        roaming=False,mischiefEnabled=False,adaptiveBehavior=False,
                        toyAppearance=appearance))
    game.ball.body.x,game.ball.body.y=640.,743.;game.ball.body.grounded=True;game.ball.place()
    notebook_before=game.mesa.caderno.x(),game.mesa.caderno.y()
    start_x=585. if side=='left' else 695.
    end_x=618. if side=='left' else 662.
    game.interact(dict(type='cursor',x=start_x,y=738.))
    game.tick(.016,clock[0])
    clock[0]+=.016
    game.interact(dict(type='cursor',x=end_x,y=738.))
    game.tick(.016,clock[0])
    assert game.ball.appearance==appearance
    assert game.ball.body.vx*expected_sign>200
    for _ in range(18):
        clock[0]+=.016;game.tick(.016,clock[0])
    assert (game.ball.body.x-640.)*expected_sign>35
    assert game.ball.roll_angle*expected_sign>0
    assert 0<game.ball.body.x<1280 and 0<game.ball.body.y<760
    assert (game.mesa.caderno.x(),game.mesa.caderno.y())==notebook_before


def test_distancia_zero_e_pausa_ou_toggle_nao_usam_velocidade_antiga(tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT);game.configure({'senseCursor':True})
    # Movimento rápido longe do brinquedo seguido de desativação do sensor não guarda velocidade velha.
    game.interact(dict(type='cursor',x=100.,y=200.));game._sense_toy_cursor(clock[0])
    clock[0]+=.016
    game.interact(dict(type='cursor',x=300.,y=200.));game._sense_toy_cursor(clock[0])
    assert game.cursor_velocity[0]>1000
    game.configure({'senseCursor':False})
    assert game.cursor_velocity==(0.,0.) and game.cursor_sample is None
    game.configure({'senseCursor':True})
    clock[0]+=1.
    x0,y0=game.ball.body.x,game.ball.body.y
    game.interact(dict(type='cursor',x=x0,y=y0));game._sense_toy_cursor(clock[0])
    assert game.cursor_velocity==(0.,0.)
    assert game.ball.body.vx==game.ball.body.vy==0.
    # Passar sobre o centro dá um impulso finito; depois a pausa não re-chuta.
    clock[0]+=.03;game.interact(dict(type='cursor',x=x0-2,y=y0))
    clock[0]+=.03;game.interact(dict(type='cursor',x=x0,y=y0));game._sense_toy_cursor(clock[0])
    assert game.ball.body.vx==pytest.approx(260.) and game.ball.body.vy==pytest.approx(-120.)
    game.ball.body.vx=game.ball.body.vy=0.
    clock[0]+=.4;game._sense_toy_cursor(clock[0])
    assert game.ball.body.vx==game.ball.body.vy==0.


def test_cenas_de_brincadeira_vem_do_resultado_e_dos_motores(tmp_path):
    game=Game(tmp_path,CONTENT)
    game.behavior.last_play=dict(started=100.,action=None)
    game._play_expression(100)
    assert not game.play_reaction
    game.behavior.last_play=dict(started=110.,action='kick')
    game._play_expression(110)
    assert game.play_reaction['kind']=='brinquedo_rebatida'
    assert game.play_reaction['heading'] == 0.
    game.body.grounded=True;game.next_play_scene=0
    game.mesa.decisao.at_desk=True;game.behavior.play_pull=0
    game._play_expression(120)
    assert game.play_reaction['started']==110
    game.behavior.play_pull=.7;game._play_expression(121)
    assert game.play_reaction['kind']=='fingir_trabalho'
    game._play_expression(122)
    assert game.play_reaction['started']==121
    game.mesa.decisao.at_desk=False;game.next_play_scene=0
    game.ball.body.x,game.ball.body.y=game.body.x+40,game.body.y
    game.state.tone.r['STARTLE']=.7;game._play_expression(130)
    assert game.play_reaction['kind']=='brinquedo_susto'
    game.state.tone.r['STARTLE']=0;game.next_play_scene=0
    game.behavior.adaptive_goal='play';game._play_expression(140)
    assert game.play_reaction['kind']=='preparar_bote'


def test_sinais_de_proximidade_chegam_a_rede_e_impulsionam_brinquedo(tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.ball.body.x,game.ball.body.y=game.body.x+30,game.body.y
    game.cursor=(game.ball.body.x-60,game.ball.body.y)
    game._sense_toy_cursor(clock[0]-.1)
    game.cursor=(game.ball.body.x-12,game.ball.body.y)
    game._sense_toy_cursor(clock[0])
    clock[0]+=.1;game.think(.1,clock[0])
    assert game.inputs['NOVELTY']>0 and game.inputs['TOY_NEAR']>0
    assert game.brain.time_ms>0
    assert game.ball.body.vx>0 and game.ball.body.vy<0


@pytest.mark.parametrize('choice,expected',[('kick','brinquedo_rebatida'),('wait',None)])
def test_play_real_continua_neural_e_gera_reacao_da_tentativa(tmp_path,monkeypatch,choice,expected):
    game=Game(tmp_path,CONTENT)
    monkeypatch.setattr(game.intelligence,'choose',lambda action,candidates,**kwargs:choice)
    game.body.x,game.body.y=600,400;game.body.grounded=True
    game.ball.body.x,game.ball.body.y=650,400
    game.behavior.emotion='feliz';game.behavior.play_pull=0
    game.behavior.next_roam=1e9
    before=vars(game.ball.body).copy()
    game.behavior.tick(.016,100,game.cursor,game.bounds(),game.prof)
    assert game.behavior.last_play is None and vars(game.ball.body)==before
    game.behavior.play_pull=1
    game.behavior.tick(.016,101,game.cursor,game.bounds(),game.prof)
    assert game.behavior.last_play['started']==101
    game._play_expression(101)
    assert game.play_reaction.get('kind')==expected
    if choice=='kick':
        assert game.ball.body.vx>0 and game.ball.body.vy<0
    else:assert vars(game.ball.body)==before


def test_bobinho_persegue_irrita_e_devolve_no_contato(tmp_path, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    game = Game(tmp_path, CONTENT)
    game.configure(dict(senseApp=False,senseIdle=False,senseCursor=False,senseWindows=False))
    game.last_think = 100.
    pet, toy = game.body, game.ball.body
    pet.x, pet.y = 420., game.bounds()[3]-pet.half_h
    pet.grounded, pet.surface = True, game.bounds()[3]
    game.ball.place(510., pet.y)
    toy.x, toy.y = game.ball._cx, game.ball._cy
    def move(kind, x, y):
        clock[0] += .016
        game.interact(dict(type=kind,id=game.ball.id,x=x,y=y))
        game.tick(.016,clock[0])
    move('drag-start', toy.x, toy.y)
    move('drag', 750., pet.y)
    assert pet.vx > 0 and toy.held and toy.vx == toy.vy == 0.
    assert game.behavior.toy_action == 'chase'
    assert game.play.teases == 1
    move('drag', pet.x+90., pet.y)
    move('drag', pet.x+330., pet.y)
    assert game.play.teases == 2
    assert game.play_reaction['kind'] == 'brinquedo_frustrado'
    assert game.senses.pulse['TOY_TAKEN'] > 0
    move('drag', pet.x+65., pet.y-67.)
    assert game.behavior.toy_action == 'hop' and pet.vy < 0 and toy.held
    move('drag-end', pet.x+52., pet.y-43.)
    assert toy.vy < -300. and not toy.held
    assert game.behavior.toy_action == 'return'
    assert game.play_reaction['kind'] == 'brinquedo_rebatida'


def test_toque_de_baixo_para_cima_levanta_brinquedo_e_inicia_brincadeira(tmp_path, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    game = Game(tmp_path, CONTENT)
    x,y = game.ball.body.x,game.ball.body.y
    game.interact(dict(type='cursor',x=x,y=y+55.))
    game._sense_toy_cursor(clock[0])
    clock[0] += .035
    game.interact(dict(type='cursor',x=x,y=y+14.))
    game._sense_toy_cursor(clock[0])
    assert game.ball.body.vy < -300.
    assert game.play.chase_until > clock[0]


def test_olha_mouse_em_movimento_mesmo_com_brinquedo_guardado(tmp_path, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    game = Game(tmp_path, CONTENT)
    game.last_think = clock[0]
    game.body.x, game.body.y = 500., 350.
    game.behavior.glance = (300., 350.)
    game.behavior.next_glance = 1e9
    game.interact({'type':'ball'})
    game.interact(dict(type='cursor',x=680.,y=350.))
    clock[0] += .016
    game.interact(dict(type='cursor',x=715.,y=350.))
    game.tick(.016,clock[0])
    assert game.state.gaze[0] > .99
    game.configure({'senseCursor':False})
    clock[0] += .016
    game.tick(.016,clock[0])
    assert game.state.gaze[0] < -.99
