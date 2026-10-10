#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration MIDI des CC (Mixin App) : config.json et boîte CONFIG."""
import json
import tkinter as tk
from tkinter import messagebox

from theme import CC_LABELS, CC_ORDER, CONFIG_FILE, DEFAULT_CONFIG


class ConfigMixin:
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
