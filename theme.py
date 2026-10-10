#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thème et constantes partagés : couleurs, mise en page, config CC, patches."""
import math
import os

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
