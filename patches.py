#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banque de patches (Mixin App) : patches.json, push B!/B, SAVE/DELETE."""
import json
import tkinter as tk
from tkinter import messagebox, simpledialog

from theme import PATCHES_FILE, norm_env_time


class PatchMixin:
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
