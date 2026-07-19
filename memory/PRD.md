# PRD — Habbo Bot (auto-joueur mini-jeu glace/sphères/dalle jaune)

## Problème / objectif
Bot Python **desktop Windows** qui joue automatiquement à un mini-jeu Habbo :
plateau isométrique 7×7, blocs de glace fixes, sphères vertes rebondissantes
(ennemis), dalle jaune (cible qui se téléporte au contact et relance un chrono 10s).
Le bot analyse l'écran, calcule le meilleur chemin (évite glace + boules) et pilote
la souris pour rester en vie le plus longtemps possible.

**Langue utilisateur : Français** (répondre en français).

## Contrainte d'environnement CRITIQUE
- Script d'automatisation **Windows** (mss + opencv + pyautogui + pynput).
- **Impossible à exécuter/tester en E2E sur le serveur cloud Emergent** (pas d'écran,
  pas de fenêtre de jeu, pyautogui/tkinter indisponibles headless).
- Tests possibles côté serveur : `py_compile`, tests de logique avec libs stubées.
- Le test final se fait **sur le PC Windows de l'utilisateur** (via « Save to GitHub »).

## Architecture
```
/app/habbo_bot/
├── habbo_bot.py           # cœur : vision OpenCV, tracker de boules, A* espace-temps,
│                          #        temporisation, apprentissage anti-mort
├── interface.py           # GUI Tkinter : presets, curseurs live, panneau IA, raccourcis
├── requirements.txt       # numpy, opencv-python, mss, pyautogui, pynput
├── lancer_bot.bat         # (MAJ) lance désormais l'INTERFACE graphique
├── lancer_interface.bat   # lance l'interface graphique (identique)
├── build_exe.bat          # compile un .exe via PyInstaller (--windowed)
└── README.md
```
`habbo_bot_memory.json` (local) = mémoire d'apprentissage persistante.

## Concepts techniques
Computer Vision (OpenCV), capture rapide (mss), A* espace-temps (case,t,direction),
prédiction physique des rebonds, temporisation HOLD/GO (attendre une ouverture),
apprentissage anti-mort heuristique (pas de réseau de neurones).

## Implémenté (au 2026-06)
- Détection auto du plateau + géométrie isométrique 7×7.
- Tracking boules (id persistant, vitesse/direction), prédiction espace-temps 2 couches
  (mortelle / anticipation) + anti-sandwich.
- A* espace-temps avec temporisation SAFE/URGENT/PANIC.
- **GUI Tkinter** : presets (Prudent/Équilibré/Agressif/EXTREME), curseurs live, toggles.
- **Raccourcis clavier globaux** (pynput) : P=démarrer, Espace=pause, S=stop,
  R=recalibrer, Q=quitter — marchent même quand le jeu a le focus.
- **Apprentissage anti-mort renforcé** :
  - mémoire de signatures de configs mortelles (existant),
  - **heatmap par-case** : la case de mort (+voisins) devient chère → évitée
    proactivement par le pathfinding,
  - **prudence adaptative** (monte si mort rapide, baisse si bon score),
  - **stats de survie** + « dernière leçon » affichées dans le panneau **IA** de la GUI,
  - persistance JSON chargée aussi au démarrage de la GUI.
- Lanceurs `.bat` verbeux + vérification Tkinter + fenêtre d'erreur au lieu de plantage
  silencieux. `lancer_bot.bat` ouvre maintenant directement la GUI.
- **Mode Apprentissage spectateur + Imitation (learning from demonstration)** :
  - bouton « 👁 Observer & apprendre de MOI » (touche O) : le bot regarde l'utilisateur
    jouer sans cliquer et enregistre (état → sa direction) dans `habbo_bot_demos.json`,
  - toggle « Imiter mon style » : k-NN sur les démonstrations → rejoue la décision de
    l'utilisateur dans les situations similaires, avec **sécurité anti-mort** (fallback
    A*) et retour à l'algo en URGENT/PANIC pour garantir l'objectif,
  - curseur « Imitation : tolerance » (IMIT_MAXDIST), compteur « Coups appris » dans le
    panneau IA. Imitation-par-mémoire (choix utilisateur), ZÉRO nouvelle dépendance.
- **Comportement anti-oscillation / extraction (2026-06)** — réglages du feedback utilisateur :
  - `REVERSE_COST` : pénalité forte du demi-tour dans A* → supprime les aller-retours /
    feintes inutiles ("revenir sur ses pas").
  - `EXTRACT_TH` + `escape_target()` : quand une case devient dangereuse (≤ X pas) sans
    urgence de chrono, le bot **s'extirpe vers l'espace libre** dans une direction simple
    et engagée (prolongée de 2 cases) au lieu de feinter — priorité claire GO / EXTRACT / HOLD.
  - `best_hold_cell` : forte inertie + score d'ouverture → temporise au large, bouge moins.
  - Après avoir touché une dalle : `S.commit` remis à zéro → re-planifie proprement vers la
    prochaine dalle (plus de "panique"/backtrack au moment de l'enchaînement).
  - Tracker de boules plus réactif (EMA 0.6) + borne anti-bruit sur la vitesse mesurée.
  - Nouveaux curseurs exposés dans l'interface : « Anti demi-tour » et « S'extirper si
    danger à ≤ X pas ».

## Historique décisions
- Face-tracking / gating de tour : implémenté puis jugé peu fiable par l'utilisateur.
  Le code subsiste mais est **dormant** (touche `f` non exposée dans la GUI ;
  `detect_my_turn` renvoie « toujours ton tour » tant qu'aucun visage n'est capturé).
  → Suppression complète possible si l'utilisateur le confirme (question en attente).

## Backlog / prochaines tâches
- **P1 — Appâtage/feinte** : attirer les boules vers les bords pour ouvrir un passage.
  Nécessite un clip vidéo de l'utilisateur montrant la stratégie (en attente).
- **P2 — Nettoyage** : supprimer le code face-tracking résiduel si l'utilisateur valide.
- **P2 — .exe** : vérifier `build_exe.bat` (PyInstaller --windowed) sur Windows.
- **P3 — Apprentissage réglages auto** : ajuster prudence/vitesse selon le taux de survie.

## Statut de test
- Logique d'apprentissage : testée headless (libs stubées) — /tmp/test_learning.py — OK
  (heatmap, prudence adaptative, persistance, évitement proactif via A*).
- Logique d'imitation : testée headless — /tmp/test_imitation.py — OK
  (state_features, k-NN + vote, tolérance, _safe_neighbor anti-mort, persistance demos).
- GUI Tkinter + lanceurs `.bat` : NON testables sur serveur → validation utilisateur Windows.
