# SPDX-License-Identifier: GPL-3.0-only
"""Modelo da partida de pingue-pongue em coordenadas do desktop."""
from __future__ import annotations

import math


class PingPong:
    """A área útil da tela é a mesa, e o ponteiro rebate pelo contato."""

    def __init__(self, area, pet_radius, toy_radius):
        if len(area) != 4:
            raise ValueError("area must be (left, top, right, bottom)")
        self.area = tuple(map(float, area))
        left, top, right, bottom = self.area
        self.pet_radius = max(1.0, float(pet_radius))
        self.toy_radius = max(2.0, float(toy_radius))
        width, height = right-left, bottom-top
        if width < max(320.,4*self.pet_radius) or height < max(220.,2*self.pet_radius+24.):
            raise ValueError("usable area is too small for ping-pong")
        self.speed_scale = self._clamp(width/1100.,.82,2.)
        self.cursor_radius = self.toy_radius + max(14.,min(24.,self.toy_radius))
        self.pet_x = left + self.pet_radius + 12.
        self.pet_y = (top+bottom)/2
        self.ball_x = (left+right)/2
        self.ball_y = (top+bottom)/2
        self.vx = self.vy = 0.0
        self.player_score = self.pet_score = self.rally = self.best = 0
        self.serve_delay = .65
        self.finished = False
        self.winner = None
        self._serve_sign = 1
        self._reaction_delay = 0.
        self._last_cursor = None

    def clear_pointer(self):
        """Retomar uma partida começa com a posição atual do ponteiro."""
        self._last_cursor = None

    def step(self, dt, cursor, vigor):
        """Advance by dt seconds and return a hit/point event, if one occurred."""
        if self.finished:
            return None
        dt = max(0.0, min(float(dt), .12))
        l, t, r, b = self.area
        vigor = max(0.0, min(1.0, float(vigor)))
        cursor_start = self._last_cursor or cursor
        self._last_cursor = cursor
        if self.serve_delay > 0:
            self.serve_delay = max(0.0, self.serve_delay - dt)
            if self.serve_delay == 0:
                self._start_serve()
            return None
        if dt == 0:
            return None
        mouse_dx = cursor[0]-cursor_start[0]
        mouse_dy = cursor[1]-cursor_start[1]
        swing = self._clamp(mouse_dy/dt/850.,-1.,1.)

        # A Bolha volta ao centro e só tenta interceptar quando o brinquedo se aproxima.
        ai_speed = (145.0 + 125.0 * vigor) * min(1., (b-t)/600.)
        target = (t+b)/2
        self._reaction_delay = max(0., self._reaction_delay-dt)
        contact_x = self.pet_x + self.pet_radius + self.toy_radius
        distance = self.ball_x-contact_x
        if (self.vx < 0 and self._reaction_delay == 0.
                and distance <= min(310., (r-l)*.36)):
            anticipation = .45 + .35*vigor
            travel = max(0., distance / -self.vx)
            target = self._reflected_y(self.ball_y + self.vy*travel*anticipation,
                                       t+self.toy_radius,b-self.toy_radius)
        if self.vx >= 0 or self._reaction_delay == 0.:
            pet_margin = min(self.pet_radius, (b-t)/2.)
            target = self._clamp(target, t+pet_margin, b-pet_margin)
            self.pet_y += self._clamp(target - self.pet_y, -ai_speed * dt, ai_speed * dt)

        # Small deterministic substeps bound travel per step and prevent tunneling.
        max_step = max(1.0, self.toy_radius * .45)
        n = max(1, int(math.ceil(math.hypot(self.vx, self.vy) * dt / max_step)))
        h = dt / n
        event = None
        for substep in range(n):
            previous_x, previous_y = self.ball_x,self.ball_y
            self.ball_x += self.vx * h
            self.ball_y += self.vy * h
            if self.ball_y - self.toy_radius < t:
                self.ball_y = 2 * (t + self.toy_radius) - self.ball_y
                self.vy = abs(self.vy)
            elif self.ball_y + self.toy_radius > b:
                self.ball_y = 2 * (b - self.toy_radius) - self.ball_y
                self.vy = -abs(self.vy)
            strike = None
            if self.vx > 0 and self.ball_x >= contact_x+self.cursor_radius:
                fraction = substep/n
                strike = self._cursor_contact(
                    previous_x-cursor_start[0]-mouse_dx*fraction,
                    previous_y-cursor_start[1]-mouse_dy*fraction,
                    self.ball_x-previous_x-mouse_dx/n,
                    self.ball_y-previous_y-mouse_dy/n,
                )
            if strike is not None:
                fraction, offset = strike
                self.ball_x = previous_x+(self.ball_x-previous_x)*fraction
                self.ball_y = previous_y+(self.ball_y-previous_y)*fraction
                self._bounce_from(.7*offset+.55*swing,-1)
                self.rally += 1
                self.best = max(self.best, self.rally)
                self._reaction_delay = .24 - .12 * vigor
                event = 'player_hit'
            elif (self.vx < 0 and self.ball_x >= self.pet_x
                  and math.hypot(self.ball_x-self.pet_x,self.ball_y-self.pet_y) <= self.pet_radius+self.toy_radius):
                radius = self.pet_radius+self.toy_radius
                dy = self.ball_y-self.pet_y
                self.ball_x = self.pet_x + math.sqrt(max(0., radius**2-dy**2))
                self._bounce_from(dy/self.pet_radius,1)
                self.rally += 1
                self.best = max(self.best, self.rally)
                event = 'pet_hit'
            if self.ball_x + self.toy_radius >= r:
                return self._point('pet_point')
            if self.ball_x - self.toy_radius <= l:
                return self._point('player_point')
        return event

    def _cursor_contact(self, x, y, dx, dy):
        """Encontra o primeiro contato entre os dois movimentos no quadro."""
        distance = x*x + y*y - self.cursor_radius**2
        if distance <= 0.:
            return 0.,y/self.cursor_radius
        travel = dx*dx + dy*dy
        approach = x*dx + y*dy
        discriminant = approach*approach-travel*distance
        if not travel or approach >= 0. or discriminant < 0.:
            return None
        fraction = (-approach-math.sqrt(discriminant))/travel
        if 0. <= fraction <= 1.:
            return fraction,(y+dy*fraction)/self.cursor_radius
        return None

    def _bounce_from(self, offset, direction):
        speed = self._clamp(math.hypot(self.vx,self.vy)*1.035,310.*self.speed_scale,780.*self.speed_scale)
        angle = self._clamp(offset,-1.,1.)*.92
        self.vx = direction * speed * math.cos(angle)
        self.vy = speed * math.sin(angle)

    def _point(self, event):
        if event == 'player_point':
            self.player_score += 1
            self._serve_sign = -1
        else:
            self.pet_score += 1
            self._serve_sign = 1
        self.rally = 0
        self.ball_x = (self.area[0] + self.area[2]) / 2
        self.ball_y = (self.area[1] + self.area[3]) / 2
        self.vx = self.vy = 0.0
        self._reaction_delay = 0.
        if max(self.player_score, self.pet_score) >= 5:
            self.finished = True
            self.winner = 'player' if self.player_score > self.pet_score else 'pet'
        else:
            self.serve_delay = .65
        return event

    def _start_serve(self):
        self.ball_x = (self.area[0] + self.area[2]) / 2
        self.ball_y = (self.area[1] + self.area[3]) / 2
        self.vx = self._serve_sign * 330.0*self.speed_scale
        self.vy = 90.0 if (self.player_score+self.pet_score) % 2 == 0 else -90.0

    @staticmethod
    def _clamp(value, low, high):
        return min(high, max(low, value))

    @staticmethod
    def _reflected_y(y, low, high):
        span = high - low
        if span <= 0:
            return (low + high) / 2
        z = (y - low) % (2 * span)
        return low + (z if z <= span else 2 * span - z)
