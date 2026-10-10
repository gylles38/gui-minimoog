#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mise à jour de l'affichage depuis les trames (Mixin App)."""
import math
import time

from theme import (LOCK_DELAY_BIT, LOCK_EXT_BIT, LOCK_POT_KEYS,
                   LOCK_REVERB_BIT, LOCK_WAVE_RANGE, MOD_WHEEL_NORM,
                   OVERLOAD_HOLD, OVERLOAD_THRESHOLD)


class UpdateMixin:
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
