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

try:
    import serial
except ImportError:
    serial = None

from app import App


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
