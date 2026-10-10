#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Menu DÉMO (Mixin App) : chargement et lecture des riffs."""
import json
import os
import tkinter as tk

from theme import DEFAULT_SEQUENCES, SEQUENCES_FILE, best_patch


class SequenceMixin:
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
