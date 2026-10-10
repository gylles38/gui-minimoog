# GUI Panneau Minimoog Model D

Affiche en temps réel l'état des contrôles physiques du clone Minimoog
(firmware `minimoog.ino`) sous forme de panneau graphique.
Les valeurs arrivent par le câble USB (port série) sous forme de trames CSV.

## Structure du projet

Le code est découpé par fonctionnalité :

- `panel_minimoog.py` — point d'entrée : arguments CLI, détection du port,
  réexporte la classe `App` (compatibilité `import panel_minimoog`).
- `app.py` — classe `App` : assemble les mixins ci-dessous et pilote la boucle
  tkinter, la connexion série et l'état global.
- `theme.py` — thème et constantes partagés : couleurs, mise en page, config
  MIDI/CC, patchs par défaut, séquences par défaut et utilitaires.
- `widgets.py` — composants dessinés sur le canvas : `ToolTip`,
  `PanelComponent`, `Knob`, `SwitchOn`, `Wheel`, `Keyboard`.
- `panel_build.py` (`PanelMixin`) — fond façon Model D et construction du
  panneau : sections, cadrans, switchs, molettes, jauges MOD DEPTH / VEL FILT /
  LED BRIGHT.
- `patches.py` (`PatchMixin`) — banque de patchs (`patches.json`) : liste,
  sauvegarde, suppression, push vers le firmware.
- `midi_config.py` (`ConfigMixin`) — configuration des CC (`config.json`).
- `sequences.py` (`SequenceMixin`) — démos musicales (`sequences.json`).
- `telemetry.py` (`UpdateMixin`) — mise à jour de l'affichage depuis les trames
  `P,...` du firmware.

Les fichiers de données (`patches.json`, `config.json`, `sequences.json`)
restent à la racine du projet.

## Fermware

- Utiliser la branche `feature/gui-panneau-minimoog`.
- Le firmware émet une trame `P,...` toutes les 200 ms (5 Hz).

Format de trame (48 champs + masque) :

```
P,
 vol1, vol2, vol3, volN,              // positions volume 0..1
 freq2, freq3,                        // désaccord ±7 st
 cut, res, amt,                       // filtre 0..1
 fAtk, fDec, fSus,                    // env filtre (s, s, 0..1)
 lAtk, lDec, lSus,                    // env loud (s, s, 0..1)
 glide, modmix,                       // 0..1
 s0..s12,                             // 13 switchs 0/1
 w1,r1,m1, w2,r2,m2, w3,r3,m3,        // waveform, range, mode (par VCO)
 note, midiOn, pitchBend, modWheel,   // MIDI
 patchNom, lockMask (lo.hi hex), revType  // patch, latch (36 bits), type reverb 0..3
```

`revType` : 0 ROOM, 1 HALL, 2 PLATE, 3 SPRING — choisi par ENC2 en mode reverb.

Order des switchs (idx 0..12) :
Mod_OSC, Ctrl_OSC3, Mix_OSC1, Mix_OSC2, Mix_OSC3, Mix_NOISE,
Type_NOISE, Output, Glide, Decay, Kbd_Ctrl2, Kbd_Ctrl1, Filt_Mod.

## Usage

Liste des ports :

```bash
python3 panel_minimoog.py -l
```

Lancer avec le port (USB branché au clone) :

```bash
python3 panel_minimoog.py /dev/ttyUSB0
```

Si un seul port est présent, il est détecté automatiquement.
Mode démonstration (sans matériel) :

```bash
python3 panel_minimoog.py --demo
```

## Dépendances

- Python 3
- `pyserial` (`pip install pyserial`)
- `tkinter` (fourni avec Python)

## Notes

- Le GUI ignore les lignes série qui ne commencent pas par `P,` (logs divers).
- La fenêtre fait 1500x974 px.
- Le firmware embarque aussi une **banque interne de 12 patchs** (`PATCHES_DEFAUT`
  dans `minimoog.ino`, identiques à `patches.json`) : le synthé est autonome sans le
  PC. Si la GUI est connectée, elle remplace la banque en poussant `patches.json`
  (`B!` + `B <ligne>`) ; SAVE continue d'écrire dans `patches.json`.
- Bouton **RESET** (entre DELETE et MIDI/SÉRIE) : envoie la commande série `R` —
  retour aux valeurs d'usine (volumes 50 %, filtre ouvert, env rapides, reverb
  off), déverrouillage de tous les potards et sortie du mode patch. Fonctionne
  aussi en moniteur série (`R`).
- En **mode MIDI** (RX série USB coupée), le bouton RESET fait un **reset
  matériel DTR/RTS** puis repousse la banque : l'ESP redémarre aux valeurs
  d'usine (potards libres) et revient en mode série.

## Procédure : charger les patches et jouer au clavier MIDI

GPIO3 de l'ESP32 est **partagé** entre la RX série USB (terminal / GUI) et l'entrée
MIDI DIN (optocoupleur). C'est une **mutual exclusion** : on ne peut pas avoir le
terminal série et le clavier MIDI actifs en même temps.

- En **mode série**, le firmware écoute les commandes (N/L/B...) sur GPIO3 : la GUI
  fonctionne, mais l'entrée MIDI est ignorée.
- Brancher le câble MIDI pendant qu'on est resté en mode série coupe la RX série
  (l'optocoupleur tire GPIO3) → ni terminal ni clavier ne répondent. Il faut
  **rebooter** après être passé en MIDI pour revenir en série.
- Les patches restent en RAM : l'encodeur ENC1 (mode patch) peut en changer **dans
  les deux modes** (sélection locale, sans série).

### Pour charger des patches, sauvegarder, etc.

1. Reboote l'ESP32 **sans le câble MIDI branché** (ou débranche-le avant le boot).
2. Ouvre la GUI **dans les ~10 s** qui suivent (fenêtre où l'ESP choisit le mode
   série). Attends « Patch: N en banque (fw) » dans le bandeau.
3. La banque (`patches.json`, poussée par la GUI) est alors active dans l'ESP.

   *Sans la GUI* : le firmware démarre seul avec la banque interne (12 patchs),
   ENC1 en mode patch permet de les parcourir — le synthé reste jouable.

### Pour jouer au clavier MIDI

1. Fais d'abord la procédure de chargement ci-dessus (le patch reste en mémoire).
2. Clique le bouton **MIDI** dans la GUI (à côté de PANIC) → le firmware passe en
   mode MIDI (Serial1 prend GPIO3).
3. Branche alors le câble MIDI du clavier → le clavier joue, et ENC1 continue de
   changer de patch.
4. Pour revenir au terminal / GUI (nouveau push, SAVE) : **reboote** l'ESP sans le
   câble MIDI branché. Le bouton **SÉRIE** (en mode série) ou `M0` ne fonctionnent
   que tant qu'on est encore en mode série ; une fois en MIDI, seul un reboot
   ramène en série.