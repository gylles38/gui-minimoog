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
m2 : 0=waveform, 1=range, 2=reverb, 3=delay (LED VCO2 clignote en 2 et 3)
revType : 0 ROOM, 1 HALL, 2 PLATE, 3 SPRING (choisi par ENC2 mode reverb)
champs suivants : extVol (pot J49), modDepth (CC3), velDepth (CC9),
          delayLevel (pot J50 en mode ENC2 3), delayType (0..3 = 60/120/240/480 ms)
lockMask : hex "lo.hi" — bits à 1 = contrôle figé sur la valeur du patch
          (39 bits : 0-12 switchs, 13-29 pots, 30-35 wave/range, 36 EXT VOL,
           37 NIVEAU REVERB, 38 NIVEAU DELAY)
  (rétention latch, affiché en ambre)

Dernier champ de la trame : ledBright (0..1, luminosité PWM des 3 LEDs
physiques OSC1/2/3 sur l'ESP32). Le curseur LED BRIGHT de la bande du bas
l'envoie au firmware (commande série 'W<0-100>') ; le clavier maître peut
aussi la régler en MIDI CC14.


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

CC MIDI : la correspondance des contrôleurs (molette, mod depth, vel filt,
LED bright, chargement de patch) est définie dans config.json (source de
vérité sur le PC) et poussée au firmware par la commande série
'C mw,md,vd,lb,pl' au branchement puis à chaque modification (bouton CONFIG) —
donc modifiable sans reflash. Le firmware renvoie la table active en fin de
trame P (champs ccMW/ccMD/ccVD/ccLB/ccPL), affichée dans la boîte CONFIG.

Séquences : le menu DÉMO de la bande du haut propose de courts riffs
classiques (sequences.json — éditable). Au lancement, le patch le plus adapté
est choisi automatiquement dans la banque selon le profil du riff, chargé au
firmware (commande L<nom>) puis joué une fois (commande N n<note>s<durée>,
arrêt automatique en fin de motif ; STOP envoie A immédiatement).

Usage :
    python3 panel_minimoog.py /dev/ttyUSB0          (port explicite)
    python3 panel_minimoog.py --demo                (données simulées)
    python3 panel_minimoog.py -l                    (liste des ports)
"""

import argparse
import json
import math
import os
import random
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

try:
    import serial
except ImportError:
    serial = None

WAVES = ["Tri", "Tri-Saw", "Scie", "Carre", "Imp30", "Imp15"]
RANGES = ["32'", "16'", "8'", "4'", "2'", "Lo"]

# --- textures du fond, façon Model D original -----------------------------
# Cabinet en noyer (marges) + plaque d'aluminium anodisé noir brossé au
# centre, sérigraphie crème des cadres de section par-dessus. Tout est peint
# en canvas, sans image ni dépendance, avec une graine fixe : rendu stable.
WOOD_BASE = "#5b3a22"
WOOD_DARK = ("#4a2e1a", "#3f2716", "#472a17", "#553521")
WOOD_LIGHT = ("#6b4529", "#7a5232", "#65402a", "#714928")
PANEL_FILL = "#17181a"
PANEL_EDGE = "#0b0c0d"
PANEL_BRUSH_LIGHT = ("#1c1e22", "#21242a", "#1a1d21")
PANEL_BRUSH_DARK = ("#111214", "#131417", "#101113")
PANEL_GRAIN = ("#20232a", "#0f1012", "#1a1d23")
SILK = "#c2baa8"          # sérigraphie crème (cadres de section)
# Décalage vertical du corps du panneau (sous la bande du haut) : libère de la
# place pour les lignes d'en-tête et la ligne DÉMO. La plaque métallique et le
# rail en bois suivent ce décalage (voir PANEL_BOX / PANEL_SCREWS et App).
BODY_DY = 34
# Marge de bois sous le rail des jauges (MOD DEPTH / VEL FILT / LED BRIGHT)
# jusqu'au bas de la fenêtre : y loge les vis du bas, près de la bordure.
BOTTOM_PAD = 40
# Rectangle de la plaque : 6 px de métal autour des sections, le bas s'arrête
# au-dessus des jauges MOD DEPTH / VEL FILT qui vivent sur le rail en bois.
PANEL_BOX = (24, 24, 1476, 849 + BODY_DY)
# Dimensions de la fenêtre (partagées avec App.W / App.H).
WIN_W, WIN_H = 1500, 900 + BODY_DY + BOTTOM_PAD
# Vis du panneau, uniquement dans les marges en bois (aucun widget à ces
# emplacements : x<24, x>1476, y<24, ou sous la plaque hors jauges). Les vis du
# bas sont placées juste au-dessus de la bordure inférieure de la fenêtre.
PANEL_SCREWS = (
    (13, 200), (13, 470), (13, 740 + BODY_DY),
    (1487, 200), (1487, 470), (1487, 740 + BODY_DY),
    (330, 13), (750, 13), (1170, 13),
    (330, WIN_H - 14), (750, WIN_H - 14), (1170, WIN_H - 14),
)

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
# Le delay réutilise le même pot J50 (autre cible, autre valeur mémoire) :
# il occupe le champ `delaylevel` de la trame et un bit à lui seul.
LOCK_DELAY_BIT = 38

# --- LED OVERLOAD (GUI uniquement, aucun changement firmware) ---------------
# Le Model D a une lampe OVERLOAD qui s'allume quand la sortie sature. La GUI
# ne reçoit pas l'audio : on l'estime à partir de la somme des sources actives
# du mixer (volumes OSC1/2/3 + bruit + feedback entrée externe), pondérée par
# une enveloppe LOUDNESS simulée localement (lAtk/lDec/lSus + note tenue).
# Les volumes de la trame sont en 0..1, donc « drive » va de 0 (silence) à ~4
# (4 sources à fond). Seuil et durée de maintien visuelle ajustables ici :
OVERLOAD_THRESHOLD = 2.8    # « drive » (somme × enveloppe) au-delà duquel ça sature
OVERLOAD_HOLD = 0.35        # s : la LED reste allumée après un pic (persistance)

PATCHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "patches.json")

# --- Configuration MIDI (paramétrable depuis la GUI, conservée en JSON) ------
# Table des CC utilisés par le firmware, poussée par la commande série
# 'C <mw>,<md>,<vd>,<lb>,<pl>' (cf. minimoog.ino). Les clés sont les mêmes que
# dans la trame P ; ce fichier est la source de vérité côté PC.
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "config.json")
DEFAULT_CONFIG = {
    "cc_modwheel": 1,    # molette de modulation
    "cc_moddepth": 3,    # atténuateur "Mod Depth" (knob K1)
    "cc_veldepth": 9,    # atténuateur vélocité → CONTOUR (knob MPK249)
    "cc_ledbright": 14,  # luminosité des LEDs OSC1/2/3
    "cc_patch": 122,     # chargement de patch (value 1-5)
}
# Ordre exact attendu par la commande série 'C' du firmware :
CC_ORDER = ["cc_modwheel", "cc_moddepth", "cc_veldepth",
            "cc_ledbright", "cc_patch"]
CC_LABELS = [
    ("cc_modwheel", "Molette modulation"),
    ("cc_moddepth", "Mod Depth (atténuateur)"),
    ("cc_veldepth", "Vel Filt (atténuateur)"),
    ("cc_ledbright", "LED bright (luminosité)"),
    ("cc_patch", "Chargement de patch"),
]

# --- Séquences de démonstration (menu SÉQUENCE de la barre du haut) ----------
# Chaque séquence est jouée par le firmware (commande 'N n<note>s<durée> …',
# syntaxe de traiterSequence() dans minimoog.ino) : le firmware le joue en
# boucle mais la GUI envoie 'A' en fin de passe (lecture unique). Le patch le
# plus adapté est choisi automatiquement dans la banque selon le profil du riff
# (voir patch_score/best_patch ci-dessous) ; sequences.json reste éditable.
SEQUENCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "sequences.json")
DEFAULT_SEQUENCES = {
    "sequences": [
        {"nom": "I Feel Love (Donna Summer)", "profil": "bass",
         "notes": [[48, 0.13], [48, 0.13], [48, 0.13], [48, 0.13],
                   [46, 0.13], [46, 0.13], [46, 0.13], [46, 0.13],
                   [44, 0.13], [44, 0.13], [44, 0.13], [44, 0.13],
                   [46, 0.13], [46, 0.13], [46, 0.13], [46, 0.13]]},
        {"nom": "Thriller (Michael Jackson)", "profil": "bass",
         "notes": [[54, 0.18], [54, 0.18], [54, 0.18],
                   [52, 0.18], [52, 0.18], [52, 0.18],
                   [50, 0.18], [50, 0.18], [50, 0.18],
                   [49, 0.18], [49, 0.18], [49, 0.18]]},
        {"nom": "The Chain (Fleetwood Mac)", "profil": "bass",
         "notes": [[40, 0.22], [40, 0.22], [40, 0.22], [40, 0.22],
                   [43, 0.22], [43, 0.22], [45, 0.22], [45, 0.22],
                   [43, 0.22], [43, 0.22], [40, 0.22], [40, 0.22]]},
        {"nom": "Chariots of Fire (Vangelis)", "profil": "strings",
         "notes": [[62, 0.35], [64, 0.35], [66, 0.35], [69, 0.7],
                   [66, 0.35], [64, 0.35], [62, 0.7]]},
        {"nom": "Frankenstein (Edgar Winter)", "profil": "lead",
         "notes": [[69, 0.12], [67, 0.12], [65, 0.12], [64, 0.12],
                   [62, 0.12], [60, 0.12], [62, 0.12], [64, 0.12],
                   [65, 0.12], [67, 0.12]]},
        {"nom": "Flash Gordon (Vangelis)", "profil": "brass",
         "notes": [[62, 0.18], [62, 0.18], [65, 0.18], [67, 0.36],
                   [62, 0.18], [65, 0.18], [67, 0.18], [70, 0.7]]},
        {"nom": "Autobahn (Kraftwerk)", "profil": "lead",
         "notes": [[67, 0.25], [67, 0.25], [69, 0.25], [67, 0.25],
                   [65, 0.25], [64, 0.25], [65, 0.25], [64, 0.25]]},
        {"nom": "Lucky Man (ELP)", "profil": "lead",
         "notes": [[62, 0.2], [64, 0.2], [66, 0.2], [67, 0.2], [69, 0.2],
                   [71, 0.2], [74, 0.5], [71, 0.2], [69, 0.2], [67, 0.2],
                   [66, 0.5]]},
    ]
}

# Profils de sélection automatique du patch : pour chaque profil, une cible
# (feature -> valeur visée) et son poids. Le score d'un patch = somme(poids ×
# proximité) ; la proximité vaut 1 quand le patch colle à la cible et décroît
# avec l'écart. Purement paramétrique : s'adapte à n'importe quelle banque.
_ENV_SCALE = 1.5     # normalisation des temps d'enveloppe (latk/fatk/ldec)
_RANGE_SCALE = 2.5   # normalisation des octaves (lo/hi/rm)
_PATCH_PROFILES = {
    "bass": ({"lo": 1.0, "rm": 1.6, "latk": 0.02, "lsus": 0.5,
              "cut": 0.35, "glide": 0.15},
             {"lo": 2, "rm": 1, "latk": 2, "lsus": 1, "cut": 1, "glide": 1}),
    "lead": ({"lo": 3.0, "rm": 3.0, "latk": 0.06, "glide": 0.3,
              "cut": 0.45, "res": 0.45},
             {"lo": 1, "rm": 1, "latk": 2, "glide": 2, "cut": 1, "res": 1}),
    "pad": ({"latk": 0.5, "fatk": 0.55, "lsus": 0.85, "rm": 3.2, "saw": 0.0},
            {"latk": 3, "fatk": 2, "lsus": 2, "rm": 1, "saw": 0.5}),
    "strings": ({"latk": 0.8, "fatk": 0.7, "lsus": 0.9, "saw": 1.0},
                {"latk": 3, "fatk": 2, "lsus": 2, "saw": 1}),
    "brass": ({"fatk": 0.18, "amt": 0.8, "cut": 0.42, "lsus": 0.75,
               "saw": 1.0, "rm": 3.2},
              {"fatk": 2, "amt": 2, "cut": 1, "lsus": 1, "saw": 1, "rm": 1}),
    "pluck": ({"latk": 0.01, "lsus": 0.2, "ldec": 0.15, "cut": 0.55},
              {"latk": 3, "lsus": 2, "ldec": 2, "cut": 1}),
    "whistle": ({"hi": 6, "res": 1.0, "glide": 0.4, "cut": 0.35},
                {"hi": 2, "res": 2, "glide": 1, "cut": 1}),
}


def patch_features(p):
    """Vecteur de caractéristiques normalisées d'un patch de la banque."""
    r = p.get("r") or [3, 3, 3]
    w = p.get("w") or [2, 2, 2]
    return {
        "lo": min(r), "hi": max(r), "rm": sum(r) / max(1, len(r)),
        "latk": p.get("lAtk", 0.0), "fatk": p.get("fAtk", 0.0),
        "lsus": p.get("lSus", 1.0), "ldec": p.get("lDec", 0.0),
        "cut": p.get("cut", 0.0), "res": p.get("res", 0.0),
        "amt": p.get("amt", 0.0), "glide": p.get("glide", 0.0),
        "saw": 1.0 if 2 in w else 0.0,
    }


def patch_score(patch, profil):
    """Score d'adéquation d'un patch à un profil (plus grand = plus adapté)."""
    cible = _PATCH_PROFILES.get(profil)
    if not cible or patch is None:
        return 0.0
    tgt, poids = cible
    fe = patch_features(patch)
    score = 0.0
    for k, t in tgt.items():
        ech = _ENV_SCALE if k in ("latk", "fatk", "ldec") else _RANGE_SCALE
        score += poids[k] * (1.0 - min(1.0, abs(fe[k] - t) / ech))
    return score


def best_patch(patches, profil):
    """Patch le plus adapté à un profil dans la banque (None si banque vide)."""
    best, best_s = None, None
    for p in patches:
        s = patch_score(p, profil)
        if best_s is None or s > best_s:
            best, best_s = p, s
    return best


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


def _mix(c1, c2, t):
    """Mélange deux couleurs « #rrggbb » — t = poids de la 2e."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t))
                                   for i in range(3))


# Code couleur officiel des « Switch, Rocker » du Model D (réf. 51-20X) :
MD_BLUE = "#2f6fd0"     # sources audio : on / off dans le mixer
MD_ORANGE = "#e8620f"   # modulation : d'une source vers sa destination
MD_WHITE = "#e8e4dc"    # fonctions de jeu (GLIDE, DECAY, KBD CTL, PUSH)
MD_BLACK = "#2a2d31"    # sélection d'une source (NOISE TYPE)


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

    def blink_tick(self, phase_on):
        self._phase = phase_on
        if self.blink:
            self._set(phase_on)


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


class App:
    W, H = WIN_W, WIN_H
    BODY_DY = BODY_DY  # voir la constante module (partagée avec PANEL_BOX)

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
        # Fond = bois du cabinet : si la fenêtre est agrandie, le débord
        # prolonge le cabinet au lieu de laisser un gris technique.
        self.root.configure(bg=WOOD_BASE)
        self.root.geometry(f"{self.W}x{self.H}")
        self.root.minsize(self.W, self.H)
        self.cv = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg=WOOD_BASE, highlightthickness=0)
        self.cv.pack(fill="both")

        self.knobs = {}
        self.switches = {}
        self.top = {}
        self._bank_pushed = True
        self._bank_sync = -1
        self.patches = self._load_patches()
        self.config = self._load_config()
        self.sequences = self._load_sequences()
        self._seq_playing = False
        self._seq_after = None
        self._tips = []
        self._tip_last = None
        self.tt = ToolTip()
        self._mon_on = True          # moniteur MIDI actif au lancement
        self._mon_q = []             # max 2 lignes, q[0] = plus récente
        self._ovl_env = 0.0          # enveloppe LOUDNESS simulée (LED OVERLOAD)
        self._ovl_t = time.time()
        self._ovl_lit_until = 0.0    # maintien visuel de la LED OVERLOAD
        self._led_drag = False       # curseur LED BRIGHT en cours de glissé ?
        self._led_val = 0.5          # dernière luminosité LEDs (0..1)
        self._led_sent = -1          # dernier pourcent W envoyé au firmware
        self._mod_drag = False       # jauge MOD DEPTH en cours de glissé ?
        self._mod_val = 0.5          # atténuateur MOD DEPTH courant (0..1)
        self._vel_drag = False       # jauge VEL FILT en cours de glissé ?
        self._vel_val = 0.5          # atténuateur VEL FILT courant (0..1)
        self._depth_sent = (-1, -1)  # dernier couple (mod,vel) % envoyé (cmd D)
        self._build_panel()
        self._build_patch_widgets()
        self._build_sequence_widgets()
        self.cv.bind("<Enter>", self._tip_motion)
        self.cv.bind("<Motion>", self._tip_motion)
        self.cv.bind("<Leave>", lambda e: self._tip_clear())
        # Jauges (LED BRIGHT, MOD DEPTH, VEL FILT) : bindings additifs
        # (le clavier virtuel garde les siens).
        self.cv.bind("<ButtonPress-1>", self._on_led_down, add="+")
        self.cv.bind("<B1-Motion>", self._on_led_drag, add="+")
        self.cv.bind("<ButtonRelease-1>", self._on_led_up, add="+")
        self.cv.bind("<ButtonPress-1>", self._on_mod_down, add="+")
        self.cv.bind("<B1-Motion>", self._on_mod_drag, add="+")
        self.cv.bind("<ButtonRelease-1>", self._on_mod_up, add="+")
        self.cv.bind("<ButtonPress-1>", self._on_vel_down, add="+")
        self.cv.bind("<B1-Motion>", self._on_vel_drag, add="+")
        self.cv.bind("<ButtonRelease-1>", self._on_vel_up, add="+")

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
                self.root.after(450, self._push_config)
                self.root.after(500, self._push_bank)
            except Exception as e:
                self.cv.itemconfigure(self.top["port"],
                                      text=f"Port {self.port}: ERREUR {e}")

        # premier affichage
        self.root.after(30, self._tick)
        self.root.mainloop()

    # ------------------------------------------------------------- structure
    def _box(self, x, y, w, h, title=None, dy=0):
        # Sérigraphie crème façon Model D : simple cadre imprimé SUR la
        # plaque, sans remplissage — la texture du métal brossé (peinte par
        # _paint_background) reste visible dessous, comme sur le vrai panneau.
        cv = self.cv
        y = y + dy
        cv.create_rectangle(x - 1, y - 1, x + w + 1, y + h + 1,
                            outline=PANEL_EDGE, width=1)
        cv.create_rectangle(x, y, x + w, y + h, outline=SILK, width=1)
        if title:
            cv.create_text(x + 14, y + 16, text=title,
                           font=("Helvetica", 10, "bold"),
                           fill="#ffd24a", anchor="w")

    def knob(self, key, x, y, label, lo=0.0, hi=1.0, fmt="{:.2f}", wave=None,
             norm=None, help=None, accent=None):
        y = y + self.BODY_DY
        self.knobs[key] = Knob(self.cv, x, y, label, lo=lo, hi=hi, fmt=fmt,
                               wave=wave, norm=norm, accent=accent)
        if help:
            self._tips.append((x - 38, y - 50, x + 38, y + 46, help))

    def switch(self, key, x, y, label, states=None, blink_txt="PATCH",
               help=None, color=MD_WHITE, orient="h"):
        y = y + self.BODY_DY
        self.switches[key] = SwitchOn(self.cv, x, y, label, states=states,
                                      blink_txt=blink_txt, color=color,
                                      orient=orient)
        if help:
            self._tips.append((x - 32, y - 14, x + 32, y + 54, help))

    # ------------------------------------------------------------- tooltips
    def _tip_motion(self, event):
        """Affiche la bulle du contrôle sous le pointeur (test du canvas).
        Le texte peut être une chaîne ou un callable (résolu à l'affichage)
        pour rester à jour si la config des CC change."""
        cur = None
        for (x1, y1, x2, y2, text) in self._tips:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cur = text() if callable(text) else text
                break
        if cur != self._tip_last:
            self._tip_last = cur
            if cur:
                self.tt.show(cur, event.x_root, event.y_root)
            else:
                self.tt.hide()

    def _tip_clear(self):
        self._tip_last = None
        self.tt.hide()

    def _btn_tip(self, widget, text):
        """Attache une bulle à un vrai widget Tk (bouton, liste...).
        `text` peut être une chaîne ou un callable."""
        if widget is None:
            return

        def _show(e):
            t = text() if callable(text) else text
            self.tt.show(t, e.x_root, e.y_root)

        widget.bind("<Enter>", _show)
        widget.bind("<Motion>", _show)
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

    # ------------------------------------------------------- config MIDI (CC)
    def _load_config(self):
        """Charge la config MIDI depuis config.json (complète les manquants)."""
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in DEFAULT_CONFIG:
                if k in data:
                    v = int(data[k])
                    if 0 <= v <= 127:
                        cfg[k] = v
        except Exception:
            pass
        return cfg

    def _save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _cc(self, key):
        """Numéro de CC courant (config.json) — utilisé par les bulles d'aide
        pour qu'elles restent à jour quand la config change."""
        try:
            return int(self.config.get(key, DEFAULT_CONFIG[key]))
        except Exception:
            return int(DEFAULT_CONFIG[key])

    def _push_config(self):
        """Envoie la table des CC au firmware (commande 'C mw,md,vd,lb,pl')."""
        if not (self.ser and getattr(self.ser, "is_open", False)):
            return
        try:
            vals = ",".join(str(int(self.config[k])) for k in CC_ORDER)
            self.ser.write(("C %s\n" % vals).encode())
            self.ser.flush()
        except Exception:
            pass

    def _open_config(self):
        """Ouvre la boîte de dialogue de paramétrage des CC MIDI."""
        dlg = getattr(self, "_cfg_dlg", None)
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.focus_force()
            return
        dlg = tk.Toplevel(self.root)
        self._cfg_dlg = dlg
        dlg.title("CONFIG — CC MIDI")
        dlg.configure(bg="#1c2128")
        dlg.resizable(False, False)
        dlg.transient(self.root)

        tk.Label(dlg, text="Correspondance des CC MIDI", bg="#1c2128",
                 fg="#ffd24a", font=("Helvetica", 13, "bold")
                 ).grid(row=0, column=0, columnspan=3, sticky="w",
                        padx=18, pady=(14, 0))
        tk.Label(dlg, text="Numéros 0..127 (identiques au clavier maître). "
                 "Enregistré dans config.json puis envoyé\nau synthé (commande "
                 "C) : aucun reflash nécessaire.",
                 justify="left", bg="#1c2128", fg="#9aa3ad",
                 font=("Helvetica", 8)).grid(row=1, column=0, columnspan=3,
                                             sticky="w", padx=18, pady=(2, 10))

        vars_ = {}
        for r, (key, label) in enumerate(CC_LABELS, start=2):
            tk.Label(dlg, text=label, bg="#1c2128", fg="#e8e4dc",
                     font=("Helvetica", 10), anchor="w"
                     ).grid(row=r, column=0, sticky="w", padx=(18, 10), pady=3)
            var = tk.IntVar(value=int(self.config.get(key,
                                                      DEFAULT_CONFIG[key])))
            vars_[key] = var
            tk.Spinbox(dlg, from_=0, to=127, width=5, textvariable=var,
                       font=("Courier", 12, "bold"), justify="center",
                       bg="#2b313a", fg="#e8e4dc",
                       buttonbackground="#39414a", relief="flat",
                       highlightthickness=0, insertbackground="#e8e4dc"
                       ).grid(row=r, column=1, sticky="e", padx=(0, 6), pady=3)

        # Rappel des CC réellement actifs dans le firmware (si la trame les
        # renvoie) : permet de repérer une éventuelle désynchro.
        fw = (getattr(self, "_last", None) or {}).get("cc_fw")
        fw_txt = " / ".join(str(x) for x in fw) if (fw and len(fw) == 5) else "—"
        base = 2 + len(CC_LABELS)
        tk.Label(dlg, text="CC actifs dans le firmware : " + fw_txt,
                 bg="#1c2128", fg="#7fb3ff", font=("Courier", 8)
                 ).grid(row=base, column=0, columnspan=3, sticky="w",
                        padx=18, pady=(10, 0))

        bar = tk.Frame(dlg, bg="#1c2128")
        bar.grid(row=base + 1, column=0, columnspan=3, pady=12)

        def set_defaults():
            for k, v in DEFAULT_CONFIG.items():
                vars_[k].set(v)

        for txt, bgc, cmd in (
                ("Défauts", "#37474f", set_defaults),
                ("Annuler", "#5a3a3a", self._close_cfg),
                ("Enregistrer", "#2e7d32", lambda: self._save_cfg(vars_))):
            tk.Button(bar, text=txt, command=cmd, bg=bgc, fg="#ffffff",
                      relief="raised", bd=2, padx=10, pady=2,
                      cursor="hand2").pack(side="left", padx=4)

        dlg.protocol("WM_DELETE_WINDOW", self._close_cfg)
        dlg.update_idletasks()
        try:
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            dw, dh = dlg.winfo_width(), dlg.winfo_height()
            dlg.geometry("+%d+%d" % (rx + max(0, (rw - dw) // 2),
                                     ry + max(0, (rh - dh) // 2)))
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

    def _close_cfg(self):
        dlg = getattr(self, "_cfg_dlg", None)
        if dlg is not None:
            try:
                dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass
        self._cfg_dlg = None

    def _save_cfg(self, vars_):
        labels = dict(CC_LABELS)
        new = {}
        for k in CC_ORDER:
            try:
                v = int(vars_[k].get())
            except Exception:
                v = -1
            if not (0 <= v <= 127):
                messagebox.showerror(
                    "CONFIG — valeur invalide",
                    "Le CC de « %s » doit être un nombre entre 0 et 127."
                    % labels[k], parent=self.root)
                return
            new[k] = v
        vals = list(new.values())
        if len(set(vals)) != len(vals):
            if not messagebox.askyesno(
                    "CONFIG — CC en double",
                    "Deux fonctions partagent le même CC. Continuer quand "
                    "même ?", parent=self.root):
                return
        self.config = new
        self._save_config()
        self._push_config()
        self._close_cfg()

    def _patch_to_line(self, p):
        """Convertit un dict patch (JSON) en ligne CSV pour la commande B du
        firmware. Ordre : nom,w1,r1,w2,r2,w3,r3,v1,v2,v3,vN,fr2,fr3,cut,res,
        amt,fAtk,fDec,fSus,lAtk,lDec,lSus,glide,modMix,reverb,revType,s0..s12,
        extVol,dlyLevel,dlyType"""
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
        # dlyLevel / dlyType en FIN de ligne, après extVol (champs optionnels
        # côté firmware) : niveau mémoire du delay et durée choisie par ENC2.
        dly = max(0.0, min(1.0, float(p.get("dlyLevel", 0.0))))
        return "B " + nom + "," + \
            ",".join(str(x) for x in [w[0], r[0], w[1], r[1], w[2], r[2]]) + \
            "," + ",".join(f) + "," + \
            str(int(p.get("revtype", 0))) + "," + ",".join(s) + \
            ",{:.3f}".format(ext) + ",{:.3f}".format(dly) + \
            "," + str(int(p.get("dlyType", 0)))

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
            # Niveau et durée du delay, tels qu'émis dans la trame P.
            "dlyLevel": max(0.0, min(1.0, d.get("delaylevel", 0.0))),
            "dlyType": int(d.get("delaytype", 0) or 0),
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
        try:
            sel = [p.get("nom", "?") for p in self.patches].index(
                self.patch_var.get())
        except ValueError:
            sel = -1
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
        self._seq_ui_idle()
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
            # Le reboot remet la table des CC aux valeurs d'usine : re-pousser.
            self.root.after(450, self._push_config)
            self.root.after(500, self._push_bank)
        except Exception:
            print("[GUI] Échec du reset série")
            pass

    def _refresh_patch_list(self):
        try:
            names = [p.get("nom", f"PATCH{i+1}") for i, p in enumerate(self.patches)]
            menu = self.patch_combo["menu"]
            menu.delete(0, "end")
            for n in names:
                menu.add_command(label=n,
                                 command=lambda v=n: self.patch_var.set(v))
            if names:
                self.patch_var.set(names[0])
        except Exception:
            pass

    def _build_patch_widgets(self):
        names = [p.get("nom", "?") for p in self.patches] or ["—"]
        self.patch_var = tk.StringVar(value=names[0])
        self.patch_combo = tk.OptionMenu(self.root, self.patch_var, *names)
        self.patch_combo.configure(font=("Helvetica", 9), bg="#2a2f36",
                                   fg="#ffffff", activebackground="#3a4048",
                                   activeforeground="#ffffff", bd=1,
                                   highlightthickness=0, width=12)
        self.patch_combo["menu"].configure(font=("Helvetica", 9))
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

    # ----------------------------------------------------------- séquences
    def _load_sequences(self):
        """Charge sequences.json (créé avec les riffs par défaut si absent)."""
        if not os.path.exists(SEQUENCES_FILE):
            try:
                with open(SEQUENCES_FILE, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_SEQUENCES, f, ensure_ascii=False,
                              indent=2)
            except Exception:
                pass
        try:
            with open(SEQUENCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            seqs = data.get("sequences")
            if isinstance(seqs, list) and seqs:
                return seqs
        except Exception:
            pass
        return [dict(s) for s in DEFAULT_SEQUENCES["sequences"]]

    def _build_sequence_widgets(self):
        """Menu DÉMO (bande du haut) : sélectionne un riff, charge le patch
        le plus adapté de la banque puis lance la séquence dans le firmware."""
        cv = self.cv
        cv.create_text(330, 130, text="Démo", anchor="w",
                       font=("Helvetica", 9, "bold"), fill="#ffd24a")
        names = [s.get("nom", f"SEQ{i + 1}")
                 for i, s in enumerate(self.sequences)] or ["—"]
        self.seq_var = tk.StringVar(value=names[0])
        self.seq_menu = tk.OptionMenu(self.root, self.seq_var, *names)
        self.seq_menu.configure(font=("Helvetica", 9), bg="#2a2f36",
                                fg="#ffffff", activebackground="#3a4048",
                                activeforeground="#ffffff", bd=1,
                                highlightthickness=0, width=40)
        self.seq_menu["menu"].configure(font=("Helvetica", 9))
        cv.create_window(560, 130, window=self.seq_menu, anchor="center")
        self.seq_btn = tk.Button(
            self.root, text="▶ JOUER", font=("Helvetica", 9, "bold"),
            bg="#00838f", fg="#ffffff", activebackground="#00acc1",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=8, pady=1, cursor="hand2", command=self._toggle_sequence)
        cv.create_window(800, 130, window=self.seq_btn, anchor="center")
        self.top["seqpatch"] = cv.create_text(
            855, 130, text="", anchor="w", font=("Helvetica", 8, "bold"),
            fill="#7cd4ff")
        self._btn_tip(self.seq_menu, "DÉMO : courts riffs classiques du "
                      "Minimoog (sequences.json — éditable). Le patch est "
                      "choisi automatiquement selon le profil du riff.")
        self._btn_tip(self.seq_btn, "JOUER/STOP : charge le patch le plus "
                      "adapté de la banque (sélection par profil), puis joue "
                      "le riff UNE fois (arrêt automatique en fin de motif). "
                      "Recliquer interrompt tout de suite (commande A).")

    def _sequence_line(self, seq):
        """Construit la ligne série 'N n<note>s<durée> …' d'une séquence."""
        toks = []
        for item in seq.get("notes", []):
            try:
                n, d = int(item[0]), float(item[1])
            except Exception:
                continue
            if 0 <= n <= 127 and d > 0:
                toks.append("n%ds%g" % (n, d))
        return ("N " + " ".join(toks)) if toks else None

    def _sequence_ms(self, seq):
        """Durée d'une passe, calquée sur tacheSequence() : chaque note dure
        ceil(d*1000/20)*20 ms, plus 30 ms de blanc entre les notes."""
        total = 0
        for item in seq.get("notes", []):
            try:
                d = float(item[1])
            except Exception:
                continue
            if d <= 0:
                continue
            dur = int(d * 1000)               # troncature, comme le firmware
            total += ((dur + 19) // 20) * 20 + 30
        return total

    def _toggle_sequence(self):
        if getattr(self, "_seq_playing", False):
            self._stop_sequence()
        else:
            self._play_sequence()

    def _play_sequence(self):
        """Charge le patch le plus adapté à la séquence, puis la joue une fois."""
        if self.demo or getattr(self, "_midi_estActive", False):
            return
        if not (self.ser and getattr(self.ser, "is_open", False)):
            return
        nom = self.seq_var.get()
        seq = next((s for s in self.sequences if s.get("nom") == nom), None)
        if seq is None:
            return
        line = self._sequence_line(seq)
        if line is None:
            return
        profil = seq.get("profil", "")
        patch = best_patch(self.patches, profil)
        pnom = patch.get("nom") if patch else None
        try:
            if pnom:
                self.ser.write(("L %s\n" % pnom).encode())
            self.ser.write((line + "\n").encode())
            self.ser.flush()
        except Exception:
            return
        self._seq_playing = True
        self.seq_btn.configure(text="■ STOP", bg="#c0392b",
                               activebackground="#ff6b5e")
        if pnom:
            self.cv.itemconfigure(self.top["patch"], text=f"Patch: {pnom}")
            self.cv.itemconfigure(
                self.top["seqpatch"], text="→ %s (%s)" % (pnom, profil))
        # Arrêt automatique : une passe exactement. Le firmware a jusqu'à 50 ms
        # de latence de démarrage, donc on borne à la durée du motif : le
        # deuxième passage n'est jamais entamé (la dernière note peut être
        # tronquée de quelques ms selon la latence).
        if self._seq_after is not None:
            try:
                self.root.after_cancel(self._seq_after)
            except Exception:
                pass
        self._seq_after = self.root.after(
            max(200, self._sequence_ms(seq)), self._stop_sequence)

    def _stop_sequence(self):
        self._seq_ui_idle()
        try:
            if self.ser and getattr(self.ser, "is_open", False):
                self.ser.write(b"A\n")
                self.ser.flush()
        except Exception:
            pass

    def _seq_ui_idle(self):
        """Remet le bouton SÉQUENCE à l'arrêt et annule l'arrêt programmé."""
        self._seq_playing = False
        if getattr(self, "_seq_after", None) is not None:
            try:
                self.root.after_cancel(self._seq_after)
            except Exception:
                pass
            self._seq_after = None
        try:
            self.seq_btn.configure(text="▶ JOUER", bg="#00838f",
                                   activebackground="#00acc1")
            self.cv.itemconfigure(self.top["seqpatch"], text="")
        except Exception:
            pass

    def _paint_background(self):
        """Fond façon Model D : cabinet en noyer dans les marges, plaque
        d'aluminium anodisé noir brossé au centre. Peinte une seule fois, au
        tout début de _build_panel() — graine fixe, rendu identique à chaque
        lancement. _box() ne pose ensuite que la sérigraphie crème."""
        cv = self.cv
        rnd = random.Random(1971)   # 1971 : sortie du Minimoog Model D
        W, H = self.W, self.H

        # 1) Cabinet en noyer : aplat + fibres horizontales ondulées
        cv.create_rectangle(0, 0, W, H, fill=WOOD_BASE, width=0)
        for _ in range(150):
            base = rnd.uniform(-6, H + 6)
            amp = rnd.uniform(1.0, 5.0)
            col = rnd.choice(WOOD_DARK if rnd.random() < 0.55 else WOOD_LIGHT)
            pts, x, y = [], -12.0, base
            while x < W + 12:
                pts.extend([x, y])
                x += rnd.uniform(70, 180)
                y = base + rnd.uniform(-amp, amp)
            pts.extend([W + 12, y])
            cv.create_line(*pts, smooth=True, fill=col,
                           width=rnd.choice((1, 1, 1, 2)), capstyle="round")

        # 2) Plaque d'aluminium anodisé : aplat sombre + tranche
        px1, py1, px2, py2 = PANEL_BOX
        cv.create_rectangle(px1, py1, px2, py2, fill=PANEL_FILL,
                            outline=PANEL_EDGE, width=1)

        # 3) Brossage horizontal fin : traits discontinus, teintes très proches
        #    du fond — c'est le grain qui fait « métal » et non le contraste.
        y = float(py1) + 2.0
        while y < py2 - 1:
            d = rnd.random()
            if d < 0.34:
                xa, xb = float(px1), float(px2)
                if rnd.random() < 0.30:
                    xa += rnd.uniform(60, 700)
                if rnd.random() < 0.30:
                    xb -= rnd.uniform(60, 700)
                cv.create_line(xa, y + rnd.uniform(-0.7, 0.7),
                               xb, y + rnd.uniform(-0.7, 0.7),
                               fill=rnd.choice(PANEL_BRUSH_LIGHT), width=1)
            elif d < 0.56:
                cv.create_line(px1, y + rnd.uniform(-0.7, 0.7),
                               px2, y + rnd.uniform(-0.7, 0.7),
                               fill=rnd.choice(PANEL_BRUSH_DARK), width=1)
            y += 2.5

        # 4) Grain de surface (poudre martelée) : stries courtes horizontales
        for _ in range(320):
            sx = rnd.uniform(px1, px2)
            sy = rnd.uniform(py1, py2)
            cv.create_line(sx, sy, sx + rnd.uniform(2, 6), sy,
                           fill=rnd.choice(PANEL_GRAIN), width=1)

        # 5) Vis du panneau, dans les marges en bois
        for (sx, sy) in PANEL_SCREWS:
            cv.create_oval(sx - 6, sy - 6, sx + 6, sy + 6,
                           fill="#6f747b", outline="#2a2c30", width=1)
            cv.create_oval(sx - 4, sy - 4, sx + 4, sy + 4,
                           fill="#8b9098", outline="#565a61", width=1)
            a = rnd.uniform(0.0, math.pi)
            r = 3.4
            cv.create_line(sx - r * math.cos(a), sy - r * math.sin(a),
                           sx + r * math.cos(a), sy + r * math.sin(a),
                           fill="#33363b", width=2, capstyle="round")

    def _build_panel(self):
        self._paint_background()
        cv = self.cv
        self._box(30, 30, 1440, 76, "MINIMOOG MODEL D — état temps réel")
        dy = self.BODY_DY
        self._box(30, 120, 310, 520, "MOD / GLIDE / OUT", dy=dy)
        self._box(365, 120, 420, 520, "OSCILLATOR BANK", dy=dy)
        self._box(805, 120, 310, 520, "MIXER", dy=dy)
        self._box(1135, 120, 335, 300, "FILTER", dy=dy)
        self._box(1135, 440, 335, 200, "LOUDNESS", dy=dy)
        self._box(30, 660, 1440, 185, dy=dy)

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

        # --- Bouton CONFIG : paramétrage des CC MIDI (config.json). Ouvre une
        # boîte de dialogue ; la table est poussée au firmware (commande C).
        self.cfg_btn = tk.Button(
            self.root, text="CONFIG", font=("Helvetica", 9, "bold"),
            bg="#4527a0", fg="#ffffff", activebackground="#5e35b1",
            activeforeground="#ffffff", relief="raised", bd=2,
            padx=8, pady=1, cursor="hand2", command=self._open_config)
        cv.create_window(150, 130, window=self.cfg_btn, anchor="center")
        self._btn_tip(self.cfg_btn, "CONFIG : correspondance des CC MIDI "
                      "(molette, mod depth, vel filt, LED bright, chargement de "
                      "patch). Enregistrée dans config.json et poussée au "
                      "firmware (commande C) — modifiable sans reflash.")

        # --- Mod/Glide/Out (x 30..340) — 2 colonnes, lu de bas en haut puis
        # colonne suivante, pour suivre les câblages réels sur l'ESP32 :
        #   col1 (x=95)  : MOD MIX 210, GLIDE 330, GLIDE ON 450, DECAY 570
        #   col2 (x=235) : MOD OSC 210, CTRL OSC3 330, REVERB 450, écran 540+
        # Le bloc reverb (pot J50 + afficheur) reste en bas à droite.
        self.switch("decay", 95, 570, "DECAY",
                     color=MD_WHITE,
                    help="DECAY : réglage des temps de déclin des enveloppes.")
        self.switch("glideOn", 95, 450, "GLIDE ON",
                     color=MD_WHITE,
                    help="GLIDE ON : active le glissement tonal (portamento) "
                         "entre les notes jouées en séquence.")
        self.knob("glide", 95, 330, "GLIDE", fmt="{:.0%}",
                  help="GLIDE (portamento) : temps de glissement de fréquence "
                       "entre deux notes. Nécessite le switch GLIDE ON.")
        self.knob("modmix", 95, 210, "MOD MIX", fmt="{:.0%}",
                  help="MOD MIX : quantité de modulation provenant du VCO3/LFO "
                       "(envoyée vers la hauteur, le filtre et le volume).")
        self.switch("ctrlOsc3", 235, 330, "CTRL OSC3",
                     color=MD_ORANGE, orient="v",
                    help="CTRL OSC3 : passe le VCO3 en mode contrôle (LFO) au "
                         "lieu d'une oscillation audible.")
        self.switch("modOsc", 235, 210, "MOD OSC",
                     color=MD_ORANGE,
                    help="MOD OSC : achemine la sortie du VCO3 vers la chaîne "
                         "de modulation (vibrato / filtre / gain).")
        # Pot REVERB dédié (J50, Mux2/C14) : reste dans ce panneau.
        self.knob("reverb", 235, 450, "REVERB", fmt="{:.0%}",
                  help="J50 : pot PARTAGÉ REVERB / DELAY. Le libellé suit la "
                       "cible courante — ENC2 en mode 2 = reverb, mode 3 = "
                       "delay (la LED VCO2 clignote) — et chaque effet garde "
                       "son propre niveau mémoire : en changeant de mode le "
                       "pot ne reprend la main qu'en le tournant. 0 % = effet "
                       "coupé. La rotation de ENC2 choisit ensuite l'algorithme "
                       "(ROOM/HALL/PLATE/SPRING) ou la durée "
                       "(60/120/240/480 ms).")
        # Indicateur reverb façon écran 80s : valeur en % (ambre), LED de
        # service, label en dessous.
        self.top["revPanel"] = cv.create_rectangle(
            193, 540 + dy, 277, 580 + dy, fill="#0e1116", outline="#4a525b",
            width=2)
        cv.create_rectangle(199, 546 + dy, 271, 574 + dy, outline="#1c262f",
                            width=1)
        self.top["revLed"] = cv.create_oval(
            202, 556 + dy, 212, 566 + dy, fill="#3a4048", outline="#1a2b33")
        self.top["revValue"] = cv.create_text(
            235, 564 + dy, text="00%", font=("Courier", 16, "bold"),
            fill="#ffb14a")
        self.top["revGlow"] = []
        for gx, gy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            self.top["revGlow"].append(cv.create_text(
                235 + gx, 564 + dy + gy, text="00%",
                font=("Courier", 16, "bold"), fill="#5a2a00"))
        self.top["revUnit"] = cv.create_text(
            258, 549 + dy, text="REV", font=("Helvetica", 7), fill="#7a828b")
        self.top["rev"] = cv.create_text(
            235, 592 + dy, text="REVERB off", font=("Helvetica", 8, "bold"),
            fill="#3a4048")
        self.top["revType"] = cv.create_text(
            235, 606 + dy, text="", font=("Courier", 8, "bold"),
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
                     color=MD_BLUE,
                    help="Envoie l'oscillateur 1 au mixer.")
        self.switch("mixOn2", 970, 330, "OSC2",
                     color=MD_BLUE,
                    help="Envoie l'oscillateur 2 au mixer.")
        self.switch("mixOn3", 970, 450, "OSC3",
                     color=MD_BLUE,
                    help="Envoie l'oscillateur 3 au mixer.")
        self.switch("mixOnN", 970, 570, "NOISE",
                     color=MD_BLUE,
                    help="Envoie le bruit au mixer.")
        self.switch("typeNoise", 1050, 450, "NOISE TYPE",
                     color=MD_BLACK, orient="v",
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
        # LED OVERLOAD (GUI seulement) : à droite du potar EXT VOL, rouge quand
        # le mixer sature (estimation — voir _update_overload).
        self.top["ovlGlow"] = cv.create_oval(
            1093 - 8, 570 + dy - 8, 1093 + 8, 570 + dy + 8, fill="",
            outline="")
        self.top["ovlLed"] = cv.create_oval(
            1093 - 5, 570 + dy - 5, 1093 + 5, 570 + dy + 5,
            fill="#3a2020", outline="#1a0d0d", width=1)
        self.top["ovlTxt"] = cv.create_text(
            1093, 588 + dy, text="OVLD", font=("Helvetica", 7, "bold"),
            fill="#7a828b")
        self._tips.append((1063, 544 + dy, 1120, 598 + dy,
                           "OVERLOAD : lampe de saturation de sortie (façon "
                           "Model D). La GUI ne reçoit pas l'audio : elle "
                           "estime le niveau par la somme des sources actives "
                           "du mixer (OSC1/2/3, bruit, feedback EXT) pondérée "
                           "par l'enveloppe LOUDNESS. Rouge = ça sature."))
        # groupés verticalement, alignés sur la zone filter (ils agissent dessus)
        self.switch("filtMod", 1062, 210, "FILT MOD",
                     color=MD_ORANGE,
                    help="FILT MOD : applique la modulation (molette MOD, VCO3 "
                         "en LFO) au filtre.")
        self.switch("kbd1", 1062, 265, "KBD CTL1",
                     color=MD_WHITE,
                    help="KBD CTL1 : le clavier pilote la fréquence de coupure "
                         "du filtre (1 V/octave, façon Model D).")
        self.switch("kbd2", 1062, 330, "KBD CTL2",
                     color=MD_WHITE,
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
                  help=lambda: (
                       "CONTOUR : profondeur du contrôle de l'enveloppe de "
                       "filtre sur la coupure. La vélocité des notes MIDI la "
                       "module en dessous (courbe racine carrée : une frappe "
                       "légère pèse déjà), atténuée par la jauge VEL FILT "
                       "(CC%d). 0 %% = vélocité ignorée, 100 %% = note douce "
                       "→ ~10 %% du CONTOUR, note franche → valeur affichée. "
                       "Extension : le Model D d'origine n'a pas de vélocité."
                       % self._cc("cc_veldepth")))
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
                405, y + dy, text=f"VCO {i+1}", font=("Helvetica", 10, "bold"),
                fill="#d8d8d8")
            push_help = ("rappelle un patch de la banque (mode PATCH, "
                         "LED clignote)."
                         if i != 1 else
                         "passe de reverb à delay (LED clignote) : la rotation "
                         "choisit alors l'algorithme ROOM/HALL/PLATE/SPRING ou "
                         "la durée 60/120/240/480 ms ; le niveau des deux "
                         "effets reste sur le pot partagé J50.")
            self.knob(f"wave{i}", 475, y, "WAVEFORM", lo=0, hi=5,
                      fmt=lambda v: WAVES[int(v)], wave=1,
                      help=f"WAVEFORM du VCO {i+1} : Tri / Tri-Saw / Scie / "
                           "Carré / Imp30 / Imp15.")
            self.switch(f"vco{i}sw", 580, y, "PUSH",
                         color=MD_WHITE,
                        blink_txt="PATCH" if i == 0 else ("REVERB" if i == 1 else "PATCH"),
                        help=f"PUSH (VCO {i+1}) : bouton poussoir — " + push_help)
            self.knob(f"range{i}", 660, y, "RANGE", lo=1, hi=6,
                      fmt=lambda v: RANGES[int(v) - 1],
                      help=f"RANGE du VCO {i+1} : gamme 32' (grave) → 2' (aigu) "
                           "+ Lo (note la plus grave).")
            if has_det:
                # Teintes distinctes : OSC2 = violet, OSC3 = orange — les deux
                # potards sont identiques physiquement, on les distingue ici
                # par l'étiquette, l'échelle, la couronne et l'index. (Le violet
                # évite la confusion avec le cyan du mode gel de patch.)
                self.knob(f"det{i}", 730, y, f"FREQ OSC{i+1}",
                          lo=-7, hi=7, fmt="{:+.1f} st",
                          accent=("#b06bff", "#ff8c3a")[i - 1],
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
        self.pitchw = Wheel(self.cv, 140, 682 + dy, 52, 136, "PITCH",
                            lo=-2.0, hi=2.0, color="#ffd24a",
                            fmt="{:+.1f} st", detent=True)
        self.modw = Wheel(self.cv, 205, 682 + dy, 52, 136, "MOD",
                          lo=0.0, hi=1.0, color="#7cd4ff", fmt="{:.0%}")
        # Atténuateur de modulation = pot "Mod Depth" du Model D (CC3, knob K1
        # du MPK249) : il borne la profondeur MAX de la molette. Jauge compacte
        # sous la molette MOD (elle n'a pas de pot physique sur le panneau).
        self.cv.create_text(205, 862 + dy, text="MOD DEPTH",
                            font=("Helvetica", 8), fill="#8b939c")
        self.cv.create_rectangle(140, 872 + dy, 270, 878 + dy, fill="#1b1f25",
                                 outline="#2f353c")
        self.moddep_bar = self.cv.create_rectangle(142, 874 + dy, 142, 876 + dy,
                                                   fill="#7cd4ff", outline="")
        self.moddep_val = self.cv.create_text(205, 890 + dy, text="",
                                               font=("Helvetica", 8, "bold"),
                                               fill="#d8d8d8")
        # Atténuateur vélocité -> CONTOUR (CC9, knob du MPK249) : même
        # principe que MOD DEPTH. 0 % = la vélocité est ignorée, 100 % = une
        # note douce n'ouvre presque pas l'enveloppe de coupure.
        self.cv.create_text(400, 862 + dy, text="VEL FILT",
                            font=("Helvetica", 8), fill="#8b939c")
        self.cv.create_rectangle(335, 872 + dy, 465, 878 + dy, fill="#1b1f25",
                                 outline="#2f353c")
        self.velf_bar = self.cv.create_rectangle(337, 874 + dy, 337, 876 + dy,
                                                 fill="#7cd4ff", outline="")
        self.velf_val = self.cv.create_text(400, 890 + dy, text="",
                                            font=("Helvetica", 8, "bold"),
                                            fill="#d8d8d8")
        # Luminosité des 3 LEDs physiques d'encodeur (OSC1/2/3) : curseur
        # horizontal cliquable/glissable. Envoie la commande série W<0-100>
        # au firmware (PWM LEDC) ; réglable aussi au clavier maître via CC14
        # (la position est alors renvoyée par la trame P).
        self.cv.create_text(595, 862 + dy, text="LED BRIGHT",
                            font=("Helvetica", 8), fill="#8b939c")
        self.cv.create_rectangle(530, 872 + dy, 660, 878 + dy, fill="#1b1f25",
                                 outline="#2f353c")
        self.led_bar = self.cv.create_rectangle(532, 874 + dy, 532, 876 + dy,
                                                fill="#e8e4dc", outline="")
        self.led_val = self.cv.create_text(595, 890 + dy, text="",
                                           font=("Helvetica", 8, "bold"),
                                           fill="#d8d8d8")
        self.kbd = Keyboard(self.cv, 275, 695 + dy, 1150, 120, midi0=36,
                            midi1=84, note_cb=self._play_key)
        self.pitchw.update(0.0)
        self.modw.update(0.05)
        self._led_ui(self._led_val)
        self._mod_ui(self._mod_val)
        self._vel_ui(self._vel_val)

        # --- Bulles d'aide des zones dessinées (wheels, clavier, reverb)
        self._tips.append((110, 668 + dy, 170, 846 + dy,
                           "PITCH (lecture) : pitch bend ±7 demi-tons venant "
                           "du clavier maître (MIDI)."))
        self._tips.append((175, 668 + dy, 235, 846 + dy, lambda: (
                           "MOD : position de la molette de modulation (CC%d) "
                           "du clavier maître — vibrato par le VCO3/LFO et "
                           "ouverture du filtre. 100 %% = pleine course de la "
                           "molette." % self._cc("cc_modwheel"))))
        self._tips.append((138, 848 + dy, 272, 900 + dy, lambda: (
                           "MOD DEPTH (CC%d) : atténuateur de la molette de "
                           "modulation — borne la profondeur max (vibrato et "
                           "filtre). Cliquer ou glisser pour régler (commande D)."
                           % self._cc("cc_moddepth"))))
        self._tips.append((335, 848 + dy, 467, 900 + dy, lambda: (
                           "VEL FILT (CC%d) : att\u00e9nuateur "
                           "de la v\u00e9locit\u00e9 sur le CONTOUR du filtre. 0 %% = "
                           "v\u00e9locit\u00e9 ignor\u00e9e, 100 %% = note douce -> peu "
                           "d'enveloppe, note franche -> course pleine. Cliquer "
                           "ou glisser pour régler (commande D)."
                           % self._cc("cc_veldepth"))))
        self._tips.append((190, 535 + dy, 280, 614 + dy,
                           "EFFETS : niveau par le pot J50 "
                           "partagé (juste au-dessus) — REVERB en mode 2 de "
                           "ENC2, DELAY en mode 3 (la LED VCO2 clignote). Les "
                           "deux niveaux sont mémorisés séparément. La rotation "
                           "de ENC2 choisit l'algorithme (ROOM/HALL/PLATE/"
                           "SPRING) ou la durée (60/120/240/480 ms)."))
        self._tips.append((525, 848 + dy, 665, 894 + dy, lambda: (
                           "LED BRIGHT : luminosité des 3 "
                           "LEDs physiques des encodeurs (OSC1/2/3) sur "
                           "l'ESP32. Cliquer ou glisser pour régler (commande "
                           "série W0-100) ; réglable aussi en MIDI par CC%d "
                           "depuis le clavier maître. 0 %% = LEDs éteintes."
                           % self._cc("cc_ledbright"))))

    # ------------------------------------------------------- curseur LED BRIGHT
    def _led_ui(self, t):
        """Redessine la barre + la valeur du curseur LED BRIGHT (0..1)."""
        t = max(0.0, min(1.0, t))
        self._led_val = t
        self.cv.coords(self.led_bar, 532, 874 + self.BODY_DY,
                       532 + 128 * t, 876 + self.BODY_DY)
        self.cv.itemconfigure(self.led_bar,
                              fill="#e8e4dc" if t > 0.004 else "#39414a")
        self.cv.itemconfigure(self.led_val,
                              text=f"{t:.0%}",
                              fill="#d8d8d8" if t > 0.004 else "#5a6470")

    def _in_led_slider(self, x, y):
        return 528 <= x <= 662 and 856 + self.BODY_DY <= y <= 896 + self.BODY_DY

    def _led_from_x(self, x):
        t = (x - 530) / 130.0
        return max(0.0, min(1.0, t))

    def _on_led_down(self, event):
        if not self._in_led_slider(event.x, event.y):
            return
        self._led_drag = True
        self._apply_led(self._led_from_x(event.x))

    def _on_led_drag(self, event):
        if getattr(self, "_led_drag", False):
            self._apply_led(self._led_from_x(event.x))

    def _on_led_up(self, event):
        if getattr(self, "_led_drag", False):
            self._led_drag = False
            self._apply_led(self._led_from_x(event.x))

    def _apply_led(self, t):
        self._led_ui(t)
        pct = int(round(t * 100))
        if pct == getattr(self, "_led_sent", -1):
            return  # n'émet que si le pourcent a réellement changé
        self._led_sent = pct
        if self.ser and getattr(self.ser, "is_open", False):
            try:
                self.ser.write(("W%d\n" % pct).encode())
                self.ser.flush()
            except Exception:
                pass

    # ------------------------------------------- curseurs MOD DEPTH / VEL FILT
    def _mod_ui(self, t):
        """Redessine la jauge MOD DEPTH (0..1), teinte cyan."""
        t = max(0.0, min(1.0, t))
        self._mod_val = t
        self.cv.coords(self.moddep_bar, 142, 874 + self.BODY_DY,
                       142 + 126 * t if t > 0.004 else 142.5,
                       876 + self.BODY_DY)
        self.cv.itemconfigure(self.moddep_bar,
                              fill="#7cd4ff" if t > 0.004 else "#39414a")
        self.cv.itemconfigure(self.moddep_val,
                              text=f"{t:.0%}",
                              fill="#d8d8d8" if t > 0.004 else "#5a6470")

    def _vel_ui(self, t):
        """Redessine la jauge VEL FILT (0..1), teinte ambre."""
        t = max(0.0, min(1.0, t))
        self._vel_val = t
        self.cv.coords(self.velf_bar, 337, 874 + self.BODY_DY,
                       337 + 126 * t if t > 0.004 else 337.5,
                       876 + self.BODY_DY)
        self.cv.itemconfigure(self.velf_bar,
                              fill="#ffb14a" if t > 0.004 else "#39414a")
        self.cv.itemconfigure(self.velf_val,
                              text=f"{t:.0%}",
                              fill="#d8d8d8" if t > 0.004 else "#5a6470")

    def _in_mod_slider(self, x, y):
        return 138 <= x <= 272 and 856 + self.BODY_DY <= y <= 896 + self.BODY_DY

    def _mod_from_x(self, x):
        return max(0.0, min(1.0, (x - 140) / 130.0))

    def _in_vel_slider(self, x, y):
        return 333 <= x <= 467 and 856 + self.BODY_DY <= y <= 896 + self.BODY_DY

    def _vel_from_x(self, x):
        return max(0.0, min(1.0, (x - 335) / 130.0))

    def _on_mod_down(self, event):
        if not self._in_mod_slider(event.x, event.y):
            return
        self._mod_drag = True
        self._apply_mod(self._mod_from_x(event.x))

    def _on_mod_drag(self, event):
        if getattr(self, "_mod_drag", False):
            self._apply_mod(self._mod_from_x(event.x))

    def _on_mod_up(self, event):
        if getattr(self, "_mod_drag", False):
            self._mod_drag = False
            self._apply_mod(self._mod_from_x(event.x))

    def _on_vel_down(self, event):
        if not self._in_vel_slider(event.x, event.y):
            return
        self._vel_drag = True
        self._apply_vel(self._vel_from_x(event.x))

    def _on_vel_drag(self, event):
        if getattr(self, "_vel_drag", False):
            self._apply_vel(self._vel_from_x(event.x))

    def _on_vel_up(self, event):
        if getattr(self, "_vel_drag", False):
            self._vel_drag = False
            self._apply_vel(self._vel_from_x(event.x))

    def _apply_mod(self, t):
        self._mod_ui(t)
        self._send_depths()

    def _apply_vel(self, t):
        self._vel_ui(t)
        self._send_depths()

    def _send_depths(self):
        """Émet 'D <mod%>,<vel%>' si le couple a changé (firmware : atténuateurs)."""
        md = int(round(self._mod_val * 100))
        vd = int(round(self._vel_val * 100))
        if (md, vd) == getattr(self, "_depth_sent", (-1, -1)):
            return
        self._depth_sent = (md, vd)
        if self.ser and getattr(self.ser, "is_open", False):
            try:
                self.ser.write(("D %d,%d\n" % (md, vd)).encode())
                self.ser.flush()
            except Exception:
                pass

    # ------------------------------------------------------------- données
    def _update_all(self, d, sw, locks=0):
        # Pot J50 partagé REVERB/DELAY : cible exactement celle du firmware
        # (fxCible) — ENC2 en mode 3 pilote le delay, sinon la reverb.
        actif_dly = int(d.get("modR1", 0) or 0) == 3
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
                locked = bool(locks & (1 << (LOCK_DELAY_BIT if actif_dly
                                             else LOCK_REVERB_BIT)))
            if idx and idx in d:
                val = d[idx]
                if name == "reverb" and actif_dly:
                    val = d.get("delaylevel", 0.0)
                k.update(val, locked)
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
                needle_fill, value_fill = "#efe9dc", "#ffd24a"
            else:
                needle_fill, value_fill = "#4a525b", "#5a6470"
            self.cv.itemconfigure(ek.idv["needle"], fill=needle_fill)
            self.cv.itemconfigure(ek.idv["value"], fill=value_fill)
        if "vco1sw" in self.switches:
            self.switches["vco1sw"].blink_txt = ("DELAY" if actif_dly
                                                 else "REVERB")
        for i in range(3):
            if f"vco{i}sw" in self.switches:
                self.switches[f"vco{i}sw"].update(d.get(f"modR{i}", 0))
        # ENC2 en mode 2 = REVERB : le push VCO2 ne change plus que le TYPE
        # d'algo. Le niveau est porté par son propre pot J50 (knob REVERB),
        # donc le knob OSC2 VOL affiche toujours le volume d'OSC2.
        if "vol2" in self.knobs:
            self.knobs["vol2"].fmt = "{:.2f}"
        # Indicateur FX façon écran 80s : il suit la cible courante du pot
        # J50 (reverb en mode ENC2 != 3, delay en mode ENC2 == 3). Les deux
        # niveaux restent mémoarisés de chaque côté, la ligne 1 les montre
        # tous les deux, la ligne 2 détaille l'FX actif.
        if "rev" in self.top:
            ron = d.get("reverb", 0.0) > 0.001
            don = d.get("delaylevel", 0.0) > 0.001
            on = don if actif_dly else ron
            lvl = d.get("delaylevel", 0.0) if actif_dly else d.get("reverb", 0.0)
            pct = max(0.0, min(1.0, lvl))
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
                self.top["revUnit"], text="FX",
                fill="#ffb14a" if on else "#7a828b")
            rp = int(round(max(0.0, min(1.0, d.get("reverb", 0.0))) * 100))
            dp = int(round(max(0.0, min(1.0, d.get("delaylevel", 0.0))) * 100))
            self.cv.itemconfigure(
                self.top["rev"],
                text="REV {:02d}%  DLY {:02d}%".format(rp, dp),
                fill="#c8ccd0" if (ron or don) else "#3a4048")
            if actif_dly:
                noms = ("60MS", "120MS", "240MS", "480MS")
                rt = int(d.get("delaytype", 0) or 0)
            else:
                noms = ("ROOM", "HALL", "PLATE", "SPRING")
                rt = int(d.get("revtype", 0) or 0)
            self.cv.itemconfigure(
                self.top["revType"], text=noms[rt % len(noms)],
                fill="#7cd4ff" if on else "#3a4048")
            # Libellé du pot J50 : il suit la cible, pas toujours « REVERB ».
            if "reverb" in self.knobs:
                self.cv.itemconfigure(
                    self.knobs["reverb"].idv["label"],
                    text="DELAY" if actif_dly else "REVERB")
        # Curseur LED BRIGHT : suit la valeur renvoyée par le firmware (CC14 ou
        # commande W) sauf pendant qu'on le fait glisser à la souris.
        if not getattr(self, "_led_drag", False):
            self._led_ui(max(0.0, min(1.0, d.get("ledbright", 0.5))))

    # ------------------------------------------------------------- overload
    def _update_overload(self, d, sw, gate):
        """LED OVERLOAD (GUI uniquement) : estime la saturation de sortie.

        La GUI ne reçoit pas l'audio ; on approche le niveau par la somme des
        sources actives du mixer (switchs OSC1/2/3 + NOISE), au feedback de
        l'entrée externe, le tout pondéré par une enveloppe LOUDNESS simulée
        localement (lAtk/lDec/lSus + tenue de note `gate`).
        """
        total = 0.0
        for idx, key in ((2, "vol1"), (3, "vol2"), (4, "vol3"), (5, "volN")):
            if idx < len(sw) and sw[idx]:
                total += max(0.0, min(1.0, d.get(key, 0.0)))
        # Feedback de l'entrée externe (réinjecté avant le filtre côté firmware)
        total += max(0.0, min(1.0, d.get("ext", 0.0)))

        # Enveloppe LOUDNESS simulée (attaque -> déclin vers sustain -> relâche)
        t = time.time()
        dt = max(0.0, min(0.2, t - self._ovl_t))
        self._ovl_t = t
        atk = max(0.01, d.get("lAtk", 0.01))
        dec = max(0.01, d.get("lDec", 0.01))
        sus = max(0.0, min(1.0, d.get("lSus", 0.0)))
        env = self._ovl_env
        if gate:
            if env < 1.0:
                env += (1.0 - env) * min(1.0, dt / atk)
                if env > 0.999:
                    env = 1.0
            else:
                env += (sus - env) * min(1.0, dt / dec)
        else:
            env += (0.0 - env) * min(1.0, dt / dec)
        env = max(0.0, min(1.0, env))
        self._ovl_env = env

        if total * env >= OVERLOAD_THRESHOLD:
            self._ovl_lit_until = t + OVERLOAD_HOLD
        on = t < self._ovl_lit_until
        if "ovlLed" in self.top:
            self.cv.itemconfigure(
                self.top["ovlGlow"], fill="#ff5a3c" if on else "")
            self.cv.itemconfigure(
                self.top["ovlLed"], fill="#ff3b30" if on else "#3a2020")
            self.cv.itemconfigure(
                self.top["ovlTxt"], fill="#ff6b5e" if on else "#7a828b")

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
        moddepth = 0.5
        if len(parts) > 49:
            try:
                moddepth = float(parts[49])
            except (ValueError, IndexError):
                moddepth = 0.5
        veldepth = 0.5
        if len(parts) > 50:
            try:
                veldepth = float(parts[50])
            except (ValueError, IndexError):
                veldepth = 0.5
        delaylevel = 0.0
        if len(parts) > 51:
            try:
                delaylevel = float(parts[51])
            except (ValueError, IndexError):
                delaylevel = 0.0
        delaytype = 0
        if len(parts) > 52:
            try:
                delaytype = int(parts[52])
            except (ValueError, IndexError):
                delaytype = 0
        ledbright = 0.5
        if len(parts) > 53:
            try:
                ledbright = max(0.0, min(1.0, float(parts[53])))
            except (ValueError, IndexError):
                ledbright = 0.5
        # Table des CC MIDI réellement active dans le firmware (champs 54..58,
        # optionnels) : sert de référence/affichage dans la boîte CONFIG.
        cc_fw = None
        if len(parts) > 58:
            try:
                cc_fw = [int(parts[54 + k]) for k in range(5)]
            except (ValueError, IndexError):
                cc_fw = None

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
        d["veldepth"] = veldepth
        d["delaylevel"] = delaylevel
        d["delaytype"] = delaytype
        d["ledbright"] = ledbright
        d["cc_fw"] = cc_fw

        self._last = d.copy()
        self._last["sw"] = sw
        # 1re trame reçue = firmware prêt à écouter : pousser la banque
        if getattr(self, "_bank_pushed", True) is False \
                and self.ser and self.ser.is_open:
            self._push_bank()

        self._update_all(d, sw, locks)
        self._update_overload(d, sw, bool(midiOn))

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
        # Atténuateurs MOD DEPTH (CC3) / VEL FILT (CC9) : suivent la valeur
        # renvoyée par le firmware, sauf pendant qu'on les fait glisser.
        if not getattr(self, "_mod_drag", False):
            self._mod_ui(max(0.0, min(1.0, d.get("moddepth", 0.5))))
        if not getattr(self, "_vel_drag", False):
            self._vel_ui(max(0.0, min(1.0, d.get("veldepth", 0.5))))

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
            "veldepth": 0.5 + 0.5 * math.sin(t * 1.3),
            "delaylevel": 0.5 + 0.4 * math.sin(t * 0.6),
            "delaytype": int(t) % 4,
            "ledbright": 0.55 + 0.45 * math.sin(t * 0.4),
            "cc_fw": [1, 3, 9, 14, 122],
        }
        sw0 = [0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1]
        self._update_all(d, sw0)
        self._update_overload(d, sw0, bool(int(t) % 2))
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
        self._seq_ui_idle()

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
            noms = {self._cc("cc_modwheel"): "molette",
                    self._cc("cc_moddepth"): "mod depth",
                    self._cc("cc_veldepth"): "vel filt",
                    self._cc("cc_ledbright"): "LED bright",
                    self._cc("cc_patch"): "patch"}
            nom = noms.get(d0)
            if nom:
                return f"CC {nom} ch{ch} · v{d1}"
            return f"CC ch{ch} · n{d0} v{d1}"
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