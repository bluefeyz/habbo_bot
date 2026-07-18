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

## 3. Utilisation (aucun calibrage à faire 🎉)
1. Ouvre le jeu Habbo et laisse le **plateau bien visible** à l'écran (le sol beige
   entièrement dégagé, sans fenêtre par-dessus).
2. Dans la fenêtre noire du bot, appuie sur **`p`**.
   → Le bot **détecte automatiquement** le plateau (repère le sol beige, calcule
   les 4 coins et la grille 7×7), place ton perso au **centre** (spawn) et démarre.
3. Une fenêtre de debug s'ouvre : vérifie que la grille rouge est bien calée.
   Si ce n'est pas le cas, réappuie sur **`p`** pour re-détecter.

### Touches
| Touche | Action                              |
|--------|-------------------------------------|
| `p`    | détecter le plateau / (re)démarrer  |
| `space`| pause / reprise                     |
| `q`    | quitter le bot                      |
| souris dans un coin de l'écran | arrêt d'urgence (failsafe) |

> Le perso spawn **toujours au centre** (case 3,3), la dalle jaune en bas et les
> 2 boules sur les côtés : le bot en tient compte au démarrage.

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
6. **Clic** sur la case suivante du chemin, en boucle et de façon agressive.
