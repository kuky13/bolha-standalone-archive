# SPDX-License-Identifier: GPL-3.0-only
"""Reações ao contato real e intervalos de comemoração sem fila escondida."""
import math
from pathlib import Path
import time

import pytest

from game import Game


CONTENT=Path(__file__).resolve().parents[2]/'assets/bolha/content'


def at_rest(tmp_path,monkeypatch):
    clock=[100.]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    game=Game(tmp_path,CONTENT)
    game.configure(dict(senseApp=False,senseIdle=False,senseCursor=False,senseWindows=False,roaming=False))
    game.body.x=600.
    game.body.y=game.bounds()[3]-game.body.half_h
    game.body.grounded=True
    game.body.surface=game.bounds()[3]
    game.state.emotion=game.behavior.emotion='contente'
    game.last_think=clock[0]
    return game,clock


@pytest.mark.parametrize('appearance',['ball','peanut'])
@pytest.mark.parametrize('side',[-1.,1.])
def test_arremesso_real_rebate_uma_vez_e_alimenta_o_cerebro(tmp_path,monkeypatch,appearance,side):
    game,clock=at_rest(tmp_path,monkeypatch)
    game.configure({'toyAppearance':appearance})
    pet,toy=game.body,game.ball.body
    pet.grounded=True;pet.y=pet.surface-pet.half_h
    toy.x=pet.x+side*(pet.half_w+toy.half_w+9.)
    toy.y=pet.y
    toy.vx=-side*900.
    toy.grounded=False
    clock[0]+=.016
    game.tick(.016,clock[0])
    assert toy.vx*side>600.
    assert game.play_reaction['kind']=='brinquedo_rebatida'
    assert game.play_reaction['heading']==pytest.approx(math.degrees(math.atan2(toy.vy,toy.vx)))
    assert game.senses.pulse['IMPACT']>0. and game.senses.pulse['NOVELTY']>0.
    reaction=dict(game.play_reaction)
    impact=game.senses.pulse['IMPACT']
    for _ in range(3):
        clock[0]+=.016
        game.tick(.016,clock[0])
    assert game.play_reaction==reaction and game.senses.pulse['IMPACT']==impact
    assert math.dist((pet.x,pet.y),(toy.x,toy.y))>pet.half_w+toy.half_w


def test_brinquedo_rapido_nao_atravessa_bolha_pequena(tmp_path,monkeypatch):
    game,clock=at_rest(tmp_path,monkeypatch)
    game.configure({'avatarSize':48})
    pet,toy=game.body,game.ball.body
    toy.x=pet.x+pet.half_w+toy.half_w+5.
    toy.y=pet.y
    toy.vx=-2500.
    clock[0]+=.05
    game.tick(.05,clock[0])
    assert toy.x>pet.x and toy.vx>0.
    assert game.play_reaction['kind']=='brinquedo_rebatida'


def test_impacto_real_acorda_a_bolha_sem_simular_tropeco(tmp_path,monkeypatch):
    game,clock=at_rest(tmp_path,monkeypatch)
    game.sleep.asleep=True
    pet,toy=game.body,game.ball.body
    toy.x=pet.x+pet.half_w+toy.half_w+9.
    toy.y=pet.y
    toy.vx=-900.
    clock[0]+=.016
    game.tick(.016,clock[0])
    assert not game.sleep.asleep
    assert game.play_reaction['kind']=='brinquedo_susto'


@pytest.mark.parametrize('winner,previous_score,expected',[
    ('player',0,'assustado'),('pet',0,'feliz'),('pet',4,'comemorando'),
])
def test_ponto_real_na_partida_nao_simula_tropeco(tmp_path,monkeypatch,winner,previous_score,expected):
    game,clock=at_rest(tmp_path,monkeypatch)
    game.configure({'senseCursor':True})
    game.interact({'type':'pingpong'})
    match=game.pingpong
    match.serve_delay=0.
    match.ball_y=match.area[3]-match.toy_radius-2.
    match.vy=0.
    if winner=='player':
        match.player_score=previous_score
        match.ball_x=match.area[0]+match.toy_radius+1.
        match.vx=-500.
    else:
        match.pet_score=previous_score
        match.ball_x=match.area[2]-match.toy_radius-1.
        match.vx=500.
    clock[0]+=.016
    game.tick(.016,clock[0])
    assert game.play_reaction['kind']==expected


@pytest.mark.parametrize('held',['pet','toy'])
def test_contato_com_objeto_segurado_nao_rebate(tmp_path,monkeypatch,held):
    game,clock=at_rest(tmp_path,monkeypatch)
    pet,toy=game.body,game.ball.body
    toy.x=pet.x+pet.half_w+toy.half_w-3.
    toy.y=pet.y
    toy.vx=-500.
    if held=='pet':
        pet.held=True
    else:
        toy.held=game.ball.dragging=True
    clock[0]+=.016
    game.tick(.016,clock[0])
    assert toy.vx<0. and not game.play_reaction
    assert game.senses.pulse['IMPACT']==0.


def test_encosto_em_repouso_nao_gera_sustos_nem_tremedeira(tmp_path,monkeypatch):
    game,clock=at_rest(tmp_path,monkeypatch)
    pet,toy=game.body,game.ball.body
    toy.y=game.bounds()[3]-toy.half_h
    radius=pet.half_w+toy.half_w
    toy.x=pet.x+math.sqrt(radius**2-(toy.y-pet.y)**2)
    toy.grounded=True
    toy.surface=game.bounds()[3]
    start=toy.x,toy.y
    assert math.dist((pet.x,pet.y),start)==pytest.approx(radius)
    for _ in range(4):
        clock[0]+=.016
        game.tick(.016,clock[0])
    assert toy.vx==toy.vy==0.
    assert (toy.x,toy.y)==start and not game.play_reaction
    assert game.senses.pulse['IMPACT']==0.


def test_fogos_automaticos_respeitam_dois_minutos_e_pedido_tem_intervalo_proprio(tmp_path,monkeypatch):
    game,clock=at_rest(tmp_path,monkeypatch)
    launched=[]
    monkeypatch.setattr(game.festa.fogos,'launch',lambda *position:launched.append(position))
    monkeypatch.setattr(game.intelligence,'choose',lambda *args,**kwargs:'fireworks')
    fiesta=game.festa
    assert fiesta.tick(100.,{'CHEER':30.},'feliz',game.body,True,4.)
    assert not fiesta.tick(219.,{'CHEER':30.},'feliz',game.body,True,4.)
    assert fiesta.tick(220.,{'CHEER':30.},'feliz',game.body,True,4.)
    clock[0]=228.
    game.interact({'type':'celebrate'})
    assert fiesta.requested
    assert fiesta.tick(clock[0],{'CHEER':0.},'contente',game.body,True,0.)
    game.interact({'type':'celebrate'})
    assert not fiesta.requested and len(launched)==3


@pytest.mark.parametrize('blocked',['panel','held','sleep','hidden'])
def test_pedido_de_fogos_nao_fica_na_fila_enquanto_bolha_esta_ocupada(tmp_path,monkeypatch,blocked):
    game,clock=at_rest(tmp_path,monkeypatch)
    launched=[]
    monkeypatch.setattr(game.festa.fogos,'launch',lambda *position:launched.append(position))
    game.interact({'type':'celebrate'})
    assert game.festa.requested
    if blocked=='panel':game.panel=True
    elif blocked=='held':game.body.held=True
    elif blocked=='sleep':game.sleep.asleep=True
    else:game.hidden=True
    clock[0]+=.016
    game.tick(.016,clock[0])
    assert not game.festa.requested and not launched
