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

### Raccourcis clavier (marchent aussi quand le JEU a le focus)
| Touche  | Action                       |
|---------|------------------------------|
| `P`     | Calibrer le plateau + démarrer |
| `Espace`| Pause / Reprendre            |
| `S`     | Stop                         |
| `R`     | Recalibrer le plateau        |
| `Q`     | Quitter                      |

### IA – apprentissage anti-mort (visible dans l'interface)
Le panneau **« IA – Apprentissage »** montre en direct ce que le bot apprend :
- **Morts** et **Prudence** (0→1) : la prudence est *adaptative* — elle monte quand
  le bot meurt vite, redescend quand il enchaîne les points.
- **Situations connues** : configurations de boules déjà mortelles reconnues.
- **Zones dangereuses apprises** : cases où le bot est déjà mort → il les **évite
  proactivement** (coût de pathfinding augmenté sur ces cases).
- **Survie moyenne** et **dernière leçon** apprise.

Tout est sauvegardé dans `habbo_bot_memory.json` et **persiste entre les sessions** :
plus tu joues, mieux il anticipe.

### 👁 Mode Apprentissage (spectateur) + « Imiter mon style »
Le bot peut **apprendre en te regardant jouer** (apprentissage par démonstration,
100 % local, sans dépendance lourde) :
1. Clique sur **« 👁 Observer & apprendre de MOI »** (ou touche **O**). Le bot
   **ne clique pas** : il te regarde et enregistre tes coups (situation → ta
   direction) dans `habbo_bot_demos.json`. Joue plusieurs parties normalement.
2. Clique sur **Stop** (S) quand tu as fini : tes coups sont sauvegardés.
3. Coche le toggle **« Imiter mon style »**, puis lance le bot avec **Démarrer**
   (P). Dans les situations qui **ressemblent** à ce que tu as fait, il **rejoue
   ta décision**. Une **sécurité anti-mort** reste active : s'il n'y a pas de coup
   sûr, l'algorithme A* reprend la main, et il fonce toucher la dalle quand le
   chrono l'exige.
- Le curseur **« Imitation : tolerance »** règle à quel point une situation doit
  ressembler pour rejouer ton coup (petit = strict, grand = imite plus souvent).
- Le panneau IA affiche **« Coups appris de toi »** et l'état **Imitation ON/OFF**.

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
