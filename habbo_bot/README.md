# Habbo Bot – auto-joueur (mini-jeu glace / sphères / dalle jaune)

> ⚠️ **Avertissement** : automatiser une partie sur Habbo est contraire aux
> conditions d'utilisation du jeu et peut entraîner un **bannissement** de ton
> compte. Utilise ce script à tes risques, idéalement sur un jeu local / un clone.

## 1. Ce qu'il te faut
- **Windows**
- **Python 3.11+** → https://www.python.org/downloads/
  - ⚠️ Pendant l'installation, coche **« Add Python to PATH »**.
- Pas besoin de Visual Studio. (VS Code est utile juste pour lire/éditer le code.)

## 2. Lancer le bot (avec l'interface graphique)
Double-clique sur **`lancer_bot.bat`** (ou `lancer_interface.bat`, c'est identique).
Il installe tout seul les dépendances la première fois (patiente 1-3 min au 1er
lancement), puis ouvre une **fenêtre grise « Habbo Bot - Panneau de controle »**
avec des boutons, des presets (Prudent / Équilibré / Agressif / EXTREME) et des
curseurs réglables **en direct**.

> Si aucune fenêtre grise n'apparaît et que ça reste dans la console noire :
> lis le texte affiché (il t'indique l'erreur, souvent Tkinter manquant → il
> faut réinstaller Python depuis python.org en laissant coché « tcl/tk and IDLE »).

### Utilisation depuis l'interface
1. Ouvre le jeu Habbo, plateau bien visible (sol beige dégagé, sans fenêtre par-dessus).
2. Dans l'interface, clique sur **« ▶ Calibrer & Demarrer »** : le bot détecte
   automatiquement le plateau (grille 7×7) et commence à jouer.
3. Ajuste les curseurs / presets pendant qu'il joue pour trouver le meilleur réglage.
   Boutons **Pause / Reprendre**, **Stop** et **Recalibrer plateau** disponibles.

## 4. Si la détection est mauvaise
Ouvre `habbo_bot.py` et ajuste les **plages de couleurs HSV** en haut du fichier
(`ICE_LOW/HIGH`, `GREEN_LOW/HIGH`, `YELLOW_LOW/HIGH`). Les logs affichés dans la
console t'indiquent ce que le bot détecte (position des sphères, dalle, joueur).

Autres réglages utiles :
- `CLICK_DELAY` : pause après chaque clic (augmente si le perso « rate » des cases).
- `SPHERE_MIN_AREA` : taille mini d'une sphère détectée.
- `PATCH` : taille de l'échantillon de couleur pris au centre d'une case.

## 5. Comment ça marche (résumé)
1. **Détection auto du plateau** : masque du sol beige (`OpenCV`), plus grande
   zone → 4 coins du losange → projection isométrique (grille 7×7). Zéro calibrage.
2. **Vision** : masques de couleur → glace, boules vertes, dalle jaune.
3. **Prédiction** : les boules vont ~40 % plus vite que toi ; le bot projette leur
   trajectoire 3 cases en avant (+ compensation du ping ~100 ms) pour ne jamais
   les croiser.
4. **A\*** (8 directions, diagonales) vers la dalle, avec évitement pondéré →
   trajets d'esquive complexes, re-calculés à chaque image (re-route immédiat).
5. **Chrono 10 s** synchronisé (relancé quand la dalle se téléporte) avec 3 modes
   auto `SAFE` → `URGENT` → `PANIC` pour toujours toucher la dalle à temps.
6. **Clic loin + spam** : il clique la case la plus lointaine atteignable en ligne
   droite sûre (le perso s'y rend seul), re-clique en continu, et **change de
   direction instantanément** dès qu'une boule menace à ≤ 2 cases. À chaque dalle
   touchée, la position réelle du perso est **re-synchronisée** (aucune dérive).
