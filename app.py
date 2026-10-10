#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classe App : assemble les mixes par fonctionnalité et pilote la boucle."""
import time
import tkinter as tk

try:
    import serial
except ImportError:
    serial = None

from theme import BODY_DY, WIN_H, WIN_W, WOOD_BASE
from widgets import ToolTip
from panel_build import PanelMixin
from patches import PatchMixin
from midi_config import ConfigMixin
from sequences import SequenceMixin
from telemetry import UpdateMixin


class App(PanelMixin, PatchMixin, ConfigMixin, SequenceMixin, UpdateMixin):
    W, H = WIN_W, WIN_H
    BODY_DY = BODY_DY

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
