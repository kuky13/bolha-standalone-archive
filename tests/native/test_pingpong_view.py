# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from bolha.app import NativeApp
from bolha.pingpong_view import PingPongView
from game import Game
from pingpong import PingPong


def test_menu_inicia_e_fecha_placar_transparente(qt_application,tmp_path):
    game = Game(tmp_path, Path(__file__).resolve().parents[2]/'assets/bolha/content')
    game.desktop({'areas':[dict(x=-1000,y=-50,width=1000,height=620)]})
    view = PingPongView()
    noop = lambda *args: None
    app = NativeApp.__new__(NativeApp)
    app.__dict__.update(game=game,pingpong_view=view,show_settings=noop,show_neural=noop,
                        request_reaction=noop,updater=SimpleNamespace(check=noop,defer=noop),
                        quit=noop,cancel_interactions=noop,dialogs=[])
    app.interact = lambda kind,**data:game.interact(dict(type=kind,**data))
    menu = app.make_menu()
    try:
        app.pingpong_action.trigger()
        assert game.pingpong is not None and view.isVisible()
        assert view.geometry().getRect()==(-680,-38,360,64)
        assert view.windowFlags() & Qt.WindowTransparentForInput
        assert view.testAttribute(Qt.WA_ShowWithoutActivating)
        assert not view.grab().isNull()
        menu.aboutToShow.emit()
        assert app.pingpong_action.text()=='Encerrar pingue-pongue'
        app.pingpong_action.trigger()
        assert game.pingpong is None and not view.isVisible()
    finally:
        menu.close()
        view.close()


def test_raquete_acompanha_contato_e_recorta_monitor_sem_capturar_mouse(qt_application):
    match = PingPong((-1000.,-50.,0.,570.),68.,18.)
    view = PingPongView()
    try:
        cursor=(-800.,250.)
        view.sync(match,cursor=cursor)
        paddle=view.paddle
        assert paddle.isVisible() and paddle.radius==match.cursor_radius-match.toy_radius==18.
        assert (paddle.x()+38,paddle.y()+28)==cursor
        assert paddle.windowFlags() & Qt.WindowTransparentForInput
        assert paddle.testAttribute(Qt.WA_ShowWithoutActivating)
        face=paddle.grab().toImage().pixelColor(38,28)
        assert face.red()>face.blue() and face.alpha()==255
        view.sync(match,cursor=(-999.,250.))
        clipped=paddle.grab().toImage()
        assert all(clipped.pixelColor(x,28).alpha()==0 for x in range(37))
        view.sync(match,paused=True,cursor=cursor)
        assert not paddle.isVisible() and view.isVisible()
        view.sync(match,cursor=(10.,250.))
        assert not paddle.isVisible()
        match.finished=True
        view.sync(match,cursor=cursor)
        assert not paddle.isVisible()
        view.sync(None)
        assert not paddle.isVisible() and not view.isVisible()
    finally:
        view.close()


def test_contato_real_da_raquete_produz_brilho_breve(qt_application,monkeypatch):
    import time
    clock=[100.]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    match=PingPong((0.,0.,1000.,620.),68.,18.)
    match.serve_delay=0.
    match.ball_x,match.ball_y=650.,300.
    match.vx,match.vy=400.,0.
    view=PingPongView()
    cursor=(680.,300.)
    try:
        view.sync(match,cursor=cursor)
        assert match.step(.016,cursor,.5)=='player_hit'
        view.sync(match,cursor=cursor)
        assert view.paddle.flash_until==100.16
        lit=view.paddle.grab().toImage()
        clock[0]+=.2
        view.sync(match,cursor=cursor)
        normal=view.paddle.grab().toImage()
        assert lit!=normal
    finally:
        view.close()
