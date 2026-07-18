# Habbo Bot – auto-joueur (mini-jeu glace / sphères / dalle jaune)

> ⚠️ **Avertissement** : automatiser une partie sur Habbo est contraire aux
> conditions d'utilisation du jeu et peut entraîner un **bannissement** de ton
> compte. Utilise ce script à tes risques, idéalement sur un jeu local / un clone.

## 1. Ce qu'il te faut
- **Windows**
- **Python 3.11+** → https://www.python.org/downloads/
  - ⚠️ Pendant l'installation, coche **« Add Python to PATH »**.
- Pas besoin de Visual Studio. (VS Code est utile juste pour lire/éditer le code.)

## 2. Lancer le bot
Double-clique simplement sur **`lancer_bot.bat`**.
Il installe tout seul les dépendances la première fois, puis démarre le bot.

## 3. Utilisation
1. Ouvre le jeu Habbo et laisse la fenêtre **bien visible** à l'écran.
2. Dans la fenêtre noire du bot, appuie sur **`p`** → mode calibrage.
3. Place la **souris au centre** de la case demandée puis appuie sur la touche :
   - `1` → coin haut du plateau, case **(0,0)**
   - `2` → case **(0,6)** (l'autre coin d'une même rangée)
   - `3` → case **(6,0)** (le coin de la même colonne)
   - `4` → la case où se trouve **ton personnage**
4. Le bot démarre automatiquement et joue tout seul.

### Touches en cours de jeu
| Touche | Action            |
|--------|-------------------|
| `space`| pause / reprise   |
| `q`    | quitter le bot    |
| souris dans un coin de l'écran | arrêt d'urgence (failsafe) |

## 4. Si la détection est mauvaise
Ouvre `habbo_bot.py` et ajuste les **plages de couleurs HSV** en haut du fichier
(`ICE_LOW/HIGH`, `GREEN_LOW/HIGH`, `YELLOW_LOW/HIGH`). Les logs affichés dans la
console t'indiquent ce que le bot détecte (position des sphères, dalle, joueur).

Autres réglages utiles :
- `CLICK_DELAY` : pause après chaque clic (augmente si le perso « rate » des cases).
- `SPHERE_MIN_AREA` : taille mini d'une sphère détectée.
- `PATCH` : taille de l'échantillon de couleur pris au centre d'une case.

## 5. Comment ça marche (résumé)
1. **Capture** de la zone du plateau (`mss`).
2. **Vision** (`OpenCV`) : masques de couleur → glace, sphères vertes, dalle jaune.
3. **Grille** : projection isométrique inverse pour convertir pixels ↔ cases (7×7).
4. **Danger** : les sphères et les 2 cases devant elles sont marquées à éviter.
5. **A\*** (8 directions, diagonales autorisées) vers la dalle jaune.
6. **Clic** sur la case suivante du chemin, en boucle.
