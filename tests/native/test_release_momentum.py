# SPDX-License-Identifier: GPL-3.0-only
"""O gesto real alimenta a física existente, sem impulso nos cancelamentos."""
from pathlib import Path
from types import SimpleNamespace
import math
import time

import pytest
from PySide6.QtCore import QEvent,QPointF,Qt

from game import Game
from bolha.grab import MouseGrab
from bolha.pet import PetWindow
from bolha.scene import NativeScene,ObjectWindow
import bolha.grab as grab_module

CONTENT=Path(__file__).resolve().parents[2]/'assets/bolha/content'


def mouse(x,y):
    return SimpleNamespace(button=lambda:Qt.LeftButton,globalPosition=lambda:QPointF(x,y))


@pytest.fixture(params=['pet','peanut','ball'])
def gesture(request,qt_application,tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(grab_module,'drag_pointer',lambda:None)
    game=Game(tmp_path,CONTENT)
    game.configure(dict(senseApp=False,senseIdle=False,senseCursor=False,senseWindows=False,
                        roaming=False,mischiefEnabled=False,adaptiveBehavior=False,
                        toyAppearance='ball' if request.param=='ball' else 'peanut'))
    pet=request.param=='pet'
    game.body.x,game.body.y=(500 if pet else 150),300
    game.ball.body.x,game.ball.body.y=(150 if pet else 500),300
    game.ball.place()
    window=PetWindow(game) if pet else ObjectWindow(NativeScene(game),game.ball)
    body=game.body if pet else game.ball.body
    window.sync();window.mousePressEvent(mouse(508,309))
    try:yield window,game,body,clock
    finally:window.close()


def flick(window,clock):
    clock[0]+=.04;window.mouseMoveEvent(mouse(548,289))
    clock[0]+=.04;window.mouseMoveEvent(mouse(588,269))


def test_soltura_rapida_continua_da_posicao_final_com_cursor_sobre_objeto(gesture):
    window,game,body,clock=gesture
    flick(window,clock)
    clock[0]+=.02;window.mouseReleaseEvent(mouse(608,259))
    assert (body.x,body.y)==(600,250)
    assert (body.vx,body.vy,body.omega)==pytest.approx((1000,-500,350))
    assert not body.held and not body.grounded and body.platform is None
    # O cursor continua em cima do corpo; hover e passeio desligado não apagam inércia aérea.
    game.cursor=(608,259);game.hover=True
    game.interact({'type':'hold-end'});game.interact({'type':'hold-end'})
    assert (body.vx,body.vy,body.omega)==pytest.approx((1000,-500,350))
    clock[0]+=.016;game.tick(.016,clock[0])
    assert body.x>600 and body.y<250 and body.vx>990 and body.vy>-500
    assert body.angle>0 and not body.held
    assert game.prefs['senseCursor'] is False


def test_flick_seguido_de_pausa_ou_nova_pega_nao_reutiliza_impulso(gesture):
    window,game,body,clock=gesture
    flick(window,clock);clock[0]+=.2
    window.mouseReleaseEvent(mouse(588,269))
    assert body.vx==body.vy==body.omega==0
    window.mousePressEvent(mouse(588,269));clock[0]+=3
    window.mouseReleaseEvent(mouse(588,269))
    assert body.vx==body.vy==body.omega==0
    x,y=body.x,body.y;clock[0]+=.016;game.tick(.016,clock[0])
    assert body.x==x and body.y>y and body.vy>0


@pytest.mark.parametrize('finish',['poll','ungrab','qt-release'])
def test_soltura_fisica_sem_ultimo_move_usa_historia_durante_perda_de_captura(gesture,finish):
    window,game,body,clock=gesture
    pointer=SimpleNamespace(point=QPointF(548,289),down=True)
    pointer.sample=lambda:(pointer.point,pointer.down)
    window.mouse_grab.pointer=pointer
    clock[0]+=.04;window.event(QEvent(QEvent.UngrabMouse))
    assert body.held and (body.x,body.y)==(540,280)
    clock[0]+=.04;pointer.point=QPointF(588,269);pointer.down=False
    if finish=='poll':window.poll_interaction()
    elif finish=='ungrab':window.event(QEvent(QEvent.UngrabMouse))
    else:window.mouseReleaseEvent(mouse(1,1))
    assert not body.held and (body.x,body.y)==(580,260)
    assert (body.vx,body.vy,body.omega)==pytest.approx((1000,-500,350))
    before=body.vx,body.vy,body.omega
    window.poll_interaction();window.mouseReleaseEvent(mouse(1,1))
    assert (body.vx,body.vy,body.omega)==before and not window.mouse_grab.samples


@pytest.mark.parametrize('reason',['cancel','hide','menu','device-error'])
def test_cancelar_flick_rapido_termina_sem_impulso(gesture,reason):
    window,game,body,clock=gesture
    flick(window,clock)
    if reason=='hide':game.interact(dict(type='hide',value=True));window.sync()
    elif reason=='menu':game.panel=True;window.poll_interaction()
    elif reason=='device-error':
        def unavailable():raise OSError('desktop indisponível')
        window.mouse_grab.pointer=SimpleNamespace(sample=unavailable);window.poll_interaction()
    else:window.cancel_interaction()
    assert not body.held and body.vx==body.vy==body.omega==0
    assert not window.mouse_grab.samples and not game.in_flight
    clock[0]+=.02;window.mouseReleaseEvent(mouse(608,259))
    assert body.vx==body.vy==body.omega==0


@pytest.mark.parametrize('pause,expected',[(0,1000),(.04,1000*2/3),(.08,1000/3),(.13,0),(.2,0)])
def test_estimador_enfraquece_ao_parar_e_descarta_movimento_antigo(qt_application,monkeypatch,pause,expected):
    clock=[10.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(grab_module,'drag_pointer',lambda:None)
    grab=MouseGrab(SimpleNamespace(isVisible=lambda:False))
    grab.begin(QPointF(-100,50))
    clock[0]+=.04;grab.track(QPointF(-60,30))
    clock[0]+=.04;grab.track(QPointF(-20,10))
    clock[0]+=pause
    vx,vy=grab.velocity(QPointF(-20,10))
    assert (vx,vy)==pytest.approx((expected,-expected/2))
    grab.stop();assert not grab.samples


def test_estimador_descarta_timestamps_iguais_relogio_recuado_e_amostras_velhas(qt_application,monkeypatch):
    clock=[10.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(grab_module,'drag_pointer',lambda:None)
    grab=MouseGrab(SimpleNamespace(isVisible=lambda:False))
    grab.begin(QPointF(0,0));grab.track(QPointF(100,100))
    assert grab.velocity(QPointF(200,200))==(0,0)
    clock[0]=9.;assert grab.velocity(QPointF(0,0))==(0,0)
    for index in range(300):
        clock[0]+=.001;grab.track(QPointF(index,index/2))
    assert len(grab.samples)<=64 and grab.velocity(QPointF(299,149.5))==pytest.approx((1000,500))
    clock[0]+=1;assert grab.velocity(QPointF(299,149.5))==(0,0)


def test_arredondamento_subpixel_na_captura_nao_cria_arremesso(gesture):
    window,game,body,clock=gesture
    # QMouseEvent pode vir fracionário, enquanto QCursor.pos chega arredondado.
    clock[0]+=.0001;window.mouseMoveEvent(mouse(508.49,309.49))
    assert (body.x,body.y)==pytest.approx((500.49,300.49))
    clock[0]+=.0001;window.mouseReleaseEvent(mouse(508,309))
    assert body.vx==body.vy==body.omega==0 and game.senses.pulse['THROW']==0


@pytest.mark.parametrize('target',['pet','toy'])
@pytest.mark.parametrize('velocity,expected',[
    ((1e100,-1e100),(2500,-2500)),
    ((math.inf,math.nan),(0,0)),
    (('inválido',None),(0,0)),
    ((True,False),(0,0)),
    pytest.param((10**500,-10**500),(2500,-2500),id='huge-integers'),
])
def test_game_limita_impulso_e_rejeita_valores_invalidos(tmp_path,target,velocity,expected):
    game=Game(tmp_path,CONTENT);item=game.ball if target=='toy' else None
    body=item.body if item else game.body;event=dict(id=item.id) if item else {}
    game.interact(dict(event,type='drag-start',x=500,y=300))
    game.interact(dict(event,type='drag-end',x=500,y=300,vx=velocity[0],vy=velocity[1]))
    assert (body.vx,body.vy)==expected and body.omega==expected[0]*.35
    assert all(math.isfinite(value) for value in (body.vx,body.vy,body.omega))


def test_game_soltar_celere_alimenta_throw_e_conserva_reacao_do_cerebro(tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT);game.configure(dict(roaming=False,senseCursor=False))
    game.interact(dict(type='hold-start'));game.state.tone.r['ANGRY']=.9
    game.drives.stimulation=0;game.drives.contact=.8
    clock[0]+=5
    game.interact(dict(type='drag-end',x=500,y=300,vx=1600,vy=-700))
    assert game.release_reaction['kind']=='birra' and game.in_flight
    assert game.senses.pulse['THROW']>0 and game.drives.stimulation==pytest.approx(.35)
    reaction=game.release_reaction.copy();game.interact(dict(type='hold-end'))
    assert (game.body.vx,game.body.vy)==(1600,-700) and game.release_reaction==reaction
    game.interact(dict(type='hold-start'));assert not game.in_flight
    game.interact(dict(type='drag-end',x=500,y=300,vx=2000,vy=-1000,cancelled=True))
    assert game.body.vx==game.body.vy==game.body.omega==0 and not game.release_reaction


@pytest.mark.parametrize('kind',['notebook','note','paper'])
def test_notebook_bilhete_e_papel_nao_recebem_arremesso(qt_application,tmp_path,monkeypatch,kind):
    from pestinha.scene import Ball
    clock=[100.];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(grab_module,'drag_pointer',lambda:None)
    game=Game(tmp_path,CONTENT)
    if kind=='notebook':item=game.mesa.caderno;item.show();item.place(500,300)
    elif kind=='paper':item=Ball(500,300,kind='papel');item.show()
    else:
        item=game.mischief._make('bilhete','feliz',False);item.place(500,300);game.mischief._add(item)
    window=ObjectWindow(NativeScene(game),item)
    try:
        window.mousePressEvent(mouse(500,300));clock[0]+=.04
        window.mouseMoveEvent(mouse(600,250));window.mouseReleaseEvent(mouse(600,250))
        position=(item.body.x,item.body.y) if hasattr(item,'body') else (item._cx,item._cy)
        assert position==(600,250) and not game.scene_dragging
        if hasattr(item,'body'):assert item.body.vx==item.body.vy==item.body.omega==0
        if kind=='note':assert not item.closed and not game.mischief_ctl.dismiss_times
        assert game.senses.pulse['THROW']==0
    finally:window.close()
