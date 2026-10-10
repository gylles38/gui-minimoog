#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construction du panneau (Mixin App) : fond, sections, cadrans et jauges."""
import math
import random
import tkinter as tk

from theme import (PANEL_BOX, PANEL_BRUSH_DARK, PANEL_BRUSH_LIGHT,
                   PANEL_EDGE, PANEL_FILL, PANEL_GRAIN, PANEL_SCREWS,
                   SILK, WOOD_BASE, WOOD_DARK, WOOD_LIGHT,
                   MD_BLACK, MD_BLUE, MD_ORANGE, MD_WHITE,
                   RANGES, WAVES, norm_env_time)
from widgets import Knob, SwitchOn, Wheel, Keyboard


class PanelMixin:
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
            235, 564 + dy, text="00%", font=("Courier", 14, "bold"),
            fill="#ffb14a")
        self.top["revGlow"] = []
        for gx, gy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            self.top["revGlow"].append(cv.create_text(
                235 + gx, 564 + dy + gy, text="00%",
                font=("Courier", 14, "bold"), fill="#5a2a00"))
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
