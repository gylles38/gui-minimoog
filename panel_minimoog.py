#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Panneau Minimoog Model D — affichage graphique temps réel.

Lit les trames CSV émises par minimoog.ino (préfixe 'P') sur le port série
et dessine un panneau façon Minimoog Model D.

Format de trame (une ligne, 48 champs + masque) :
P,vol1,vol2,vol3,volN,freq2,freq3,cut,res,amt,fAtk,fDec,fSus,lAtk,lDec,lSus,
 glide,modmix, s0..s12, w1,r1,m1,w2,r2,m2,w3,r3,m3, note,midiOn,pitchBend,modWheel, patchNom, lockMask, revType
m1 : 0=waveform, 1=range, 2=patch (LED VCO1 clignote)
revType : 0 ROOM, 1 HALL, 2 PLATE, 3 SPRING (choisi par ENC2 mode reverb)
lockMask : hex "lo.hi" — bits à 1 = contrôle figé sur la valeur du patch
          (37 bits : 0-12 switchs, 13-29 pots, 30-35 wave/range, 36 EXT VOL)
 (rétention latch, affiché en ambre)

Lignes 'M' (moniteur MIDI, émises par le firmware en mode MIDI, une par
message reçu) : "M,<statusHEX>,<d0>,<d1>". Affiche les 2 dernières en haut,
bouton MON pour couper l'affichage (action GUI uniquement).

Jouer au clavier à la souris : cliquer / glisser sur les touches envoie les
commandes série N<note> (note ON) et X (note OFF) au firmware (fonctionne en
mode SÉRIE seulement ; en mode MIDI la RX est coupée, donc pas de son).

Patches : banque définie dans patches.json (source de vérité sur le PC).
La GUI pousse toute la banque au firmware au démarrage (commandes B!/B) —
ENC1, L<nom> et CC122 fonctionnent alors normalement, sans reflash.
Bouton SAVE : capture l'état courant et l'ajoute à patches.json.
Bouton RESET : envoie la commande série 'R' (retour aux valeurs d'usine,
déverrouille les potards et sort du mode patch). En mode MIDI (RX série
coupée), il déclenche un reset matériel DTR/RTS puis repousse la banque.

Usage :
    python3 panel_minimoog.py /dev/ttyUSB0          (port explicite)
    python3 panel_minimoog.py --demo                (données simulées)
    python3 panel_minimoog.py -l                    (liste des ports)
"""

import argparse
import json
import math
import os
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

try:
    import serial
except ImportError:
    serial = None

WAVES = ["Tri", "Tri-Saw", "Scie", "Carre", "Imp30", "Imp15"]
RANGES = ["32'", "16'", "8'", "4'", "2'", "Lo"]

# Échelle appliquée côté firmware à la molette de modulation (CC1 ÷2, cf.
# MOD_WHEEL_SCALE dans minimoog.ino). La GUI compense pour afficher la position
# réelle de la molette du clavier maître (100% = pleine).
MOD_WHEEL_NORM = 0.5

# Masque de verrouillage (rétention latch) envoyé par le firmware en fin de
# trame : bits 0-12 switchs (ordre SWMAP), 13-29 pots (ordre LOCK_POT_KEYS),
# 30-35 wave/range des 3 VCO. Bit à 1 = contrôle figé sur la valeur du patch.
LOCK_POT_KEYS = ["vol1", "vol2", "vol3", "volN", "freq2", "freq3",
                 "cut", "res", "amt", "fAtk", "fDec", "fSus",
                 "lAtk", "lDec", "lSus", "glide", "modmix"]
LOCK_WAVE_RANGE = {"wave0": 30, "range0": 31,
                   "wave1": 32, "range1": 33,
                   "wave2": 34, "range2": 35}
# Le volume de l'entrée externe (pot J49) n'appartient pas à l'ordre de la trame
# (il est émis après revType), donc il ne peut pas entrer dans LOCK_POT_KEYS sans
# décaler tous les bits. Le firmware lui réserve son propre bit.
LOCK_EXT_BIT = 36
# Idem pour le niveau de reverb (pot dédié J50) : il est émis dans le champ
# `reverb` de la trame, hors LOCK_POT_KEYS, donc il a son propre bit.
LOCK_REVERB_BIT = 37

PATCHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "patches.json")

# Inverse du mapping firmware des temps d'enveloppe (0.01 s * 1000^rotation) :
# transforme une durée en secondes -> fraction de rotation 0..1 de l'aiguille.
LOG_1000 = math.log(1000.0)


def norm_env_time(t):
    t = max(t, 0.01)
    return math.log(t / 0.01) / LOG_1000


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
                 wave=None, norm=None):
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
            fill="#d8d8d8")
        # Graduations (petites barres) autour du cadran, comme le Moog
        n = max(5, int(self.cw / 22.5) + 1)
        for i in range(n):
            t = i / (n - 1)
            a = self._angle(self.lo + t * (self.hi - self.lo))
            x1 = x + math.cos(a) * (r + 6)
            y1 = y - math.sin(a) * (r + 6)
            x2 = x + math.cos(a) * (r + 10)
            y2 = y - math.sin(a) * (r + 10)
            cv.create_line(x1, y1, x2, y2, fill="#3a4048", width=1)
        self.idv["body"] = cv.create_oval(x - r, y - r, x + r, y + r,
                                          fill="#1e2329", outline="#4a525b",
                                          width=2)
        self.idv["knob"] = cv.create_oval(x - r * 0.3, y - r * 0.3,
                                          x + r * 0.3, y + r * 0.3,
                                          fill="#3a4048", outline="#6b747e")
        if self.wave is None:
            self.idv["needle"] = cv.create_line(
                x, y, x + r * 0.75 * math.cos(self._angle(0.0)),
                y - r * 0.75 * math.sin(self._angle(0.0)),
                fill="#ff8c3a", width=3)
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
        c = "#00e5ff" if locked else "#ff8c3a"
        vc = "#00e5ff" if locked else "#ffd24a"
        self.cv.itemconfigure(self.idv["body"], width=2 if locked else 2,
                              outline="#00e5ff" if locked else "#4a525b")
        if self.wave is not None:
            kind = int(val)
            if self.idv.get("icon") is not None:
                self.cv.delete(self.idv["icon"])
            self._draw_icon(kind)
            self.cv.itemconfigure(self.idv["icon"], fill=c)
            text = self.fmt(kind)
        else:
            lx = x + r * 0.75 * math.cos(a)
            ly = y - r * 0.75 * math.sin(a)
            self.cv.coords(self.idv["needle"], x, y, lx, ly)
            self.cv.itemconfigure(self.idv["needle"], fill=c)
            text = self.fmt(val) if callable(self.fmt) else self.fmt.format(val)
        self.cv.itemconfigure(self.idv["value"], text=text, fill=vc)


class SwitchOn:
    """Switch deux positions — LED + texte."""

    def __init__(self, cv, x, y, label, on_color="#3bff5a", radius=10, states=None,
                 blink_txt="PATCH"):
        self.cv = cv
        self.cx, self.cy = x, y
        self.label = label
        self.on_color = on_color
        self.r = radius
        self.states = states  # (texte OFF, texte ON) pour les sélecteurs 2 positions
        self.blink_txt = blink_txt  # texte affiché quand raw==2 (led clignote)
        self.idv = {}
        self.blink = False
        self._draw()

    def _draw(self):
        cv, x, y = self.cv, self.cx, self.cy
        self.idv["label"] = cv.create_text(
            x, y, text=self.label, font=("Helvetica", 8, "bold"),
            fill="#d8d8d8")
        r = self.r
        self.idv["led"] = cv.create_oval(x - r, y + 16 - r, x + r, y + 16 + r,
                                         fill="#3a4048", outline="#4a525b")
        self.idv["txt"] = cv.create_text(x, y + 16 + r + 12,
                                         text="OFF", font=("Helvetica", 8),
                                         fill="#9aa3ad")

    def update(self, raw, locked=False):
        # raw : 0/1/2 — la valeur 2 (mode patch ENC1) fait clignoter la LED
        # locked (bout latch) : le switch est figé sur la position du patch
        self.blink = (raw == 2)
        on = bool(raw)
        self._set(on)
        if self.states:
            txt = self.blink_txt if self.blink else (self.states[1] if on else self.states[0])
        else:
            txt = self.blink_txt if self.blink else ("ON" if on else "OFF")
        self.cv.itemconfigure(self.idv["txt"], text=txt,
                              fill="#00e5ff" if locked else "#9aa3ad")
        self.cv.itemconfigure(self.idv["led"],
                              outline="#00e5ff" if locked else "#4a525b")

    def _set(self, on):
        self.cv.itemconfigure(self.idv["led"],
                              fill=self.on_color if on else "#3a4048")

    def blink_tick(self, phase_on):
        """Clignotement local (le firmware ne l'envoie pas assez vite)."""
        if self.blink:
            self._set(phase_on)


class Wheel:
    """Molette verticale (pitch / mod) — aiguille + valeur en dessous."""

    def __init__(self, cv, x, y, w, h, label, lo=0.0, hi=1.0,
                 color="#ffd24a", fmt="{:.0%}", pad=8):
        self.cv = cv
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.lo, self.hi = lo, hi
        self.fmt = fmt
        self.pad = pad
        self.thw = w - 8
        self.thh = 4
        cv.create_text(x, y - 12, text=label, font=("Helvetica", 9, "bold"),
                       fill="#d8d8d8")
        cv.create_rectangle(x - w / 2, y, x + w / 2, y + h, fill="#1b1f25",
                            outline="#2f353c")
        cv.create_line(x, y + pad, x, y + h - pad, fill="#2f353c")
        self.thumb = cv.create_rectangle(x - self.thw / 2, y,
                                         x + self.thw / 2, y + self.thh,
                                         fill=color, outline="#4a525b")
        self.val = cv.create_text(x, y + h + 16, text="",
                                  font=("Helvetica", 9, "bold"),
                                  fill="#d8d8d8")
        self.update(lo)

    def update(self, v):
        lo, hi = self.lo, self.hi
        v = max(lo, min(hi, v))
        t = (v - lo) / (hi - lo)
        span = self.h - self.thh - 2 * self.pad
        top = self.y + self.pad + (1 - t) * span
        self.cv.coords(self.thumb, self.x - self.thw / 2, top,
                       self.x + self.thw / 2, top + self.thh)
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


class App:
    W, H = 1500, 900

    # Référence du panneau réel :
    # SWITCHES (idx trame 18..30) :
    # 0 Mod_OSC, 1 Ctrl_OSC3, 2 Mix_OSC1, 3 Mix_OSC2, 4 Mix_OSC3,
    # 5 Mix_NOISE, 6 Type_NOISE, 7 Output, 8 Glide, 9 Decay,
    # 10 Kbd_Ctrl2, 11 Kbd_Ctrl1, 12 Filt_Mod
    SWMAP = [
        (0, "modOsc"), (1, "ctrlOsc3"), (2, "mixOn1"), (3, "mixOn2"),
        (4, "mixOn3"), (5, "mixOnN"), (6, "typeNoise"), (7, "outOn"),
        (8, "glideOn"), (9, "decay"), (10, "kbd2"), (11, "kbd1"),
        (12, "filtMod"),
    ]

    def __init__(self, port=None, demo=False):
        self.port = port
        self.demo = demo
        self.ser = None

        self.root = tk.Tk()
        self.root.title("Minimoog Model D — Panneau temps réel")
        self.root.configure(bg="#14171c")
        self.root.geometry(f"{self.W}x{self.H}")
        self.root.minsize(self.W, self.H)
        self.cv = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg="#14171c", highlightthickness=0)
        self.cv.pack(fill="both")

        self.knobs = {}
        self.switches = {}
        self.top = {}
        self._bank_pushed = True
        self._bank_sync = -1
        self.patches = self._load_patches()
        self._tips = []
        self._tip_last = None
        self.tt = ToolTip()
        self._mon_on = True          # moniteur MIDI actif au lancement
        self._mon_q = []             # max 2 lignes, q[0] = plus récente
        self._build_panel()
        self._build_patch_widgets()
        self.cv.bind("<Enter>", self._tip_motion)
        self.cv.bind("<Motion>", self._tip_motion)
        self.cv.bind("<Leave>", lambda e: self._tip_clear())

        if serial and not demo and self.port:
            try:
                self.ser = serial.Serial(self.port, 115200, timeout=0.05)
                # Séquence esptool "reset to run" : l'ouverture du port togglue
                # DTR/RTS, ce qui peut laisser l'ESP32 en reset ou dans le
                # bootloader ROM (plus de trames P → panneau figé au 1er
                # lancement après reboot). On force un boot normal déterministe.
                self.ser.dtr = False          # IO0 = HIGH (boot appli)
                time.sleep(0.1)
                self.ser.rts = True           # EN = LOW (reset asserté)
                time.sleep(0.1)
                self.ser.rts = False          # EN = HIGH (boot)
                time.sleep(0.2)
                # Purge le texte de boot résiduel pour partir propre.
                self.ser.reset_input_buffer()
                # Push IMMÉDIAT (t=500 ms) : c'est lui qui est reçu pendant la
                # fenêtre de boot ~3 s et qui décide le firmware en mode SÉRIE
                # (sinon il bascule MIDI, RX coupée, et les B! n'arrivent plus).
                # setRxBufferSize(4096) côté firmware absorbe le déluge.
                self._bank_pushed = False
                self.root.after(500, self._push_bank)
            except Exception as e:
                self.cv.itemconfigure(self.top["port"],
                                      text=f"Port {self.port}: ERREUR {e}")

        # premier affichage
        self.root.after(30, self._tick)
        self.root.mainloop()

    # ------------------------------------------------------------- structure
    def _box(self, x, y, w, h, title=None):
        self.cv.create_rectangle(x, y, x + w, y + h, fill="#1b1f25",
                                 outline="#2f353c", width=1)
        if title:
            self.cv.create_text(x + 14, y + 16, text=title,
                                font=("Helvetica", 10, "bold"),
                                fill="#ffd24a", anchor="w")

    def knob(self, key, x, y, label, lo=0.0, hi=1.0, fmt="{:.2f}", wave=None,
             norm=None, help=None):
        self.knobs[key] = Knob(self.cv, x, y, label, lo=lo, hi=hi, fmt=fmt,
                               wave=wave, norm=norm)
        if help:
            self._tips.append((x - 38, y - 50, x + 38, y + 46, help))

    def switch(self, key, x, y, label, states=None, blink_txt="PATCH",
               help=None):
        self.switches[key] = SwitchOn(self.cv, x, y, label, states=states,
                                      blink_txt=blink_txt)
        if help:
            self._tips.append((x - 32, y - 14, x + 32, y + 54, help))

    # ------------------------------------------------------------- tooltips
    def _tip_motion(self, event):
        """Affiche la bulle du contrôle sous le pointeur (test du canvas)."""
        cur = None
        for (x1, y1, x2, y2, text) in self._tips:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cur = text
                break
        if cur is not self._tip_last:
            self._tip_last = cur
            if cur:
                self.tt.show(cur, event.x_root, event.y_root)
            else:
                self.tt.hide()

    def _tip_clear(self):
        self._tip_last = None
        self.tt.hide()

    def _btn_tip(self, widget, text):
        """Attache une bulle à un vrai widget Tk (bouton, liste...)."""
        if widget is None:
            return
        widget.bind("<Enter>",
                    lambda e: self.tt.show(text, e.x_root, e.y_root))
        widget.bind("<Motion>",
                    lambda e: self.tt.show(text, e.x_root, e.y_root))
        widget.bind("<Leave>", lambda e: self.tt.hide())

    # ------------------------------------------------------------- patches
    def _load_patches(self):
        """Charge la banque depuis patches.json (format du firmware B)."""
        try:
            with open(PATCHES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("patches", [])
        except Exception:
            return []

    def _save_patches(self):
        with open(PATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump({"patches": self.patches}, f, ensure_ascii=False, indent=2)

    def _patch_to_line(self, p):
        """Convertit un dict patch (JSON) en ligne CSV pour la commande B du
        firmware. Ordre : nom,w1,r1,w2,r2,w3,r3,v1,v2,v3,vN,fr2,fr3,cut,res,
        amt,fAtk,fDec,fSus,lAtk,lDec,lSus,glide,modMix,reverb,revType,s0..s12,
        extVol"""
        nom = p.get("nom", "PATCH").upper().replace(",", "_")
        w, r = p["w"], p["r"]
        v = p["v"]
        sw = p.get("sw", [0] * 13)
        f = ["{:.3f}".format(x) for x in [
            v[0], v[1], v[2], v[3],
            p.get("freq2", 0.5), p.get("freq3", 0.5),
            p.get("cut", 0), p.get("res", 0), p.get("amt", 0),
            p.get("fAtk", 0), p.get("fDec", 0), p.get("fSus", 1),
            p.get("lAtk", 0), p.get("lDec", 0), p.get("lSus", 1),
            p.get("glide", 0), p.get("modMix", 0), p.get("reverb", 0.0)]]
        s = [str(int(bool(x))) for x in sw]
        # extVol en DERNIER champ (optionnel côté firmware) : la position du
        # pot J49, 0..1. C'est ce que le knob "EXT VOL" lit dans la trame P.
        ext = max(0.0, min(1.0, float(p.get("extVol", 0.0))))
        return "B " + nom + "," + \
            ",".join(str(x) for x in [w[0], r[0], w[1], r[1], w[2], r[2]]) + \
            "," + ",".join(f) + "," + \
            str(int(p.get("revtype", 0))) + "," + ",".join(s) + \
            ",{:.3f}".format(ext)

    def _push_bank(self):
        """Envoie B! (vide banque) puis chaque patch au firmware."""
        if getattr(self, "_bank_pushed", True):
            return
        if not (self.ser and self.ser.is_open):
            return
        try:
            self.ser.write(b"B!\n")
            self.ser.flush()
            self._bank_pushed = True
            self.root.after(60, self._send_patches, 0)
        except Exception:
            pass

    def _send_patches(self, idx):
        if not (self.ser and self.ser.is_open):
            return
        if idx < len(self.patches):
            try:
                self.ser.write(self._patch_to_line(self.patches[idx]).encode() + b"\n")
                self.ser.flush()
                self.root.after(80, self._send_patches, idx + 1)
            except Exception:
                pass
        else:
            try:
                self.ser.write(b"B?\n")
                self.ser.flush()
            except Exception:
                pass
            self.cv.itemconfigure(
                self.top["patch"],
                text=f"Patch: push demandé")

    def _patch_from_current(self, nom):
        """Construit un patch depuis la dernière trame GUI (état courant)."""
        d = getattr(self, "_last", None)
        if d is None:
            return None
        sw = list(d.get("sw", [0] * 13))
        return {
            "nom": nom,
            "w": [d["wave0"], d["wave1"], d["wave2"]],
            "r": [d["range0"], d["range1"], d["range2"]],
            "v": [d["vol1"] * 0.33, d["vol2"] * 0.33,
                  d["vol3"] * 0.33, d["volN"] * 0.33],
            "freq2": (d["freq2"] + 7.0) / 14.0,
            "freq3": (d["freq3"] + 7.0) / 14.0,
            "cut": d["cut"], "res": d["res"], "amt": d["amt"],
            "fAtk": norm_env_time(d["fAtk"]),
            "fDec": norm_env_time(d["fDec"]),
            "fSus": d["fSus"],
            "lAtk": norm_env_time(d["lAtk"]),
            "lDec": norm_env_time(d["lDec"]),
            "lSus": d["lSus"],
            "glide": d["glide"],
            "modMix": d["modmix"],
            "reverb": d.get("reverb", 0.0),
            "revtype": d.get("revtype", 0),
            "sw": sw,
            # Position 0..1 du pot J49, telle qu'émise dans la trame P :
            # sans ce champ, « sauver l'état courant » perdrait le feedback.
            "extVol": max(0.0, min(1.0, d.get("ext", 0.0))),
        }

    def _save_current(self):
        """Capture l'état courant comme nouveau patch et pousse la banque."""
        nom = simpledialog.askstring("Sauvegarder le patch",
                                     "Nom du patch :",
                                     parent=self.root)
        if not nom:
            return
        p = self._patch_from_current(nom.strip().upper())
        if p is None:
            messagebox.showwarning("Sauvegarde",
                                   "Aucune trame reçue du synthé pour l'instant.")
            return
        # remplace par le même nom, sinon ajoute
        self.patches = [x for x in self.patches if x.get("nom") != p["nom"]]
        self.patches.append(p)
        self._save_patches()
        self._refresh_patch_list()
        self._bank_pushed = False
        self._push_bank()
        messagebox.showinfo("Sauvegarde", f"Patch « {p['nom']} » sauvegardé.")

    def _delete_patch(self):
        """Supprime le patch actif (sélection du combo) après confirmation."""
        sel = self.patch_combo.current()
        if sel < 0 or sel >= len(self.patches):
            return
        p = self.patches[sel]
        nom = p.get("nom", "?")
        if not messagebox.askyesno(
                "Supprimer le patch",
                f"Supprimer le patch « {nom} » de la banque ?",
                parent=self.root):
            return
        del self.patches[sel]
        self._save_patches()
        self._refresh_patch_list()
        self._bank_pushed = False
        self._push_bank()
        messagebox.showinfo("Suppression",
                            f"Patch « {nom} » supprimé.", parent=self.root)

    def _reset_controls(self):
        """Reset des contrôles aux valeurs d'usine :
        - mode SÉRIE : envoie la commande 'R' (valeurs neutres + potards libres) ;
        - mode MIDI  : RX série USB coupée → la commande ne part pas, on fait un
          reset matériel DTR/RTS : l'ESP redémarre aux valeurs d'usine puis la
          GUI repousse la banque (repasse en mode série)."""
        if not (self.ser and self.ser.is_open):
            print("[GUI] Reset : port série fermé")
            return
        if getattr(self, "_midi_estActive", False):
            self._auto_serial_recovery()
            return
        try:
            self.ser.write(b"R\n")
            self.ser.flush()
            self.cv.itemconfigure(self.top["patch"], text="Patch: — (reset)")
        except Exception:
            print("[GUI] Échec d'envoi du reset")

    def _auto_serial_recovery(self):
        """RX série muette (ESP booté en mode MIDI : GPIO3 pris par Serial1,
        toutes les commandes L/B partent dans le vide, seules les trames P
        sortent) → reset ESP via DTR/RTS et re-push de la banque pour revenir
        en mode série. Inoffensif si le reset n'est pas câblé (rattrapé au
        prochain boot manuel avec la GUI ouverte)."""
        if not (self.ser and self.ser.is_open):
            return
        now = time.time()
        if now - getattr(self, "_autorec_t", 0) < 10.0:
            return
        self._autorec_t = now
        print("[GUI] RX série muette → reset ESP + re-push banque (mode série)")
        self.cv.itemconfigure(self.top["patch"], text="Patch: reset → série")
        try:
            self.ser.dtr = False          # IO0 = HIGH (boot appli)
            time.sleep(0.1)
            self.ser.rts = True           # EN = LOW (reset asserté)
            time.sleep(0.1)
            self.ser.rts = False          # EN = HIGH (boot)
            time.sleep(0.2)
            self.ser.reset_input_buffer()
            self._probe_miss = 0
            self._midi_estActive = False
            self._midi_manual = False
            self._bank_pushed = False
            self.midi_btn.configure(text="MIDI", bg="#1b5e20")
            self.root.after(500, self._push_bank)
        except Exception:
            print("[GUI] Échec du reset série")
            pass

    def _refresh_patch_list(self):
        try:
            names = [p.get("nom", f"PATCH{i+1}") for i, p in enumerate(self.patches)]
            self.patch_combo["values"] = names
            if names:
                self.patch_combo.current(0)
        except Exception:
            pass

    def _build_patch_widgets(self):
        try:
            from tkinter import ttk
        except ImportError:
            ttk = None
        if ttk is None:
            return
        self.patch_combo = ttk.Combobox(
            self.root, state="readonly", width=12, font=("Helvetica", 9),
            values=[p.get("nom", "?") for p in self.patches])
        # Pas de chargement au clic : la liste est un simple sélecteur pour
        # SAVE/DELETE, le rappel se fait par ENC1 (mode patch) sur le synthé.
        self.cv.create_window(865, 72, window=self.patch_combo, anchor="center")
        self._btn_tip(self.patch_combo, "Liste des patches de la banque "
                      "(patches.json). Sélectionne le patch pour SAVE/DELETE ; "
                      "le rappel sur le synthé se fait par le poussoir VCO1 "
                      "(mode PATCH).")

        self.save_btn = tk.Button(
            self.root, text="SAVE", font=("Helvetica", 10, "bold"),
            bg="#2e7d32", fg="#ffffff", activebackground="#43a047",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=8, pady=2, cursor="hand2", command=self._save_current)
        self.cv.create_window(960, 72, window=self.save_btn, anchor="center")
        self._btn_tip(self.save_btn, "SAVE : enregistre l'état actuel du panneau "
                      "comme nouveau patch dans patches.json, puis repousse la "
                      "banque au synthé (le rappel se fera par VCO1 / ENC1).")

        self.delete_btn = tk.Button(
            self.root, text="DELETE", font=("Helvetica", 10, "bold"),
            bg="#c0392b", fg="#ffffff", activebackground="#ff6b5e",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=8, pady=2, cursor="hand2", command=self._delete_patch)
        self.cv.create_window(1055, 72, window=self.delete_btn, anchor="center")
        self._btn_tip(self.delete_btn, "DELETE : supprime le patch sélectionné "
                      "de la banque (patches.json) après confirmation, puis "
                      "repousse la banque au synthé.")

        self.reset_btn = tk.Button(
            self.root, text="RESET", font=("Helvetica", 10, "bold"),
            bg="#0277bd", fg="#ffffff", activebackground="#039be5",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=8, pady=2, cursor="hand2", command=self._reset_controls)
        self.cv.create_window(1150, 72, window=self.reset_btn, anchor="center")
        self._btn_tip(self.reset_btn, "RESET : retour aux réglages d'usine "
                      "(commande R — valeurs neutres, potards déverrouillés, "
                      "sortie du mode patch). En mode MIDI (RX coupée) : reset "
                      "matériel de l'ESP puis re-push de la banque (repassage "
                      "en série).")

    def _build_panel(self):
        cv = self.cv
        self._box(30, 30, 1440, 76, "MINIMOOG MODEL D — état temps réel")
        self._box(30, 120, 310, 520, "MOD / GLIDE / OUT")
        self._box(365, 120, 420, 520, "OSCILLATOR BANK")
        self._box(805, 120, 310, 520, "MIXER")
        self._box(1135, 120, 335, 300, "FILTER")
        self._box(1135, 440, 335, 200, "LOUDNESS")
        self._box(30, 660, 1440, 185)

        self.top["port"] = cv.create_text(
            45, 72, text=f"Port: {self.port or '—'}", anchor="w",
            font=("Courier", 13, "bold"), fill="#ffd24a")
        self.top["fps"] = cv.create_text(
            300, 72, text="FPS: 0", anchor="w",
            font=("Courier", 13, "bold"), fill="#ffd24a")
        self.top["note"] = cv.create_text(
            405, 72, text="Note: —", anchor="w",
            font=("Courier", 13, "bold"), fill="#ffd24a")
        self.top["patch"] = cv.create_text(
            600, 72, text="Patch: —", anchor="w",
            font=("Courier", 13, "bold"), fill="#ffd24a")

        # --- Moniteur MIDI (lignes 'M,' émises par le firmware en mode MIDI)
        # Deux lignes en petit monospace dans la bande du haut ; affiché
        # uniquement quand le bouton MON est actif (désactivable via la GUI).
        self.top["mon0"] = cv.create_text(
            345, 92, text="MIDI MON — en attente de messages…", anchor="w",
            font=("Courier", 8, "bold"), fill="#7fb3ff")
        self.top["mon1"] = cv.create_text(
            345, 103, text="", anchor="w",
            font=("Courier", 8, "bold"), fill="#5a6470")

        # --- Bouton PANIC : réinitialise l'état MIDI du synthé (commande série 'P')
        self.panic_btn = tk.Button(
            self.root, text="PANIC", font=("Helvetica", 10, "bold"),
            bg="#c0392b", fg="#ffffff", activebackground="#ff6b5e",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=16, pady=3, cursor="hand2", command=self._panic)
        cv.create_window(1340, 72, window=self.panic_btn, anchor="center")

        # --- Bouton MON : active/coupe l'affichage du moniteur MIDI (GUI only)
        self.mon_btn = tk.Button(
            self.root, text="MON", font=("Helvetica", 10, "bold"),
            bg="#00695c", fg="#ffffff", activebackground="#00897b",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=12, pady=3, cursor="hand2", command=self._toggle_mon)
        cv.create_window(1430, 72, window=self.mon_btn, anchor="center")

        # --- Bouton MIDI ON/OFF : bascule GPIO3 série <-> MIDI
        # GPIO3 est partagé : MIDI actif = RX série coupée. M0 ne marche que
        # tant qu'on est en série ; en MIDI il faut rebooter pour revenir.
        self.midi_btn = tk.Button(
            self.root, text="MIDI", font=("Helvetica", 10, "bold"),
            bg="#1b5e20", fg="#ffffff", activebackground="#2e7d32",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=16, pady=3, cursor="hand2", command=self._toggle_midi)
        cv.create_window(1245, 72, window=self.midi_btn, anchor="center")
        self._btn_tip(self.panic_btn, "PANIC : interrompt toutes les notes "
                      "tenues (commande P) — utile si une note reste bloquée "
                      "après un Note-Off perdu.")
        self._btn_tip(self.midi_btn, "SÉRIE ↔ MIDI : bascule le mode d'entrée "
                      "(GPIO3 partagé entre le port série et le DIN MIDI). En "
                      "MIDI, la RX du port série est coupée (l'affichage "
                      "continue) mais le clavier maître joue le synthé ; il "
                      "faut rebooter pour revenir en série.")
        self._btn_tip(self.mon_btn, "MON : affiche/coupe le moniteur MIDI. "
                      "En mode MIDI, le firmware transmet chaque message "
                      "reçu (notes, molette, pitch, CC…) sous forme de ligne "
                      "courte ; ici on en voit les 2 dernières en haut. "
                      "Désactivable à volonté (actions GUI uniquement).")

        # --- Mod/Glide/Out (x 30..340) — 2 colonnes, lu de bas en haut puis
        # colonne suivante, pour suivre les câblages réels sur l'ESP32 :
        #   col1 (x=95)  : MOD MIX 210, GLIDE 330, GLIDE ON 450, DECAY 570
        #   col2 (x=235) : MOD OSC 210, CTRL OSC3 330, REVERB 450, écran 540+
        # Le bloc reverb (pot J50 + afficheur) reste en bas à droite.
        self.switch("decay", 95, 570, "DECAY",
                    help="DECAY : réglage des temps de déclin des enveloppes.")
        self.switch("glideOn", 95, 450, "GLIDE ON",
                    help="GLIDE ON : active le glissement tonal (portamento) "
                         "entre les notes jouées en séquence.")
        self.knob("glide", 95, 330, "GLIDE", fmt="{:.0%}",
                  help="GLIDE (portamento) : temps de glissement de fréquence "
                       "entre deux notes. Nécessite le switch GLIDE ON.")
        self.knob("modmix", 95, 210, "MOD MIX", fmt="{:.0%}",
                  help="MOD MIX : quantité de modulation provenant du VCO3/LFO "
                       "(envoyée vers la hauteur, le filtre et le volume).")
        self.switch("ctrlOsc3", 235, 330, "CTRL OSC3",
                    help="CTRL OSC3 : passe le VCO3 en mode contrôle (LFO) au "
                         "lieu d'une oscillation audible.")
        self.switch("modOsc", 235, 210, "MOD OSC",
                    help="MOD OSC : achemine la sortie du VCO3 vers la chaîne "
                         "de modulation (vibrato / filtre / gain).")
        # Pot REVERB dédié (J50, Mux2/C14) : reste dans ce panneau.
        self.knob("reverb", 235, 450, "REVERB", fmt="{:.0%}",
                  help="REVERB : niveau de la réverbération (pot dédié J50). "
                       "0 % = reverb coupée. Le type d'algo (ROOM / HALL / "
                       "PLATE / SPRING) se choisit avec le bouton PUSH du "
                       "VCO2, en mode REVERB.")
        # Indicateur reverb façon écran 80s : valeur en % (ambre), LED de
        # service, label en dessous.
        self.top["revPanel"] = cv.create_rectangle(
            193, 540, 277, 580, fill="#0e1116", outline="#4a525b", width=2)
        cv.create_rectangle(199, 546, 271, 574, outline="#1c262f", width=1)
        self.top["revLed"] = cv.create_oval(
            202, 556, 212, 566, fill="#3a4048", outline="#1a2b33")
        self.top["revValue"] = cv.create_text(
            235, 564, text="00%", font=("Courier", 16, "bold"),
            fill="#ffb14a")
        self.top["revGlow"] = []
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            self.top["revGlow"].append(cv.create_text(
                235 + dx, 564 + dy, text="00%",
                font=("Courier", 16, "bold"), fill="#5a2a00"))
        self.top["revUnit"] = cv.create_text(
            258, 549, text="REV", font=("Helvetica", 7), fill="#7a828b")
        self.top["rev"] = cv.create_text(
            235, 592, text="REVERB off", font=("Helvetica", 8, "bold"),
            fill="#3a4048")
        self.top["revType"] = cv.create_text(
            235, 606, text="", font=("Courier", 8, "bold"),
            fill="#7cd4ff")

        # --- Mixer (x 805..1115) : 3 vol + noise + EXT, switchs on/off,
        # et à droite filtMod + kbd ctl
        self.knob("vol1", 905, 210, "OSC1 VOL",
                  help="OSC1 VOL : volume de l'oscillateur 1 dans le mixer.")
        self.knob("vol2", 905, 330, "OSC2 VOL",
                  help="OSC2 VOL : volume de l'oscillateur 2 dans le mixer.")
        self.knob("vol3", 905, 450, "OSC3 VOL",
                  help="OSC3 VOL : volume de l'oscillateur 3 dans le mixer.")
        self.knob("volN", 905, 570, "NOISE VOL",
                  help="NOISE VOL : volume du bruit (couleur selon NOISE TYPE).")
        self.switch("mixOn1", 970, 210, "OSC1",
                    help="Envoie l'oscillateur 1 au mixer.")
        self.switch("mixOn2", 970, 330, "OSC2",
                    help="Envoie l'oscillateur 2 au mixer.")
        self.switch("mixOn3", 970, 450, "OSC3",
                    help="Envoie l'oscillateur 3 au mixer.")
        self.switch("mixOnN", 970, 570, "NOISE",
                    help="Envoie le bruit au mixer.")
        self.switch("typeNoise", 1050, 450, "NOISE TYPE",
                    states=("PINK", "WHITE"),
                    help="NOISE TYPE : couleur du bruit — rose (PINK) ou blanc "
                         "(WHITE).")
        self.knob("extVol", 1040, 570, "EXT VOL",
                  # Plage 0..1 : la trame P émet potExt (position du pot),
                  # pas volumeExt. Le firmware applique ensuite EXT_FB_SCALE
                  # pour obtenir le gain réel de la boucle.
                  help="EXT VOL : volume de l'entrée externe — feedback "
                       "interne du signal (la sortie est réinjectée avant le "
                       "filtre, hack Model D). 0 % = entrée coupée ; > 0 % = "
                       "le feedback est mélangé au mixer.")
        # groupés verticalement, alignés sur la zone filter (ils agissent dessus)
        self.switch("filtMod", 1062, 210, "FILT MOD",
                    help="FILT MOD : applique la modulation (molette MOD, VCO3 "
                         "en LFO) au filtre.")
        self.switch("kbd1", 1062, 265, "KBD CTL1",
                    help="KBD CTL1 : le clavier pilote la fréquence de coupure "
                         "du filtre (1 V/octave, façon Model D).")
        self.switch("kbd2", 1062, 330, "KBD CTL2",
                    help="KBD CTL2 : contrôle partiel du clavier sur la "
                         "coupure du filtre.")

        # --- Filter (x 1130..1470) — empilé au-dessus de Loudness
        self.knob("cut", 1185, 210, "CUTOFF", fmt="{:.0%}",
                  help="CUTOFF : fréquence de coupure du filtre passe-bas "
                       "4 pôles (transistors, son Model D).")
        self.knob("res", 1267, 210, "EMPHASIS", fmt="{:.0%}",
                  help="EMPHASIS : résonance du filtre — accentue la coupure, "
                       "peut s'auto-osciller en haut.")
        self.knob("amt", 1349, 210, "CONTOUR", fmt="{:.0%}",
                  help="CONTOUR : profondeur du contrôle de l'enveloppe de "
                       "filtre sur la coupure.")
        self.knob("fAtk", 1185, 340, "F ATK", lo=0.01, hi=10, fmt="{:.2f}s",
                  norm=norm_env_time,
                  help="F ATK : temps d'attaque de l'enveloppe de filtre "
                       "(0.01–10 s).")
        self.knob("fDec", 1267, 340, "F DECAY", lo=0.01, hi=10,
                  fmt="{:.2f}s", norm=norm_env_time,
                  help="F DECAY : temps de déclin de l'enveloppe de filtre "
                       "vers le maintien.")
        self.knob("fSus", 1349, 340, "F SUS", fmt="{:.0%}",
                  help="F SUS : niveau de maintien de l'enveloppe de filtre "
                       "pendant la tenue de la note.")

        # --- Oscillator Bank (x 360..920) : 3 lignes, une par VCO
        # de gauche à droite : VCO n | WAVEFORM | PUSH | RANGE | FREQ OSC (2,3)
        # alignées sur les lignes vol du mixer (y=210/330/450)
        rows = [(210, False), (330, True), (450, True)]
        for i, (y, has_det) in enumerate(rows):
            self.top[f"vco{i}"] = cv.create_text(
                405, y, text=f"VCO {i+1}", font=("Helvetica", 10, "bold"),
                fill="#d8d8d8")
            push_help = ("rappelle un patch de la banque (mode PATCH, "
                         "LED clignote)."
                         if i != 1 else
                         "choisit le type de réverbération (ROOM/HALL/PLATE/"
                         "SPRING) ; le niveau reste sur le pot REVERB (J50).")
            self.knob(f"wave{i}", 475, y, "WAVEFORM", lo=0, hi=5,
                      fmt=lambda v: WAVES[int(v)], wave=1,
                      help=f"WAVEFORM du VCO {i+1} : Tri / Tri-Saw / Scie / "
                           "Carré / Imp30 / Imp15.")
            self.switch(f"vco{i}sw", 580, y, "PUSH",
                        blink_txt="PATCH" if i == 0 else ("REVERB" if i == 1 else "PATCH"),
                        help=f"PUSH (VCO {i+1}) : bouton poussoir — " + push_help)
            self.knob(f"range{i}", 660, y, "RANGE", lo=1, hi=6,
                      fmt=lambda v: RANGES[int(v) - 1],
                      help=f"RANGE du VCO {i+1} : gamme 32' (grave) → 2' (aigu) "
                           "+ Lo (note la plus grave).")
            if has_det:
                self.knob(f"det{i}", 730, y, f"FREQ OSC{i+1}",
                          lo=-7, hi=7, fmt="{:+.1f} st",
                          help=f"FREQ OSC{i+1} : désaccord fin (demi-tons, "
                               "−7..+7) de l'oscillateur {i+1} par rapport au "
                               "VCO 1 — épaissit le son par battements.")

        # --- Loudness (x 1130..1470) — sous le filtre
        self.knob("lAtk", 1185, 520, "LOUD ATK", lo=0.01, hi=10,
                  fmt="{:.2f}s", norm=norm_env_time,
                  help="LOUD ATK : temps d'attaque de l'enveloppe de volume "
                       "(0.01–10 s).")
        self.knob("lDec", 1267, 520, "LOUD DECAY", lo=0.01, hi=10,
                  fmt="{:.2f}s", norm=norm_env_time,
                  help="LOUD DECAY : temps de déclin de l'enveloppe de volume "
                       "vers le maintien.")
        self.knob("lSus", 1349, 520, "LOUD SUS", fmt="{:.0%}",
                  help="LOUD SUS : niveau de maintien de l'enveloppe de volume "
                       "pendant la tenue de la note.")

        # --- Clavier (x 30..1470) — molettes pitch/mod à gauche,
        # 49 notes, la touche jouée s'enfonce
        self.pitchw = Wheel(self.cv, 140, 682, 52, 146, "PITCH",
                            lo=-2.0, hi=2.0, color="#ffd24a",
                            fmt="{:+.1f} st")
        self.modw = Wheel(self.cv, 205, 682, 52, 146, "MOD",
                          lo=0.0, hi=1.0, color="#7cd4ff", fmt="{:.0%}")
        # Atténuateur de modulation = pot "Mod Depth" du Model D (CC3, knob K1
        # du MPK249) : il borne la profondeur MAX de la molette. Jauge compacte
        # sous la molette MOD (elle n'a pas de pot physique sur le panneau).
        self.cv.create_text(205, 856, text="MOD DEPTH",
                            font=("Helvetica", 8), fill="#8b939c")
        self.cv.create_rectangle(140, 866, 270, 872, fill="#1b1f25",
                                 outline="#2f353c")
        self.moddep_bar = self.cv.create_rectangle(142, 868, 142, 870,
                                                   fill="#7cd4ff", outline="")
        self.moddep_val = self.cv.create_text(205, 884, text="",
                                              font=("Helvetica", 8, "bold"),
                                              fill="#d8d8d8")
        self.kbd = Keyboard(self.cv, 275, 695, 1150, 120, midi0=36, midi1=84,
                            note_cb=self._play_key)
        self.pitchw.update(0.0)
        self.modw.update(0.05)

        # --- Bulles d'aide des zones dessinées (wheels, clavier, reverb)
        self._tips.append((110, 668, 170, 846, "PITCH (lecture) : pitch bend "
                           "±7 demi-tons venant du clavier maître (MIDI)."))
        self._tips.append((175, 668, 235, 846, "MOD : position de la molette "
                           "de modulation (CC1) du clavier maître — vibrato par "
                           "le VCO3/LFO et ouverture du filtre. 100 % = pleine "
                           "course de la molette."))
        self._tips.append((275, 684, 1425, 822, "Clavier à la souris : cliquer "
                           "ou glisser sur les touches joue la note (commande N), "
                           "relâcher l'arrête (X). Fonctionne en mode SÉRIE "
                           "seulement ; en MIDI (RX coupée) il reste visuel."))
        self._tips.append((190, 535, 280, 614, "Réverbération : niveau par le pot "
                           "REVERB dédié (J50, juste au-dessus) et algorithme "
                           "par le poussoir VCO2 — ROOM / HALL / PLATE / "
                           "SPRING."))

    # ------------------------------------------------------------- données
    def _update_all(self, d, sw, locks=0):
        for name, k in self.knobs.items():
            idx = {"vol1": "vol1", "vol2": "vol2", "vol3": "vol3",
                   "volN": "volN", "cut": "cut", "res": "res",
                   "amt": "amt", "fAtk": "fAtk", "fDec": "fDec",
                   "fSus": "fSus", "lAtk": "lAtk", "lDec": "lDec",
                   "lSus": "lSus", "glide": "glide", "modmix": "modmix",
                   "det1": "freq2", "det2": "freq3",
                   "extVol": "ext", "reverb": "reverb"}.get(name)
            locked = False
            if idx in LOCK_POT_KEYS:
                locked = bool(locks & (1 << (13 + LOCK_POT_KEYS.index(idx))))
            elif name in LOCK_WAVE_RANGE:
                locked = bool(locks & (1 << LOCK_WAVE_RANGE[name]))
            elif name == "extVol":
                locked = bool(locks & (1 << LOCK_EXT_BIT))
            elif name == "reverb":
                locked = bool(locks & (1 << LOCK_REVERB_BIT))
            if idx and idx in d:
                k.update(d[idx], locked)
            elif name.startswith("wave"):
                k.update(d.get(f"wave{name[-1]}", 0), locked)
            elif name.startswith("range"):
                k.update(d.get(f"range{name[-1]}", 1), locked)
        for idx, key in self.SWMAP:
            if key in self.switches:
                self.switches[key].update(sw[idx],
                                          locked=bool(locks & (1 << idx)))
        # EXT VOL : gris tant que l'entrée externe est coupée (vol == 0),
        # orange sinon (comme un potard actif). SAUF si le pot est figé par un
        # patch : le cyan de verrouillage doit primer, ce bloc venait l'écraser
        # après Knob.update() et le pot restait orange alors qu'il était gelé.
        if "extVol" in self.knobs:
            ek = self.knobs["extVol"]
            if locks & (1 << LOCK_EXT_BIT):
                needle_fill, value_fill = "#00e5ff", "#00e5ff"
            elif d.get("ext", 0.0) > 0.02:
                needle_fill, value_fill = "#ff8c3a", "#ffd24a"
            else:
                needle_fill, value_fill = "#4a525b", "#5a6470"
            self.cv.itemconfigure(ek.idv["needle"], fill=needle_fill)
            self.cv.itemconfigure(ek.idv["value"], fill=value_fill)
        for i in range(3):
            if f"vco{i}sw" in self.switches:
                self.switches[f"vco{i}sw"].update(d.get(f"modR{i}", 0))
        # ENC2 en mode 2 = REVERB : le push VCO2 ne change plus que le TYPE
        # d'algo. Le niveau est porté par son propre pot J50 (knob REVERB),
        # donc le knob OSC2 VOL affiche toujours le volume d'OSC2.
        if "vol2" in self.knobs:
            self.knobs["vol2"].fmt = "{:.2f}"
        # Indicateur reverb façon écran 80s : valeur en % (ambre) + LED de service
        if "rev" in self.top:
            on = d.get("reverb", 0.0) > 0.001
            pct = max(0.0, min(1.0, d.get("reverb", 0.0)))
            txt = "{:02d}%".format(int(round(pct * 100)))
            self.cv.itemconfigure(
                self.top["revValue"], text=txt,
                fill="#ffb14a" if on else "#7a828b")
            for g in self.top.get("revGlow", []):
                self.cv.itemconfigure(g, text=txt,
                                      fill="#5a2a00" if on else "#2a2f36")
            self.cv.itemconfigure(
                self.top["revLed"],
                fill="#ff4a4a" if on else "#3a4048")
            self.cv.itemconfigure(
                self.top["rev"], text="REVERB ON" if on else "REVERB off",
                fill="#3bff5a" if on else "#3a4048")
            # Type d'algo (ENC2 mode reverb) : ROOM / HALL / PLATE / SPRING
            rt = int(d.get("revtype", 0) or 0)
            noms = ("ROOM", "HALL", "PLATE", "SPRING")
            self.cv.itemconfigure(
                self.top["revType"], text=noms[rt % len(noms)],
                fill="#7cd4ff" if on else "#3a4048")

    def _parse(self, line):
        # ACK/NACK du firmware lors d'un rappel de patch (commande L)
        if "Patch chargé" in line:
            self._probe_miss = 0
            try:
                nom = line.rsplit(":", 1)[-1].strip()
            except Exception:
                nom = "?"
            label = f"Patch: {nom or '?'}"
            if len(label) > 24:
                label = label[:21] + "…"
            self.cv.itemconfigure(self.top["patch"], text=label)
            return
        if ("Patch invalide" in line or "Patch inconnu" in line
                or "Aucun patch en banque" in line or "Banque pleine" in line):
            self._probe_miss = 0
            label = "Patch: ! " + line.strip()[:40]
            self.cv.itemconfigure(self.top["patch"], text=label)
            return
        # Réponse à la requête B? : vérifie/repousse si la banque diffère
        if "Banque :" in line:
            try:
                n = int(line.split(":")[-1].strip())
            except ValueError:
                return
            self._probe_miss = 0
            self._bank_sync = n
            self._midi_estActive = False   # une réponse B? = mode série confirmé
            self._midi_manual = False
            self.midi_btn.configure(text="MIDI", bg="#1b5e20")
            if n == len(self.patches) and n > 0:
                self.cv.itemconfigure(
                    self.top["patch"],
                    text=f"Patch: {n} en banque (fw)")
            else:
                # liaison vivante mais banque absente/partielle : repousser
                self.cv.itemconfigure(
                    self.top["patch"],
                    text=f"Patch: {n}/{len(self.patches)} → repush")
                self._bank_pushed = False
                if self.ser and self.ser.is_open:
                    self._push_bank()
            return
        if not line.startswith("P,"):
            if line.startswith("M,"):
                self._mon_feed(line)
            return
        parts = line.strip().split(",")
        try:
            floats = [float(p) for p in parts[1:18]]
            reverb = float(parts[18])
            sw = [int(p) for p in parts[19:32]]
            waves = [int(parts[32]), int(parts[35]), int(parts[38])]
            rngs = [int(parts[33]), int(parts[36]), int(parts[39])]
            modR = [int(parts[34]), int(parts[37]), int(parts[40])]
            note = int(parts[41])
            midiOn = int(parts[42])
            pitch = float(parts[43])
            modW = float(parts[44])
            patch = parts[45] if len(parts) > 45 else ""
        except (ValueError, IndexError):
            return

        locks = 0
        if len(parts) > 46:
            try:
                lm = parts[46]
                if '.' in lm:
                    lo, hi = lm.split(".", 1)
                else:
                    # try to repair if concatenated
                    lo, hi = lm, '0'
                locks = (int(hi, 16) << 32) | int(lo, 16)
            except Exception:
                locks = 0
        revtype = 0
        if len(parts) > 47:
            try:
                revtype = int(parts[47])
            except (ValueError, IndexError):
                revtype = 0
        ext = 0.0
        if len(parts) > 48:
            try:
                ext = float(parts[48])
            except (ValueError, IndexError):
                ext = 0.0
        moddepth = 1.0
        if len(parts) > 49:
            try:
                moddepth = float(parts[49])
            except (ValueError, IndexError):
                moddepth = 1.0

        nums = ["vol1", "vol2", "vol3", "volN", "freq2", "freq3",
                "cut", "res", "amt", "fAtk", "fDec", "fSus",
                "lAtk", "lDec", "lSus", "glide", "modmix"]
        d = dict(zip(nums, floats))
        d["wave0"] = waves[0]
        d["wave1"] = waves[1]
        d["wave2"] = waves[2]
        d["range0"] = rngs[0]
        d["range1"] = rngs[1]
        d["range2"] = rngs[2]
        d["modR0"] = modR[0]
        d["modR1"] = modR[1]
        d["modR2"] = modR[2]
        d["reverb"] = reverb
        d["revtype"] = revtype
        d["ext"] = ext
        d["moddepth"] = moddepth

        self._last = d.copy()
        self._last["sw"] = sw
        # 1re trame reçue = firmware prêt à écouter : pousser la banque
        if getattr(self, "_bank_pushed", True) is False \
                and self.ser and self.ser.is_open:
            self._push_bank()

        self._update_all(d, sw, locks)

        for i in range(3):
            self.cv.itemconfigure(
                self.top[f"vco{i}"],
                text=f"VCO {i+1}")

        note_txt = f"Note: {note}  {'ON' if midiOn else 'off'}"
        if not (36 <= note <= 84):
            note_txt += " (hors portée GUI)"
        self.cv.itemconfigure(self.top["note"], text=note_txt)
        # Le nom du patch est toujours affiché (même en MIDI, la TX série
        # continue d'émettre les trames P → le nom reste à jour).
        label = f"Patch: {patch or '—'}"
        if len(label) > 24:
            label = label[:21] + "…"
        self.cv.itemconfigure(self.top["patch"], text=label)
        try:
            self.kbd.set_note(note, bool(midiOn))
        except Exception:
            pass  # l'affichage des wheels/pitch ne doit jamais être bloqué
        self.pitchw.update(12.0 * math.log2(pitch) if pitch > 0 else 0.0)
        self.modw.update(modW / MOD_WHEEL_NORM)
        # Atténuateur (CC3) : 0 % = molette inerte -> barre et valeur grisées
        md = max(0.0, min(1.0, d.get("moddepth", 1.0)))
        self.cv.coords(self.moddep_bar, 142, 868,
                       142 + 126 * md if md > 0.004 else 142.5, 870)
        self.cv.itemconfigure(self.moddep_bar,
                              fill="#7cd4ff" if md > 0.004 else "#39414a")
        self.cv.itemconfigure(self.moddep_val,
                              text=f"{md:.0%}",
                              fill="#d8d8d8" if md > 0.004 else "#5a6470")

    def _demo_feed(self):
        t = time.time()
        d = {
            "vol1": 0.8, "vol2": 0.7, "vol3": 0.5, "volN": 0.05,
            "freq2": 3.0 * math.sin(t * 1.3),
            "freq3": 2.0 * math.sin(t * 0.9),
            "cut": 0.45 + 0.2 * math.sin(t * 0.5),
            "res": 0.25 + 0.1 * math.sin(t * 0.3),
            "amt": 0.65, "fAtk": 0.2, "fDec": 1.2, "fSus": 0.7,
            "lAtk": 0.01 + 0.5 * math.sin(t * 0.7),
            "lDec": 0.5, "lSus": 0.8,
            "glide": 0.35, "modmix": 0.5 + 0.2 * math.sin(t),
            "wave0": 2, "wave1": 3, "wave2": 0,
            "range0": 2, "range1": 4, "range2": 6,
            "modR0": 1, "modR1": 0, "modR2": 1,
            "reverb": 0.45, "revtype": int(t) % 4, "ext": 0.2 + 0.3 * math.sin(t), "moddepth": 0.5 + 0.5 * math.sin(t * 0.7),
        }
        sw0 = [0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1]
        self._update_all(d, sw0)
        for i in range(3):
            self.cv.itemconfigure(self.top[f"vco{i}"],
                                  text=f"VCO {i+1}")
        self.cv.itemconfigure(self.top["note"],
                              text=f"Note: {40+int(t)%20}  "
                                   f"{'ON' if int(t)%2 else 'off'}")
        self.cv.itemconfigure(self.top["patch"],
                              text=f"Patch: {('BRASS' if int(t)%2 else 'SHINE_ON')}")
        self.kbd.set_note(40 + int(t) % 20, bool(int(t) % 2))
        self.pitchw.update(2.0 * math.sin(t))
        self.modw.update(0.5 + 0.5 * math.sin(t * 0.8))

    def _panic(self):
        """Bouton PANIC : envoie la commande série 'P' pour réinitialiser le MIDI
        (relâche toutes les notes, vide la pile MIDI, molettes au neutre)."""
        self.panic_btn.configure(bg="#ff6b5e")
        self.root.after(300, lambda: self.panic_btn.configure(bg="#c0392b"))
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(b"P\n")
            except Exception:
                pass

    def _toggle_midi(self):
        """Bascule entre commandes série (M0) et MIDI (M1) sur GPIO3."""
        if not (self.ser and self.ser.is_open):
            return
        if getattr(self, "_midi_estActive", False):
            # En MIDI la RX série est coupée : M0 ne part pas. On resets l'ESP
            # (DTR/RTS) pour revenir en mode série avec la banque.
            self._auto_serial_recovery()
            return
        try:
            self.ser.write(b"M1\n")
            self.ser.flush()
        except Exception:
            return
        self._midi_estActive = True
        self._midi_manual = True   # MIDI volontaire : ne pas auto-reset ensuite
        self.midi_btn.configure(text="SÉRIE", bg="#37474f")

    def _mon_feed(self, line):
        """Ligne 'M,statusHEX,d0,d1' du firmware : message MIDI reçu. Journalise
        et raffraîchit le panneau moniteur (si activé par le bouton MON)."""
        q = self._mon_q
        try:
            p = line.split(",")
            st = int(p[1], 16)
            d0 = int(p[2]) if len(p) > 2 else 0
            d1 = int(p[3]) if len(p) > 3 else 0
            q.insert(0, self._mon_text(st, d0, d1))
        except (ValueError, IndexError):
            q.insert(0, "…")
        del q[2:]
        if self._mon_on:
            self._mon_render()

    def _mon_text(self, st, d0, d1):
        """Traduit un message MIDI en une ligne courte lisible."""
        typ, ch = st & 0xF0, (st & 0x0F) + 1
        if typ == 0x80:
            return f"Note OFF ch{ch} · {d0} v{d1}"
        if typ == 0x90:
            return (f"Note OFF ch{ch} · {d0}" if d1 == 0
                    else f"Note ON ch{ch} · {d0} v{d1}")
        if typ == 0xA0:
            return f"Aftertouch ch{ch} · v{d0}"
        if typ == 0xB0:
            return (f"CC mod ch{ch} · v{d1}" if d0 == 1
                    else f"CC ch{ch} · n{d0} v{d1}")
        if typ == 0xC0:
            return f"Program ch{ch} · {d0}"
        if typ == 0xD0:
            return f"Chann. aft. ch{ch} · v{d0}"
        if typ == 0xE0:
            return f"Pitch ch{ch} · {((d1 << 7) | d0) - 8192:+d}"
        return f"Msg ch{ch} · {typ:#04x}"

    def _mon_render(self):
        """Dessine les 2 dernières lignes MON dans la bande du haut."""
        q = self._mon_q
        latest = q[0] if q else "MIDI MON — en attente de messages…"
        older = q[1] if len(q) > 1 else ""
        self.cv.itemconfigure(self.top["mon0"], text=latest)
        self.cv.itemconfigure(self.top["mon1"], text=older)

    def _toggle_mon(self):
        """Bouton MON : active/coupe l'affichage du moniteur MIDI (GUI only,
        aucun impact sur le firmware qui continue d'émettre les lignes M)."""
        self._mon_on = not self._mon_on
        self.mon_btn.configure(
            bg="#00695c" if self._mon_on else "#37474f",
            activebackground="#00897b" if self._mon_on else "#546e7a")
        for k in ("mon0", "mon1"):
            self.cv.itemconfigure(
                self.top[k], state="normal" if self._mon_on else "hidden")
        if self._mon_on:
            self._mon_render()

    def _play_key(self, note, on):
        """Joue relâche une note (clavier à la souris).

        En mode SÉRIE : N<note> = note ON, X = note OFF. En mode MIDI la RX
        série est coupée (les commandes n'arrivent plus au firmware) : le
        clavier reste visuel, sans son."""
        if on:
            self._kbd_pressed = note
        elif getattr(self, "_kbd_pressed", None) != note:
            return
        if self.demo:
            return
        if getattr(self, "_midi_estActive", False):
            return
        if not (self.ser and self.ser.is_open):
            return
        try:
            if on:
                self.ser.write(f"N{note}\n".encode())
            else:
                self.ser.write(b"X\n")
            self.ser.flush()
        except Exception:
            pass

    def _blink_tick(self):
        """Clignotement local des LED (mode patch ENC1 : VCO1)."""
        phase_on = (int(time.time() * 4) % 2) == 0
        for sw in self.switches.values():
            sw.blink_tick(phase_on)

    def _tick(self):
        frames = 0
        t0 = time.time()
        self._blink_tick()
        if self.demo:
            self._demo_feed()
            frames = 1
            self.root.after(120, self._tick)
            return
        if self.ser and self.ser.is_open:
            # Sonde banque : vérifie régulièrement que le firmware est en série
            # et possède la bonne banque ; sinon repousse / informe.
            if not getattr(self, "_probe_t", 0) or \
                    time.time() - self._probe_t > 2.0:
                self._probe_t = time.time()
                self._probe_miss = getattr(self, "_probe_miss", 0) + 1
                # RX muette un long moment (mode MIDI / UART hors ligne) :
                # on réarme discretement le mode série une seule fois, SAUF si
                # le MIDI a été activé volontairement (bouton GUI → M1).
                if getattr(self, "_probe_miss", 0) == 5 \
                        and not getattr(self, "_midi_manual", False):
                    self._auto_serial_recovery()
                else:
                    # si 3 sondes consécutives sans réponse → mode MIDI (RX coupée)
                    if getattr(self, "_probe_miss", 0) >= 3:
                        # RX série coupée → le firmware est en mode MIDI
                        self._midi_estActive = True
                        self.midi_btn.configure(text="SÉRIE", bg="#37474f")
                    else:
                        # mode série actif → le bouton propose de passer en MIDI
                        self.midi_btn.configure(text="MIDI", bg="#1b5e20")
                    try:
                        self.ser.write(b"B?\n")
                        self.ser.flush()
                    except Exception:
                        pass
            while time.time() - t0 < 0.05:
                try:
                    line = self.ser.readline()
                    if not line:
                        break
                    s = line.decode("utf-8", "replace").strip()
                    if s:
                        self._parse(s)
                        frames += 1
                except Exception:
                    break
        self.cv.itemconfigure(self.top["fps"], text=f"FPS: {frames*20}")
        self.root.after(50, self._tick)


def list_ports():
    if serial:
        import serial.tools.list_ports as lp
        return [p.device for p in lp.comports()]
    return []


def main():
    ap = argparse.ArgumentParser(description="Panneau Minimoog Model D temps réel")
    ap.add_argument("port", nargs="?", help="Port série (ex: /dev/ttyUSB0)")
    ap.add_argument("-d", "--demo", action="store_true", help="Mode démo")
    ap.add_argument("-l", "--list", action="store_true", help="Lister les ports")
    args = ap.parse_args()

    if args.list:
        print("\n".join(list_ports()))
        return
    if not args.port and not args.demo:
        ports = list_ports()
        if len(ports) == 1:
            args.port = ports[0]
            print(f"Port détecté : {args.port}")
        elif ports:
            print("Ports disponibles :")
            for p in ports:
                print(f"  {p}")
            return
        else:
            print("Aucun port trouvé. Utilisez --demo ou -l.")
            return
    App(port=args.port, demo=args.demo)


if __name__ == "__main__":
    main()