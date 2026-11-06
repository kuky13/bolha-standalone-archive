"""
FESTA - o fogo de artifício do pet feliz: a alegria da rede enche a euforia.

Não é sorteado. A população CHEER (alegria) acumula euforia enquanto ele está
feliz; quando a euforia enche, ele solta um fogo, e depois precisa de um tempo
antes de soltar outro. O desenho do fogo fica em pestinha/world/fireworks.py.
"""

from ..ajustes import ATIVIDADE_MINIMA_VOO, ESPERA_FOGOS, EUFORIA_MAXIMA
from ..log import log
from ..world.fireworks import Fireworks

RITMO_EUFORIA = 0.1         # quanto a alegria acima do repouso enche por tick
DESCANSO_EUFORIA = 0.08     # quanto a euforia esvazia por tick, sem alegria
ALEGRIA_PARA_CHEIO = 6.0    # Hz acima do repouso que enchem a euforia em um tick
AUTO_COOLDOWN = 120.
REQUEST_COOLDOWN = 8.


class FestaController:
    """Fogos de artifício quando o pet está muito feliz (a alegria da rede enche a euforia)."""
    def __init__(self, debug, app):
        """Cria a janela dos fogos e começa sem euforia."""
        self.fogos = Fireworks(app)
        self.euforia = 0.0
        self.pronto_em = 0.0
        self.debug = debug
        self.policy = None
        self.rates = {}
        self.energy = 1.
        self.contact = 0.
        self.requested = False
        self.request_ready_at = 0.

    def tick(self, now, motor, emocao, corpo, pode_soltar, dt=0.1):
        """Acumula euforia e solta um fogo quando ela enche. Devolve True se soltou."""
        alegria = max(0.0, motor["CHEER"] - ATIVIDADE_MINIMA_VOO)
        passos = dt / 0.1                            # o ritmo foi calibrado para ciclos de 0,1 s
        self.euforia += passos * (RITMO_EUFORIA * alegria / ALEGRIA_PARA_CHEIO - RITMO_EUFORIA * DESCANSO_EUFORIA)
        self.euforia = max(0.0, min(EUFORIA_MAXIMA, self.euforia))
        requested, self.requested = self.requested, False
        if not pode_soltar:
            return False
        explicit = requested and now >= self.request_ready_at
        eligible = explicit or (self.euforia >= 1.0 and emocao == "feliz" and now >= self.pronto_em)
        action = 'fireworks' if explicit else self.policy.choose('celebration', ['fireworks','wait'], rates=self.rates,
                    emotion=emocao, energy=self.energy, contact=self.contact,
                    weights={'fireworks': max(0., min(1., motor['CHEER']/30.))}) if self.policy and eligible else None
        if eligible and action == 'fireworks':
            self.fogos.launch(corpo.x, corpo.y - 30)
            self.euforia = 0.0
            self.pronto_em = now + max(ESPERA_FOGOS, AUTO_COOLDOWN)
            self.request_ready_at = now + REQUEST_COOLDOWN
            if self.debug():
                log("[fogos] soltou um fogo (alegria da rede)")
            return True
        return False

    def fechar(self):
        """Fecha a janela dos fogos ao sair."""
        self.fogos.close()
