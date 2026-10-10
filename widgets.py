#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composants graphiques dessinés sur le canvas (ToolTip, Knob, SwitchOn, Wheel, Keyboard)."""
import math
import tkinter as tk

class ToolTip:
    """Bulles d'aide : une seule fenêtre réutilisée, positionnée près du pointeur."""

    def __init__(self):
        self.win = None
        self.lbl = None

    def show(self, text, sx, sy):
        if self.win is None:
            self.win = tk.Toplevel()
            self.win.overrideredirect(True)
            try:
                self.win.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.win.configure(bg="#1c2128")
            self.lbl = tk.Label(
                self.win, text="", bg="#1c2128", fg="#e8e8e8",
                font=("Helvetica", 10), justify="left",
                wraplength=320, padx=8, pady=5)
            self.lbl.pack()
        self.lbl.configure(text=text)
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        px = min(sx + 16, sw - w - 8)
        py = min(sy + 18, sh - h - 8)
        self.win.geometry(f"{w}x{h}+{px}+{py}")
        self.win.deiconify()

    def hide(self):
        if self.win is not None:
            self.win.withdraw()


class PanelComponent:
    """Base : résultats de mise à jour transmis au canvas."""


class Knob:
    """Cadran rotatif (potentiomètre) dessiné sur le canvas."""

    def __init__(self, cv, x, y, label, cw=270, lo=0.0, hi=1.0, fmt="{:.2f}",
                 wave=None, norm=None, accent=None):
        self.cv = cv
        self.cx, self.cy = x, y
        self.r = 26
        self.label = label
        self.cw, self.lo, self.hi = cw, lo, hi
        self.fmt = fmt
        self.wave = wave
        # norm : callable(valeur) -> 0..1 utilisé pour l'angle de l'aiguille.
        # Permet d'afficher la ROTATION réelle du pot (inverse du taper) tout en
        # gardant la valeur physique en texte (ex: attack exponentiel 0..10s).
        self.norm = norm
        # accent : teinte propre à ce potard (FREQ OSC2 / FREQ OSC3) —
        # étiquette, graduations, index et couronne de la face supérieure
        # prennent cette couleur, ce qui rend les deux pots distincts.
        self.accent = accent
        self.idv = {}
        self._draw()

    def _angle(self, val):
        t = (val - self.lo) / (self.hi - self.lo) if self.hi != self.lo else 0.0
        t = max(0.0, min(1.0, t))
        return self._angle_t(t)

    def _angle_t(self, t):
        # Potentio courbe : 0% -> bas-gauche (225°), 50% -> haut (90°),
        # 100% -> bas-droite (315°/-45°). Angle décroissant sens horaire
        # dans le repère canvas (y vers le bas).
        return math.radians(225.0) - math.radians(self.cw) * t

    def _draw(self):
        cv = self.cv
        x, y, r = self.cx, self.cy, self.r
        self.idv["label"] = cv.create_text(
            x, y - r - 20, text=self.label, font=("Helvetica", 9, "bold"),
            fill=self.accent or "#d8d8d8")
        # Échelle sérigraphiée autour du cadran (blanc cassé, comme le Model D)
        n = max(5, int(self.cw / 22.5) + 1)
        for i in range(n):
            t = i / (n - 1)
            a = self._angle(self.lo + t * (self.hi - self.lo))
            x1 = x + math.cos(a) * (r + 6)
            y1 = y - math.sin(a) * (r + 6)
            x2 = x + math.cos(a) * (r + 10)
            y2 = y - math.sin(a) * (r + 10)
            cv.create_line(x1, y1, x2, y2,
                           fill=self.accent or "#a8a191", width=1)
        # Ombre portée sur la plaque métallique
        cv.create_oval(x - r + 3, y - r + 4, x + r + 3, y + r + 4,
                       fill="#0a0b0c", outline="")
        # Corps : bakélite noir mat, pourtour cannelé (30 rayons) puis face
        # supérieure légèrement plus claire — le potard du Model D.
        self.idv["body"] = cv.create_oval(x - r, y - r, x + r, y + r,
                                          fill="#171a1e", outline="#07080a",
                                          width=1)
        for i in range(30):
            a = math.radians(i * 12.0)
            ca, sa = math.cos(a), math.sin(a)
            cv.create_line(x + ca * (r - 6), y - sa * (r - 6),
                           x + ca * (r - 1), y - sa * (r - 1),
                           fill="#41474f", width=2)
        self.idv["cap"] = cv.create_oval(x - r * 0.76, y - r * 0.76,
                                         x + r * 0.76, y + r * 0.76,
                                         fill="#2b3037",
                                         outline=self.accent or "#0c0e11",
                                         width=2 if self.accent else 1)
        if self.wave is None:
            a0 = self._angle(0.0)
            self.idv["needle"] = cv.create_line(
                x + r * 0.10 * math.cos(a0), y - r * 0.10 * math.sin(a0),
                x + r * 0.70 * math.cos(a0), y - r * 0.70 * math.sin(a0),
                fill=self.accent or "#efe9dc", width=3, capstyle="round")
        else:
            self.idv["needle"] = None
            self.idv["icon"] = None
        self.idv["value"] = cv.create_text(x, y + r + 16,
                                           text="", font=("Helvetica", 9),
                                           fill="#ffd24a")

    def _wave_pts(self, kind):
        """Coordonnées 0..1 de la forme d'onde 'kind' (0..5)."""
        k = kind % 6
        if k == 0:      # Triangle
            return [(0, 1), (0.5, 0), (1, 1)]
        if k == 1:      # Tri-Saw (triangle dissymétrique)
            return [(0, 0.85), (0.35, 0), (1, 0.85)]
        if k == 2:      # Scie (dent de scie montante)
            return [(0, 0), (0.92, 0.9), (0.92, 0), (1, 0.1)]
        if k == 3:      # Carré
            return [(0, 0), (0.5, 0), (0.5, 1), (1, 1)]
        if k == 4:      # Impulsion 30 %
            return [(0, 0), (0.3, 0), (0.3, 1), (1, 1)]
        return [(0, 0), (0.15, 0), (0.15, 1), (1, 1)]  # 15 %

    def _draw_icon(self, kind):
        cv = self.cv
        x, y = self.cx, self.cy
        w, h = 20, 12
        x0, y0 = x - w / 2, y - h / 2
        pts = []
        for u, v in self._wave_pts(kind):
            pts.extend((x0 + u * w, y0 + v * h))
        self.idv["icon"] = cv.create_line(
            *pts, fill="#ff8c3a", width=2, capstyle="round", joinstyle="round")

    def update(self, val, locked=False):
        val = max(self.lo, min(self.hi, val))
        if self.norm is not None:
            t = self.norm(val)
            t = max(0.0, min(1.0, t))
        else:
            t = (val - self.lo) / (self.hi - self.lo) if self.hi != self.lo else 0.0
            t = max(0.0, min(1.0, t))
        a = self._angle_t(t)
        x, y, r = self.cx, self.cy, self.r
        # Couleur "figé patch" (cyan, tranche sur l'orange/vert) vs normale
        c = "#00e5ff" if locked else (self.accent or "#efe9dc")
        vc = "#00e5ff" if locked else "#ffd24a"
        self.cv.itemconfigure(self.idv["body"], width=2 if locked else 1,
                              outline="#00e5ff" if locked else "#07080a")
        # Étiquette et couronne de la face : elles portent l'accent du potard
        # (FREQ OSC2 bleu / OSC3 orange) ; figées par un patch elles passent au
        # cyan comme le reste de l'indication de verrouillage.
        self.cv.itemconfigure(
            self.idv["label"],
            fill="#00e5ff" if locked else (self.accent or "#d8d8d8"))
        self.cv.itemconfigure(
            self.idv["cap"],
            outline="#00e5ff" if locked else (self.accent or "#0c0e11"))
        if self.wave is not None:
            kind = int(val)
            if self.idv.get("icon") is not None:
                self.cv.delete(self.idv["icon"])
            self._draw_icon(kind)
            self.cv.itemconfigure(self.idv["icon"], fill=c)
            text = self.fmt(kind)
        else:
            bx = x + r * 0.10 * math.cos(a)
            by = y - r * 0.10 * math.sin(a)
            lx = x + r * 0.70 * math.cos(a)
            ly = y - r * 0.70 * math.sin(a)
            self.cv.coords(self.idv["needle"], bx, by, lx, ly)
            self.cv.itemconfigure(self.idv["needle"], fill=c)
            text = self.fmt(val) if callable(self.fmt) else self.fmt.format(val)
        self.cv.itemconfigure(self.idv["value"], text=text, fill=vc)


class SwitchOn:
    """Bascule deux positions — un seul rond, allumé ou éteint."""

    def __init__(self, cv, x, y, label, on_color="#3bff5a", radius=10,
                 states=None, blink_txt="PATCH", color=None, orient="h"):
        self.cv = cv
        self.cx, self.cy = x, y
        self.label = label
        self.on_color = on_color
        self.r = radius
        self.states = states
        self.blink_txt = blink_txt
        self.color = color
        self.orient = orient
        self.idv = {}
        self.blink = False
        self.on = False
        self._phase = True
        self.blink_period = 0.25   # demi-période du clignotement (s)
        self._draw()

    def _draw(self):
        cv, x, y = self.cv, self.cx, self.cy
        self.idv["label"] = cv.create_text(
            x, y - 2, text=self.label, font=("Helvetica", 8, "bold"),
            fill="#d8d8d8")
        cv.create_oval(x - 9, y + 9, x + 9, y + 27, fill="#0a0b0d", outline="")
        self.idv["btn"] = cv.create_oval(x - 7, y + 11, x + 7, y + 25,
                                        fill="#1b1f25", outline="#3a4048",
                                        width=1)
        self.idv["txt"] = cv.create_text(x, y + 38, text="OFF",
                                         font=("Helvetica", 8),
                                         fill="#9aa3ad")

    def update(self, raw, locked=False):
        self.blink = (raw >= 2)
        # modeEnc==3 (VCO2 DELAY) clignote plus vite que ==2 (VCO2 REVERB /
        # VCO1 PATCH), pour distinguer reverb et delay à l'écran.
        self.blink_period = 0.10 if raw == 3 else 0.25
        on = bool(raw)
        self.on = on
        self._set(self._phase if self.blink else on)
        if self.states:
            txt = self.blink_txt if self.blink else (self.states[1] if on else self.states[0])
        else:
            txt = self.blink_txt if self.blink else ("ON" if on else "OFF")
        self.cv.itemconfigure(self.idv["txt"], text=txt,
                              fill="#00e5ff" if locked else "#9aa3ad")

    def _set(self, on):
        self.cv.itemconfigure(self.idv["btn"],
                              fill=self.on_color if on else "#1b1f25")

    def _lamp(self, on):
        pass

    def blink_tick(self, now):
        if self.blink:
            self._phase = int(now / self.blink_period) % 2 == 0
            self._set(self._phase)


class Wheel:
    """Molette verticale (pitch / mod).

    Sur le Model D les molettes passent dans une fente de la plaque : on
    redessine donc un logement encastré (champ + ouverture noire), des rails
    de graduation de part et d'autre, et un capuchon mobile à index coloré —
    au lieu du simple pavé sur le panneau qu'on avait avant.
    """

    OUTER = 26   # demi-largeur de la plaque de logement
    INNER = 18   # demi-largeur de la fente (8 px de rail de chaque côté)
    TH = 22      # hauteur du capuchon mobile

    def __init__(self, cv, x, y, w, h, label, lo=0.0, hi=1.0,
                 color="#ffd24a", fmt="{:.0%}", pad=8, detent=False):
        self.cv = cv
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.lo, self.hi = lo, hi
        self.fmt = fmt
        self.color = color
        self.pad = pad
        self.thh = self.TH
        self._parts = []          # éléments mobiles (coords absolues + décalage)

        # 1) ombre portée puis plaque de logement encastrée
        cv.create_rectangle(x - self.OUTER + 3, y + 4,
                            x + self.OUTER + 3, y + h + 4,
                            fill="#0a0b0c", outline="")
        cv.create_rectangle(x - self.OUTER, y, x + self.OUTER, y + h,
                            fill="#22262c", outline="#07080a", width=1)
        # 2) fente noire + rails de graduation sur les deux joues
        cv.create_rectangle(x - self.INNER, y + 3, x + self.INNER, y + h - 3,
                            fill="#050607", outline="#14171b", width=1)
        n = 5
        for i in range(n):
            ty = y + 3 + i * (h - 6) / (n - 1)
            mid = (i == (n - 1) // 2)
            # repère central = point de repos (molette de pitch rappelée au
            # centre par un ressort sur l'instrument d'origine)
            col = "#efe9dc" if (mid and detent) else "#7f868f"
            lw = 2 if (mid and detent) else 1
            cv.create_line(x - self.OUTER + 1, ty, x - self.INNER, ty,
                           fill=col, width=lw)
            cv.create_line(x + self.INNER, ty, x + self.OUTER - 1, ty,
                           fill=col, width=lw)
        # 3) étiquette teintée à la couleur de la molette
        cv.create_text(x, y - 11, text=label, font=("Helvetica", 9, "bold"),
                       fill=color)
        # 4) capuchon mobile : corps, face, nervures puis index coloré
        self._top0 = y + pad + (h - self.TH - 2 * pad)   # position pour lo
        self.thumb = self._rect(x - self.INNER + 1, self._top0,
                                x + self.INNER - 1, self._top0 + self.TH,
                                "#171a1e", "#07080a", 1)
        self._rect(x - self.INNER + 3, self._top0 + 2,
                   x + self.INNER - 3, self._top0 + self.TH - 2,
                   "#272c33", "", 0)
        for dy in (6, self.TH - 6):
            self._line(x - self.INNER + 5, self._top0 + dy,
                       x + self.INNER - 5, self._top0 + dy, "#41474f", 1)
        self._line(x - self.INNER + 3, self._top0 + self.TH / 2,
                   x + self.INNER - 3, self._top0 + self.TH / 2, color, 2)
        # 5) valeur sous la fente
        self.val = cv.create_text(x, y + h + 16, text="",
                                  font=("Helvetica", 9, "bold"),
                                  fill="#d8d8d8")
        self.update(lo)

    def _rect(self, x1, y1, x2, y2, fill, outline, width):
        it = self.cv.create_rectangle(x1, y1, x2, y2, fill=fill,
                                      outline=outline, width=width)
        self._parts.append((it, x1, y1 - self._top0, x2, y2 - self._top0))
        return it

    def _line(self, x1, y1, x2, y2, fill, width):
        it = self.cv.create_line(x1, y1, x2, y2, fill=fill, width=width)
        self._parts.append((it, x1, y1 - self._top0, x2, y2 - self._top0))
        return it

    def update(self, v):
        lo, hi = self.lo, self.hi
        v = max(lo, min(hi, v))
        t = (v - lo) / (hi - lo) if hi != lo else 0.0
        t = max(0.0, min(1.0, t))
        span = self.h - self.thh - 2 * self.pad
        top = self.y + self.pad + (1 - t) * span
        for it, x1, dy1, x2, dy2 in self._parts:
            self.cv.coords(it, x1, top + dy1, x2, top + dy2)
        text = self.fmt(v) if callable(self.fmt) else self.fmt.format(v)
        self.cv.itemconfigure(self.val, text=text)


class Keyboard:
    """Clavier — les touches blanches/noires, la note jouée s'enfonce."""

    WHITE_PC = {0, 2, 4, 5, 7, 9, 11}

    def __init__(self, cv, x, y, w, h, midi0=36, midi1=84, note_cb=None):
        self.cv = cv
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.midi0, self.midi1 = midi0, midi1
        self.note_cb = note_cb
        self.pressed = None
        self.keys = {}
        self.active = None
        self._draw()
        self._bind_mouse()

    def _bind_mouse(self):
        # Binds globaux au canvas : robustes pendant le glissé (B1-Motion),
        # le joueur repère la note par coordonnées (_key_from_xy) et non par
        # le tag "current" de Tk qui peut être périmé pendant le déplacement.
        self.cv.bind("<ButtonPress-1>", self._mouse_down)
        self.cv.bind("<B1-Motion>", self._mouse_move)
        # Relâchement global (même après avoir glissé hors du clavier)
        self.cv.bind("<ButtonRelease-1>", self._mouse_up)

    def _key_from_xy(self, x, y):
        """N° MIDI de la touche sous (x, y) en coordonnées canvas, None sinon."""
        if not (self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h):
            return None
        # Zone haute : les touches noires passent devant les blanches
        if y < self.y + self.h * 0.62:
            for m, px, bw in self._noirs:
                if px <= x <= px + bw:
                    return m
        # Sinon : touche blanche courante d'après la colonne
        wi = int((x - self.x) // self._ww)
        if 0 <= wi < len(self._blancs):
            return self._blancs[wi]
        return None

    def _mouse_down(self, event):
        m = self._key_from_xy(event.x, event.y)
        if m is None:
            return
        self.pressed = m
        self._set_key(m, True)

    def _mouse_move(self, event):
        m = self._key_from_xy(event.x, event.y)
        if m is None or m == self.pressed:
            return
        self.pressed = m
        self._set_key(m, True)

    def _mouse_up(self, event):
        if self.pressed is None:
            return
        m = self.pressed
        self.pressed = None
        self._set_key(m, False)

    def _set_key(self, m, on):
        """Monophonique : dragger une autre touche = nouvelle note sans OFF."""
        self.set_note(m, on)
        if self.note_cb:
            self.note_cb(m, on)

    def _draw(self):
        cv = self.cv
        whites = [m for m in range(self.midi0, self.midi1 + 1)
                  if m % 12 in self.WHITE_PC]
        ww = self.w / len(whites)
        bw = ww * 0.62
        black_h = self.h * 0.62
        xs = {}
        k = 0
        self._blancs = whites
        self._ww = ww
        self._noirs = []
        for m in range(self.midi0, self.midi1 + 1):
            if m % 12 in self.WHITE_PC:
                x = self.x + k * ww
                xs[m] = x
                self.keys[m] = cv.create_rectangle(
                    x, self.y, x + ww + 1, self.y + self.h,
                    fill="#e8e8e8", outline="#4a525b",
                    tags=("key", f"key{m}"))
                k += 1
            else:
                xl = xs[m - 1]
                px = xl + ww - bw / 2
                self._noirs.append((m, px, bw))
                self.keys[m] = cv.create_rectangle(
                    px, self.y, px + bw, self.y + black_h,
                    fill="#20242a", outline="#000",
                    tags=("key", f"key{m}"))

    def _default_fill(self, midi):
        return "#e8e8e8" if midi % 12 in self.WHITE_PC else "#20242a"

    def set_note(self, midi, on):
        # Les notes du clavier maître peuvent sortir de la portée affichée
        # (36..84) : on ne touche jamais self.keys[note] sans vérifier.
        if on:
            if self.active is not None and self.active != midi:
                prev = self.active
                if prev in self.keys:
                    self.cv.itemconfigure(self.keys[prev],
                                          fill=self._default_fill(prev))
            self.active = midi
            if self.active in self.keys:
                self.cv.itemconfigure(self.keys[self.active], fill="#ffd24a")
        else:
            if self.active is not None and self.active == midi:
                if self.active in self.keys:
                    self.cv.itemconfigure(
                        self.keys[self.active],
                        fill=self._default_fill(self.active))
                self.active = None

