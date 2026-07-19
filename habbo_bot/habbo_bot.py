"""
Habbo - Bot auto-joueur pour le mini-jeu de survie (glace / sphères / dalle jaune).

Ce script tourne EN LOCAL sur ton PC. Il :
  1. capture l'ecran a l'endroit du plateau,
  2. detecte la glace (bleu), les spheres (vert), la dalle jaune,
  3. calcule le meilleur chemin (evite glace + spheres),
  4. clique automatiquement la case suivante pour atteindre la dalle jaune.

Touches :
  p     -> detecte automatiquement le plateau puis demarre le bot
  space -> pause / reprise
  q     -> quitter

AVERTISSEMENT : automatiser une partie Habbo est contraire aux CGU du jeu
et peut entrainer un bannissement. A utiliser a tes risques.
"""

import time
import math
import heapq
import json
import os

import numpy as np
import cv2
import mss
import pyautogui
from pynput import keyboard, mouse

# ----------------------------------------------------------------------------
# CONFIGURATION (a ajuster si la detection est mauvaise)
# ----------------------------------------------------------------------------
GRID = 7                     # plateau 7x7
CLICK_DELAY = 0.03           # spam de clics : delai mini entre 2 clics
LOOP_DELAY = 0.006           # pause entre deux analyses d'image (reactivite max)
CLICK_LATENCY = 0.10         # ping du jeu (~100 ms) : compense la prediction des boules
MOVE_SPEED = 2.9             # vitesse du perso (cases/s) MESUREE sur la video
HORIZON = 16                 # nb de pas anticipes (planification espace-temps)
PATCH = 6                    # demi-taille du carre echantillonne au centre d'une case
SPHERE_MIN_AREA = 120        # aire mini d'un blob pour etre une sphere
MARGIN = 60                  # marge (px) autour du plateau pour la capture
SHOW_DEBUG = True            # fenetre OpenCV : grille, spheres, dalle, chemin

# Comportements activables (modifiables en direct via l'interface) :
DIAGONALS = True             # autoriser les deplacements en diagonale
TEMPORIZE = True             # attendre pres de la dalle et toucher au dernier moment
DODGE = True                 # esquiver activement (anticipation des boules)
IMITATE = False              # rejouer TON style appris en mode spectateur

# Anticipation des boules (le point cle demande) :
#   rayon MORTEL   = collision certaine -> case totalement interdite
#   rayon ANTICIP. = 2 cases d'avance -> fortement evite (mais franchissable en
#   dernier recours) => laisse le temps a l'habbo d'esquiver.
MARGIN_HARD = 1              # rayon mortel (case boule + 1)
MARGIN_SOFT = 2             # rayon d'anticipation (2 cases d'avance)
SOFT_COST = 3.5             # cout d'une case dans la zone d'anticipation (doux)
SANDWICH_COST = 12.0        # cout supplementaire d'une case prise en tenaille
TURN_COST = 0.8             # penalite de changement de direction -> preferer tout droit
REVERSE_COST = 6.0          # penalite d'un DEMI-TOUR (anti aller-retour / feinte inutile)
EXTRACT_TH = 3              # si ma case devient mortelle dans <= X pas -> s'extirper

# Temporisation : pas besoin de se presser. On attend dans une case sure proche
# de la dalle, et on ne fonce la toucher qu'au dernier moment (marge de securite).
HOLD_BUFFER = 1.6           # secondes de marge avant la deadline pour foncer
UNC_GROW = 3                # la zone d'anticipation s'elargit tous les N pas
                            # (les boules peuvent tourner -> incertitude au loin)

# Apprentissage "anti-mort" (leger, sans entrainement, memoire persistante)
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "habbo_bot_memory.json")
CAUTION_STEP = 0.12          # prudence gagnee a chaque mort (0..1)
CAUTION_HARD_TH = 0.45       # au-dela (ou situation deja mortelle), rayon mortel = 2
LEARN_COST = 1.5             # cout de pathfinding ajoute par mort memorisee sur une case
LEARN_MAX = 8.0              # plafond du cout "appris" pour une case

# Apprentissage par DEMONSTRATION (mode spectateur) : le bot te regarde jouer,
# enregistre (etat du jeu -> ta direction) puis peut IMITER ton style (k-NN).
DEMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "habbo_bot_demos.json")
DEMO_MAX = 8000              # nb max de coups memorises (fichier leger)
IMIT_K = 5                   # nb de voisins consideres pour le vote d'imitation
IMIT_MAXDIST = 6.0           # distance^2 max pour juger une situation "ressemblante"
NO_YELLOW_DEATH = 25         # frames sans dalle -> partie terminee (mort/timeout)
MOTION_TH = 22               # seuil de mouvement pour tracker l'avatar
AVATAR_MIN_AREA = 250        # aire mini du blob avatar (mouvement)

# Reconnaissance de TON tour via ton visage (capture en direct au spawn central).
FACE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_face.png")
FACE_TH = 0.55               # score mini de reconnaissance du visage (a ajuster)
TURN_LOST_FRAMES = 12        # frames sans ton visage -> ce n'est plus ton tour

# Chrono du jeu : il faut toucher la dalle dans les 10 s.
TIME_LIMIT = 10.0            # secondes imparties par dalle
URGENT_AFTER = 5.5           # au-dela, le bot prend des risques pour arriver a temps
PANIC_AFTER = 7.5            # au-dela, chemin le plus court coute que coute

# Couts de A* : la glace est infranchissable, les spheres sont "cheres" mais
# franchissables quand le temps presse -> mouvements complexes et adaptatifs.
COST_SPHERE = 60.0           # penalite case occupee par une sphere
COST_PREDICT = 30.0          # penalite case sur la trajectoire anticipee d'une boule
COST_ADJACENT = 8.0          # penalite case adjacente a une sphere

# Plages de couleurs en HSV (OpenCV: H 0-179, S 0-255, V 0-255)
# Ajuste-les si besoin en observant les logs.
ICE_LOW,    ICE_HIGH    = np.array([85,  40, 150]), np.array([110, 200, 255])   # bleu clair
GREEN_LOW,  GREEN_HIGH  = np.array([70,  60,  40]), np.array([95,  255, 220])   # sphere verte/teal
YELLOW_LOW, YELLOW_HIGH = np.array([22, 120, 150]), np.array([35,  255, 255])   # dalle jaune
TAN_LOW,    TAN_HIGH    = np.array([8,   30, 130]), np.array([32,  120, 240])   # sol beige (detection auto)

pyautogui.FAILSAFE = True    # bouge la souris dans un coin pour couper d'urgence
pyautogui.PAUSE = 0          # pas de delai parasite : on gere le rythme nous-memes


# ----------------------------------------------------------------------------
# ETAT GLOBAL
# ----------------------------------------------------------------------------
class State:
    def __init__(self):
        self.calibrated = False
        self.running = False
        self.paused = False
        self.quit = False
        # transformation affine du plateau (detectee automatiquement)
        self.T = None                 # coin HAUT du sol (px absolus)
        self.e1 = None                # vecteur +1 colonne (vers coin droit)
        self.e2 = None                # vecteur +1 ligne (vers coin gauche)
        self.invM = None              # inverse pour ecran -> case
        self.player = (3, 3)          # position estimee du joueur (spawn = centre)
        self.move_accum = 0.0         # accumulateur temps -> avancee du modele
        self.last_t = None            # horodatage de la frame precedente
        self.prev_spheres = []        # spheres detectees a la frame precedente
        self.score = 0
        self.last_yellow = None
        self.deadline = None          # instant limite pour atteindre la dalle
        self.bbox = None              # zone de capture {top,left,width,height}
        self.ice = set()              # glace (fixe) detectee au demarrage
        # apprentissage anti-mort
        self.deaths = 0               # nb de morts (persiste)
        self.best_score = 0           # meilleur score de la session
        self.caution = 0.0            # prudence globale (0..1), monte a chaque mort
        self.death_mem = []           # signatures de situations mortelles
        self.pre_sig = None           # signature de la derniere frame jouee
        self.cell_deaths = {}         # heatmap apprise : (r,c) -> nb de morts
        self.run_scores = []          # score de chaque run (pour la survie moyenne)
        self.last_alive_cell = (3, 3) # derniere case sure connue (juste avant la mort)
        self.last_lesson = ""         # resume lisible du dernier apprentissage (sortie IA)
        self.avg_survival = 0.0       # score moyen avant de mourir
        self.danger_zones = 0         # nb de cases apprises comme dangereuses
        # apprentissage par demonstration (mode spectateur / imitation)
        self.observe = False          # mode spectateur : on te regarde jouer (aucun clic)
        self.demos = []               # coups appris : [{"f":[features], "a":[dr,dc]}]
        self.demo_count = 0           # nb de coups appris (affiche)
        self.obs_prev_cell = None     # case du joueur a la frame precedente (observe)
        self.obs_prev_feat = None     # etat a la frame precedente (observe)
        self.no_yellow = 0            # compteur de frames sans dalle
        self.playing = False          # une partie est en cours
        self.reached = False          # contact deja compte pour la dalle courante
        self.yellow_gone = False      # la dalle a disparu (teleport/clignotement)
        self.prev_gray = None         # image precedente (tracking avatar par mouvement)
        self.face_tmpl = None         # modele du visage (capture au spawn)
        self.face_score = 0.0         # dernier score de reconnaissance
        self.my_turn = False          # est-ce ton tour de jouer ?
        self.turn_miss = 0            # frames consecutives sans ton visage
        self.commit = None            # case-cible engagee (anti-oscillation)
        self.commit_dir = (0, 0)      # direction engagee
        # stats live (pour l'interface)
        self.mode = ""
        self.act = ""
        self.nballs = 0
        self.fps = 0.0
        self.remaining = TIME_LIMIT


S = State()
mouse_ctl = mouse.Controller()


def _recompute_learning_stats():
    """Met a jour les indicateurs affiches (zones dangereuses, survie moyenne)."""
    S.danger_zones = sum(1 for n in S.cell_deaths.values() if n >= 1.0)
    if S.run_scores:
        recent = S.run_scores[-10:]
        S.avg_survival = sum(recent) / len(recent)


def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            d = json.load(f)
        S.deaths = d.get("deaths", 0)
        S.caution = d.get("caution", 0.0)
        S.death_mem = [frozenset(tuple(x) for x in sig) for sig in d.get("mem", [])]
        S.cell_deaths = {tuple(int(v) for v in k.split(",")): float(n)
                         for k, n in d.get("cell_deaths", {}).items()}
        S.run_scores = list(d.get("run_scores", []))
        _recompute_learning_stats()
        print(f"[BOT] Memoire chargee : {S.deaths} morts, prudence={S.caution:.2f}, "
              f"{len(S.death_mem)} situations, {S.danger_zones} zones dangereuses apprises.")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_memory():
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump({"deaths": S.deaths, "caution": round(S.caution, 3),
                       "mem": [[list(x) for x in sig] for sig in S.death_mem[-200:]],
                       "cell_deaths": {f"{r},{c}": round(n, 2)
                                       for (r, c), n in S.cell_deaths.items()},
                       "run_scores": S.run_scores[-50:]}, f)
    except OSError:
        pass


def load_demos():
    """Charge tes coups appris (demonstrations) pour l'imitation."""
    try:
        with open(DEMO_FILE, "r") as f:
            d = json.load(f)
        S.demos = d.get("demos", [])
        S.demo_count = len(S.demos)
        if S.demo_count:
            print(f"[BOT] Demonstrations chargees : {S.demo_count} de tes coups appris.")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_demos():
    try:
        with open(DEMO_FILE, "w") as f:
            json.dump({"demos": S.demos[-DEMO_MAX:]}, f)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# DETECTION AUTO DU PLATEAU + GEOMETRIE ISOMETRIQUE
# ----------------------------------------------------------------------------
def grab_fullscreen():
    """Capture l'ecran principal en entier (pour detecter le plateau)."""
    with mss.mss() as sct:
        mon = sct.monitors[1]          # ecran principal
        raw = sct.grab(mon)
    img = np.array(raw)[:, :, :3]
    return img, mon["left"], mon["top"]


def detect_board():
    """Detecte automatiquement le sol beige, en deduit les 4 coins du plateau
    puis construit la transformation case <-> ecran. Le joueur spawn au centre."""
    img, off_x, off_y = grab_fullscreen()
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # sol beige + glace = losange COMPLET (la glace couvre des tuiles du haut,
    # donc le beige seul laisserait un losange tronque -> coin haut fausse).
    tan = cv2.inRange(hsv, TAN_LOW, TAN_HIGH)
    ice = cv2.inRange(hsv, ICE_LOW, ICE_HIGH)
    mask = cv2.bitwise_or(tan, ice)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))

    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        print("[BOT] !! sol beige introuvable - le jeu est-il bien visible ?")
        return False
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[idx, cv2.CC_STAT_AREA] < 20000:
        print("[BOT] !! plateau trop petit / non trouve. Zoome le jeu.")
        return False

    comp = (lab == idx).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(float)

    top = c[np.argmin(c[:, 1])]
    left = c[np.argmin(c[:, 0])]
    right = c[np.argmax(c[:, 0])]

    # coordonnees absolues ecran
    S.T = np.array([top[0] + off_x, top[1] + off_y])
    S.e1 = (np.array([right[0] + off_x, right[1] + off_y]) - S.T) / GRID
    S.e2 = (np.array([left[0] + off_x, left[1] + off_y]) - S.T) / GRID
    M = np.array([[S.e1[0], S.e2[0]], [S.e1[1], S.e2[1]]], dtype=float)
    S.invM = np.linalg.inv(M)

    # zone de capture englobant les 49 cases + marge
    pts = [cell_to_screen_abs(r, cc) for r in range(GRID) for cc in range(GRID)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    S.bbox = {"left": int(min(xs) - MARGIN), "top": int(min(ys) - MARGIN),
              "width": int(max(xs) - min(xs) + 2 * MARGIN),
              "height": int(max(ys) - min(ys) + 2 * MARGIN)}

    S.player = (3, 3)                  # spawn toujours au centre
    # glace FIXE : detectee une fois au demarrage puis mise en cache
    frame = grab_frame()
    S.ice = detect_ice(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    print(f"[BOT] Plateau detecte. centre(3,3)={tuple(int(v) for v in cell_to_screen_abs(3,3))} "
          f"| glace={sorted(S.ice)} | zone {S.bbox}")
    return True


def cell_to_screen_abs(r, c):
    """Centre d'une case (r,c) en coordonnees ecran absolues."""
    p = S.T + (c + 0.5) * S.e1 + (r + 0.5) * S.e2
    return (p[0], p[1])


def cell_to_local(r, c):
    """Centre d'une case en coordonnees locales a la capture."""
    x, y = cell_to_screen_abs(r, c)
    return (int(x - S.bbox["left"]), int(y - S.bbox["top"]))


def screen_local_to_cell(x, y):
    """Convertit un point (local a la capture) en case (r,c) arrondie."""
    abs_x = x + S.bbox["left"]
    abs_y = y + S.bbox["top"]
    d = np.array([abs_x - S.T[0], abs_y - S.T[1]], dtype=float)
    cc, rr = S.invM.dot(d)
    return (int(round(rr - 0.5)), int(round(cc - 0.5)))


def in_grid(r, c):
    return 0 <= r < GRID and 0 <= c < GRID


# ----------------------------------------------------------------------------
# DETECTION
# ----------------------------------------------------------------------------
def grab_frame():
    with mss.mss() as sct:
        raw = sct.grab(S.bbox)
    img = np.array(raw)[:, :, :3]        # BGRA -> BGR
    return img


def color_mask(hsv, low, high):
    return cv2.inRange(hsv, low, high)


def detect_ice(hsv):
    """Cases de glace. Par les regles, la glace n'existe QUE sur les cases
    interieures (lignes/colonnes 1,2,4,5) : bords + ligne/colonne centrale
    toujours libres -> on restreint la recherche = zero faux positif de bord."""
    mask = color_mask(hsv, ICE_LOW, ICE_HIGH)
    ice = set()
    for r in (1, 2, 4, 5):
        for c in (1, 2, 4, 5):
            x, y = cell_to_local(r, c)
            patch = mask[max(0, y - PATCH):y + PATCH, max(0, x - PATCH):x + PATCH]
            if patch.size and patch.mean() > 60:   # >~25% de pixels bleus
                ice.add((r, c))
    return ice


def detect_blobs(hsv, low, high):
    """Retourne les centroides (case r,c) des blobs d'une couleur."""
    mask = color_mask(hsv, low, high)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cells = []
    for cnt in cnts:
        if cv2.contourArea(cnt) < SPHERE_MIN_AREA:
            continue
        m = cv2.moments(cnt)
        if m["m00"] == 0:
            continue
        cx = m["m10"] / m["m00"]
        cy = m["m01"] / m["m00"]
        r, c = screen_local_to_cell(cx, cy)
        if in_grid(r, c):
            cells.append((r, c))
    return cells


def detect_yellow(hsv):
    cells = detect_blobs(hsv, YELLOW_LOW, YELLOW_HIGH)
    return cells[0] if cells else None


def detect_blob_pixels(hsv, low, high):
    """Centroides des blobs d'une couleur, en pixels LOCAUX (sub-case)."""
    mask = color_mask(hsv, low, high)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts = []
    for cnt in cnts:
        if cv2.contourArea(cnt) < SPHERE_MIN_AREA:
            continue
        m = cv2.moments(cnt)
        if m["m00"] == 0:
            continue
        pts.append((m["m10"] / m["m00"], m["m01"] / m["m00"]))
    return pts


def local_to_gridf(x, y):
    """Pixel local -> coordonnees grille CONTINUES (row_f, col_f)."""
    d = np.array([x + S.bbox["left"] - S.T[0], y + S.bbox["top"] - S.T[1]], dtype=float)
    cc, rr = S.invM.dot(d)
    return (rr - 0.5, cc - 0.5)


def track_avatar(img, ball_pts):
    """Suit l'habbo par le MOUVEMENT (indep. de sa couleur : gris, orange...).
    Difference entre 2 images -> objets mobiles = boules + avatar ; on retire
    les boules, le plus gros blob restant = l'avatar ; ses pieds -> la case.
    Renvoie None si l'avatar est immobile (on garde alors la position connue)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    prev = S.prev_gray
    S.prev_gray = gray
    if prev is None or prev.shape != gray.shape:
        return None
    diff = cv2.absdiff(gray, prev)
    _, m = cv2.threshold(diff, MOTION_TH, 255, cv2.THRESH_BINARY)
    for (x, y) in ball_pts:                       # efface le mouvement des boules
        cv2.circle(m, (int(x), int(y)), 26, 0, -1)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, ba = None, 0
    for c in cnts:
        a = cv2.contourArea(c)
        if a < AVATAR_MIN_AREA:
            continue
        x, y, w, h = cv2.boundingRect(c)
        r, cc = screen_local_to_cell(x + w / 2.0, y + h - 3)   # pieds
        if in_grid(r, cc) and a > ba:
            ba, best = a, (r, cc)
    return best


def capture_face(img):
    """Capture le visage de l'avatar au spawn (case centrale) comme modele.
    A appeler quand c'est ton tour et que ton perso est au centre."""
    tile = np.linalg.norm(S.e1)
    cx, cy = cell_to_local(3, 3)
    w = max(16, int(tile * 0.75)); h = max(20, int(tile * 1.0))
    x = int(cx - w / 2); y = int(cy - tile * 1.45)   # la tete est au-dessus des pieds
    x = max(0, x); y = max(0, y)
    tmpl = img[y:y + h, x:x + w]
    if tmpl.size:
        S.face_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        cv2.imwrite(FACE_FILE, tmpl)
        print(f"[BOT] Visage capture ({w}x{h}) au centre -> reconnaissance de tour active.")
        return True
    return False


def detect_my_turn(img):
    """Cherche TON visage sur le plateau. Renvoie (c_est_ton_tour, case_avatar).
    Si aucun modele n'est charge -> joue toujours (pas de gating)."""
    if S.face_tmpl is None:
        return True, None
    bg = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    th, tw = S.face_tmpl.shape
    best = (-1.0, None)
    for s in (0.85, 0.95, 1.05, 1.15):
        w, h = int(tw * s), int(th * s)
        if w < 12 or h < 12 or h >= bg.shape[0] or w >= bg.shape[1]:
            continue
        res = cv2.matchTemplate(bg, cv2.resize(S.face_tmpl, (w, h)), cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, (loc, (w, h)))
    S.face_score = best[0]
    if best[0] >= FACE_TH and best[1]:
        (x, y), (w, h) = best[1]
        r, c = screen_local_to_cell(x + w / 2.0, y + h + np.linalg.norm(S.e1) * 0.5)
        return True, ((r, c) if in_grid(r, c) else None)
    return False, None


# ----------------------------------------------------------------------------
# TRACKER DE BOULES : ID persistant + direction/vitesse mesurees
# ----------------------------------------------------------------------------
class Ball:
    __slots__ = ("rf", "cf", "vr", "vc", "dir", "speed", "miss")

    def __init__(self, rf, cf):
        self.rf, self.cf = rf, cf      # position continue (row, col)
        self.vr, self.vc = 0.0, 0.0    # vitesse lissee (cases/s)
        self.dir = (0, 0)              # direction 4-dir figee
        self.speed = 0.0               # vitesse scalaire (cases/s)
        self.miss = 0                  # frames sans detection

    @property
    def cell(self):
        return (int(round(self.rf)), int(round(self.cf)))


class BallTracker:
    MATCH_DIST = 1.6     # distance max (cases) pour associer une detection a un track
    EMA = 0.6            # lissage de la vitesse (assez reactif pour bien l'estimer)
    MIN_SPEED = 0.4      # en dessous, on garde l'ancienne direction
    MAX_SPEED = 6.0      # borne (evite les valeurs aberrantes dues au bruit de detection)

    def __init__(self):
        self.balls = []

    def reset(self):
        self.balls = []

    def update(self, dets, dt):
        """dets = liste de (row_f, col_f). Associe, met a jour vitesse+direction."""
        used = [False] * len(dets)
        for b in self.balls:
            best, bd = -1, 1e9
            for i, (rf, cf) in enumerate(dets):
                if used[i]:
                    continue
                d = math.hypot(rf - b.rf, cf - b.cf)
                if d < bd:
                    bd, best = d, i
            if best >= 0 and bd <= self.MATCH_DIST:
                rf, cf = dets[best]
                used[best] = True
                if dt > 0:
                    vr, vc = (rf - b.rf) / dt, (cf - b.cf) / dt
                    b.vr = self.EMA * vr + (1 - self.EMA) * b.vr
                    b.vc = self.EMA * vc + (1 - self.EMA) * b.vc
                b.rf, b.cf = rf, cf
                b.speed = max(abs(b.vr), abs(b.vc))
                b.speed = min(b.speed, self.MAX_SPEED)   # borne anti-bruit
                if b.speed >= self.MIN_SPEED:      # boule H/V -> axe dominant
                    if abs(b.vc) >= abs(b.vr):
                        b.dir = (0, int(np.sign(b.vc)))
                    else:
                        b.dir = (int(np.sign(b.vr)), 0)
                b.miss = 0
            else:
                b.miss += 1
        # nouvelles detections
        for i, (rf, cf) in enumerate(dets):
            if not used[i]:
                self.balls.append(Ball(rf, cf))
        # nettoyage
        self.balls = [b for b in self.balls if b.miss <= 5]
        return self.balls


tracker = BallTracker()


def situation_signature(balls, player):
    """Signature d'une situation : boules relatives au joueur (pos + direction)."""
    return frozenset((b.cell[0] - player[0], b.cell[1] - player[1],
                      b.dir[0], b.dir[1]) for b in balls)


def matches_death(sig):
    """La situation courante ressemble-t-elle a une mort deja vecue ?
    (chaque boule proche <=1 case d'une boule mortelle memorisee, meme sens)."""
    for mem in S.death_mem:
        ok = len(sig) == len(mem) and len(sig) > 0
        if not ok:
            continue
        used = [False] * len(mem)
        ml = list(mem)
        for (dr, dc, ddr, ddc) in sig:
            found = False
            for i, (mr, mc, mdr, mdc) in enumerate(ml):
                if not used[i] and abs(dr - mr) <= 1 and abs(dc - mc) <= 1 \
                        and (ddr, ddc) == (mdr, mdc):
                    used[i] = True
                    found = True
                    break
            if not found:
                ok = False
                break
        if ok:
            return True
    return False


def register_death():
    """Enregistre une mort et EN APPREND : signature mortelle, heatmap par-case,
    prudence adaptative et statistiques de survie (sortie IA lisible)."""
    S.deaths += 1
    nballs = len(S.pre_sig) if S.pre_sig else 0
    score = S.score

    # 1) apprentissage "signature" : la config de boules qui a tue
    if S.pre_sig:
        S.death_mem.append(S.pre_sig)

    # 2) apprentissage "heatmap" : la case de la mort (+voisins) devient chere,
    #    donc EVITEE PROACTIVEMENT les prochaines fois (anticipation qui progresse).
    dr, dc = S.last_alive_cell
    S.cell_deaths[(dr, dc)] = S.cell_deaths.get((dr, dc), 0.0) + 1.0
    for adr, adc in DIRS4:
        nb = (dr + adr, dc + adc)
        if in_grid(*nb):
            S.cell_deaths[nb] = S.cell_deaths.get(nb, 0.0) + 0.4

    # 3) prudence ADAPTATIVE : monte si on meurt vite, redescend si on survit bien
    #    (evite de devenir paralyse a force de morts).
    if score <= 1:
        S.caution = min(1.0, S.caution + CAUTION_STEP)
    elif score >= 5:
        S.caution = max(0.0, S.caution - 0.5 * CAUTION_STEP)
    else:
        S.caution = min(1.0, S.caution + 0.5 * CAUTION_STEP)

    # 4) statistiques de survie + resume lisible (affiche dans l'interface)
    S.run_scores.append(score)
    _recompute_learning_stats()
    S.last_lesson = (f"Mort #{S.deaths} en case {S.last_alive_cell} "
                     f"(score {score}, {nballs} boules) -> case evitee, "
                     f"prudence {S.caution:.2f}")
    save_memory()
    print(f"[BOT] *** MORT #{S.deaths} (score {score}) *** {S.last_lesson} "
          f"| survie moy={S.avg_survival:.1f} | zones={S.danger_zones}")
    # reset de la partie
    S.playing = False
    S.score = 0
    S.last_yellow = None
    S.deadline = None
    S.player = (3, 3)
    S.last_alive_cell = (3, 3)
    S.move_accum = 0.0
    S.pre_sig = None
    S.reached = False
    S.yellow_gone = False
    tracker.reset()


def predict_occupancy(balls, ice, horizon, player_speed, hard_r=1, soft_r=2):
    """Simule chaque boule (ligne droite + rebond sur bord/glace/coin) et renvoie
    deux couches par pas t :
      hard[t] = cases MORTELLES (boule + rayon `hard_r`)  -> interdites
      soft[t] = zone d'ANTICIPATION (boule + rayon `soft_r`) -> fortement evitee
    'balls_at[t]' garde le centre des boules pour l'anti-sandwich.
    t = pas du JOUEUR ; les boules avancent 'ratio' cases/pas."""
    hard = [set() for _ in range(horizon + 1)]
    soft = [set() for _ in range(horizon + 1)]
    balls_at = [[] for _ in range(horizon + 1)]

    def add_ring(layer, t, r, c, rad):
        for ar in range(-rad, rad + 1):
            for ac in range(-rad, rad + 1):
                nr, nc = r + ar, c + ac
                if in_grid(nr, nc):
                    layer[t].add((nr, nc))

    for b in balls:
        r, c = b.cell
        d = b.dir
        ratio = max(0.3, b.speed / max(0.1, player_speed)) if b.speed > 0 else 1.0
        acc = 0.0
        for t in range(horizon + 1):
            # l'incertitude grandit avec le temps (la boule peut tourner) :
            # la zone d'anticipation s'elargit au loin.
            grow = t // UNC_GROW
            add_ring(soft, t, r, c, min(soft_r + grow, 3))
            add_ring(hard, t, r, c, hard_r)
            balls_at[t].append((r, c))
            acc += ratio
            hops = int(acc)
            acc -= hops
            for _ in range(hops):
                if d == (0, 0):
                    break
                nr, nc = r + d[0], c + d[1]
                if not in_grid(nr, nc) or (nr, nc) in ice:   # rebond
                    d = (-d[0], -d[1])
                    nr, nc = r + d[0], c + d[1]
                    if not in_grid(nr, nc) or (nr, nc) in ice:
                        break
                r, c = nr, nc
    return hard, soft, balls_at


def safe_until(cell, hard):
    """Nombre de pas avant que `cell` devienne mortelle (grand = tres sur)."""
    for t in range(len(hard)):
        if cell in hard[t]:
            return t
    return len(hard)


def best_hold_cell(player, goal, ice, hard, soft, sandwich, balls):
    """Case ou TEMPORISER : la plus sûre possible (reste hors danger longtemps),
    au large des boules et proche de la dalle, SANS bouger pour rien (forte inertie
    -> evite les feintes/aller-retours inutiles). Peut renvoyer la case actuelle."""
    cands = [player]
    for dr, dc in moves_dirs():
        nr, nc = player[0] + dr, player[1] + dc
        if not in_grid(nr, nc) or (nr, nc) in ice:
            continue
        if dr != 0 and dc != 0:
            if (player[0] + dr, player[1]) in ice or (player[0], player[1] + dc) in ice:
                continue
        cands.append((nr, nc))
    best, bscore = player, -1e9
    for cell in cands:
        if cell != player and cell in hard[1]:      # ne pas entrer dans un mortel imminent
            continue
        if cell == goal and cell != player:         # on TEMPORISE a cote, pas dessus
            continue
        score = 10.0 * safe_until(cell, hard)        # priorite : rester sûr longtemps
        score += 1.5 * _openness(cell, balls)        # rester au large des boules
        score -= 1.2 * math.hypot(goal[0] - cell[0], goal[1] - cell[1])  # rester pres de la dalle
        if cell in soft[1]:
            score -= 4.0
        if cell in sandwich:
            score -= 12.0
        if cell == player:
            score += 4.0                             # forte inertie : ne pas feinter pour rien
        if score > bscore:
            bscore, best = score, cell
    return best


def sandwich_cells(balls_at_t):
    """Cases 'prises en tenaille' : une boule d'un cote ET une de l'autre
    (meme ligne ou meme colonne, a <=3 cases) -> a fortement eviter."""
    out = set()
    for r in range(GRID):
        for c in range(GRID):
            left = any(br == r and 0 < c - bc <= 3 for (br, bc) in balls_at_t)
            right = any(br == r and 0 < bc - c <= 3 for (br, bc) in balls_at_t)
            up = any(bc == c and 0 < r - br <= 3 for (br, bc) in balls_at_t)
            down = any(bc == c and 0 < br - r <= 3 for (br, bc) in balls_at_t)
            if (left and right) or (up and down):
                out.add((r, c))
    return out


# ----------------------------------------------------------------------------
# PATHFINDING (A*, 8 directions, evite glace + danger)
# ----------------------------------------------------------------------------
DIRS8 = [(-1, 0), (1, 0), (0, -1), (0, 1),
         (-1, -1), (-1, 1), (1, -1), (1, 1)]
DIRS4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def moves_dirs():
    """Directions autorisees (avec ou sans diagonales, selon le reglage)."""
    return DIRS8 if DIAGONALS else DIRS4


def commit_target(path, soon):
    """Renvoie la case la plus LOINTAINE atteignable en LIGNE DROITE sure depuis
    le depart (meme direction, aucune case imminente-dangereuse). Cliquer loin =
    le perso s'y rend seul (le jeu suit le clic). Au minimum path[1]."""
    if len(path) < 2:
        return None
    d0 = (np.sign(path[1][0] - path[0][0]), np.sign(path[1][1] - path[0][1]))
    tgt = path[1]
    for i in range(2, len(path)):
        di = (np.sign(path[i][0] - path[i - 1][0]), np.sign(path[i][1] - path[i - 1][1]))
        if di != d0 or path[i] in soon:
            break
        tgt = path[i]
    return tgt


def _openness(cell, balls):
    """Ouverture d'une case = distance (Manhattan) a la boule la plus proche.
    Plus c'est grand, plus la case est 'au large' (espace safe)."""
    if not balls:
        return 6
    return min(abs(cell[0] - b.cell[0]) + abs(cell[1] - b.cell[1]) for b in balls)


def safe_step(start, goal, ice, soon, balls, prev_dir=(0, 0)):
    """Un pas voisin SUR pour S'EXTIRPER vers l'espace libre : on maximise la
    distance aux boules, on evite les bords (moins d'issues) et surtout on NE
    REVIENT PAS sur ses pas (anti aller-retour / feinte inutile)."""
    best, best_score = None, -1e9
    for dr, dc in moves_dirs():
        nr, nc = start[0] + dr, start[1] + dc
        if not in_grid(nr, nc) or (nr, nc) in ice or (nr, nc) in soon:
            continue
        if dr != 0 and dc != 0:
            if (start[0] + dr, start[1]) in ice or (start[0], start[1] + dc) in ice:
                continue
        score = 2.2 * _openness((nr, nc), balls)
        score -= math.hypot(goal[0] - nr, goal[1] - nc)      # garder un cap vers la dalle
        if nr in (0, GRID - 1) or nc in (0, GRID - 1):
            score -= 2.0                                      # eviter de se coincer au bord
        if prev_dir != (0, 0) and (dr, dc) == (-prev_dir[0], -prev_dir[1]):
            score -= 6.0                                      # NE PAS revenir sur ses pas
        if score > best_score:
            best_score, best = score, (nr, nc)
    return best


def escape_target(start, goal, ice, soon, balls, prev_dir):
    """Case d'extraction (espace libre) + la MEME direction prolongee de quelques
    cases : cliquer loin => le perso file en ligne droite, GAGNE DE L'ESPACE, sans
    osciller. Renvoie (cible_a_cliquer, premier_pas)."""
    step = safe_step(start, goal, ice, soon, balls, prev_dir)
    if step is None:
        return None, None
    d = (step[0] - start[0], step[1] - start[1])
    tgt = cur = step
    for _ in range(2):                                        # jusqu'a 2 cases de plus
        nxt = (cur[0] + d[0], cur[1] + d[1])
        if not in_grid(*nxt) or nxt in ice or nxt in soon:
            break
        if d[0] != 0 and d[1] != 0:
            if (cur[0] + d[0], cur[1]) in ice or (cur[0], cur[1] + d[1]) in ice:
                break
        cur = tgt = nxt
    return tgt, step


def astar(start, goal, ice, danger, risk=1.0):
    """A* 8 directions. `ice` = infranchissable. `danger` = carte de couts.
    `risk` module l'aversion au danger (1.0 normal, ~0.12 en panique)."""
    if start == goal:
        return [start]
    open_h = [(0.0, start)]
    came = {start: None}
    cost = {start: 0.0}
    while open_h:
        _, cur = heapq.heappop(open_h)
        if cur == goal:
            path = []
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            return path[::-1]
        for dr, dc in moves_dirs():
            nr, nc = cur[0] + dr, cur[1] + dc
            nxt = (nr, nc)
            if not in_grid(nr, nc):
                continue
            if nxt in ice:
                continue
            # interdit de couper un coin entre deux glaces
            if dr != 0 and dc != 0:
                if (cur[0] + dr, cur[1]) in ice or (cur[0], cur[1] + dc) in ice:
                    continue
            step = 1.0 if (dr == 0 or dc == 0) else 1.41
            penalty = danger.get(nxt, 0.0) * risk if nxt != goal else 0.0
            ncost = cost[cur] + step + penalty
            if nxt not in cost or ncost < cost[nxt]:
                cost[nxt] = ncost
                h = math.hypot(goal[0] - nr, goal[1] - nc)
                heapq.heappush(open_h, (ncost + h, nxt))
                came[nxt] = cur
    return None


def spacetime_astar(start, goal, ice, hard, soft, sandwich, allow_lethal=False,
                    start_dir=(0, 0)):
    """A* espace-temps (case, t, direction).
      hard[t]  = cases mortelles -> interdites (sauf PANIC).
      soft[t]  = zone d'anticipation -> penalisee (SOFT_COST).
      sandwich = cases en tenaille -> penalisees (SANDWICH_COST).
    Une PENALITE DE VIRAGE (TURN_COST) favorise les trajets en ligne droite
    (moins d'esquives inutiles). L'attente sur place est autorisee."""
    H = len(hard) - 1
    moves = moves_dirs() + [(0, 0)]
    start_s = (start, 0, start_dir)
    open_h = [(0.0, 0.0, start_s)]
    came = {start_s: None}
    g = {start_s: 0.0}
    while open_h:
        _, gc, (cell, t, pd) = heapq.heappop(open_h)
        if cell == goal:
            path = []
            s = (cell, t, pd)
            while s is not None:
                path.append(s[0])
                s = came[s]
            return path[::-1]
        if t >= H:
            continue
        for dr, dc in moves:
            nr, nc = cell[0] + dr, cell[1] + dc
            ncell, nt = (nr, nc), t + 1
            if not in_grid(nr, nc) or ncell in ice:
                continue
            if dr != 0 and dc != 0:
                if (cell[0] + dr, cell[1]) in ice or (cell[0], cell[1] + dc) in ice:
                    continue
            if not allow_lethal and ncell in hard[nt] and ncell != goal:
                continue
            step = 1.0 if (dr == 0 or dc == 0) else 1.41
            pen = 0.0
            if ncell != goal:
                if ncell in soft[nt]:
                    pen += SOFT_COST
                if ncell in sandwich:
                    pen += SANDWICH_COST
                ld = S.cell_deaths.get(ncell, 0.0)
                if ld:                              # apprentissage : case deja mortelle
                    pen += min(LEARN_MAX, LEARN_COST * ld)
            if (dr, dc) != (0, 0) and pd != (0, 0):
                if (dr, dc) == (-pd[0], -pd[1]):
                    pen += REVERSE_COST           # demi-tour : fortement penalise
                elif (dr, dc) != pd:
                    pen += TURN_COST              # simple changement de direction
            ng = gc + step + pen
            st = (ncell, nt, (dr, dc))
            if st not in g or ng < g[st]:
                g[st] = ng
                came[st] = (cell, t, pd)
                h = math.hypot(goal[0] - nr, goal[1] - nc)
                heapq.heappush(open_h, (ng + h, ng, st))
    return None


# ----------------------------------------------------------------------------
# OVERLAY DE DEBUG (fenetre OpenCV)
# ----------------------------------------------------------------------------
def draw_debug(img, ice, spheres, yellow, path, mode, remaining):
    if not SHOW_DEBUG:
        return
    vis = img.copy()

    # grille + cases de glace
    for r in range(GRID):
        for c in range(GRID):
            x, y = cell_to_local(r, c)
            col = (255, 200, 120) if (r, c) in ice else (70, 70, 70)
            cv2.circle(vis, (x, y), 4, col, -1)
            cv2.putText(vis, f"{r}{c}", (x - 10, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (90, 90, 90), 1)

    # dalle jaune
    if yellow:
        x, y = cell_to_local(*yellow)
        cv2.rectangle(vis, (x - 14, y - 14), (x + 14, y + 14), (0, 255, 255), 2)

    # spheres + direction/vitesse mesurees (tracker)
    for b in tracker.balls:
        x, y = cell_to_local(*b.cell)
        cv2.circle(vis, (x, y), 12, (0, 0, 255), 2)
        dr, dc = b.dir
        if (dr, dc) != (0, 0):
            tx, ty = cell_to_local(b.cell[0] + dr, b.cell[1] + dc)
            cv2.arrowedLine(vis, (x, y), (tx, ty), (0, 0, 255), 2, tipLength=0.4)

    # chemin choisi
    if path and len(path) >= 2:
        pts = [cell_to_local(*cell) for cell in path]
        for i in range(len(pts) - 1):
            cv2.line(vis, pts[i], pts[i + 1], (0, 255, 0), 2)

    # joueur
    px, py = cell_to_local(*S.player)
    cv2.drawMarker(vis, (px, py), (255, 0, 255), cv2.MARKER_CROSS, 22, 3)

    # HUD
    color = {"SAFE": (0, 255, 0), "URGENT": (0, 165, 255), "PANIC": (0, 0, 255)}
    cv2.putText(vis, f"{mode}  t={remaining:4.1f}s  score={S.score}  best={S.best_score}",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                color.get(mode, (255, 255, 255)), 2)
    cv2.putText(vis, f"morts={S.deaths}  prudence={S.caution:.2f}  situations={len(S.death_mem)}",
                (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 255), 1)
    if S.face_tmpl is not None:
        tt = "TON TOUR" if S.my_turn else "PAS TON TOUR (souris libre)"
        col = (0, 255, 0) if S.my_turn else (0, 0, 255)
        cv2.putText(vis, f"{tt}  visage={S.face_score:.2f}", (10, 72),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 1)

    cv2.imshow("Habbo Bot - debug (q pour quitter)", vis)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        S.quit = True


# ----------------------------------------------------------------------------
# IMITATION (apprentissage par demonstration : rejoue TON style)
# ----------------------------------------------------------------------------
def state_features(balls, player, goal):
    """Vecteur d'etat relatif au joueur : direction vers la dalle + les 2 boules
    les plus proches (position + direction). Sert a comparer les situations."""
    pr, pc = player
    feat = [float(goal[0] - pr), float(goal[1] - pc)]
    near = sorted(balls, key=lambda b: (b.cell[0] - pr) ** 2 + (b.cell[1] - pc) ** 2)
    for i in range(2):
        if i < len(near):
            b = near[i]
            feat += [float(b.cell[0] - pr), float(b.cell[1] - pc),
                     float(b.dir[0]), float(b.dir[1])]
        else:
            feat += [9.0, 9.0, 0.0, 0.0]      # pas de boule -> sentinelle "loin"
    return feat


def imitate_action(feat, k=IMIT_K):
    """k-NN sur tes demonstrations : renvoie la direction que TU aurais prise dans
    la situation la plus proche (vote pondere par la distance). None si aucune
    situation memorisee n'est assez ressemblante (> IMIT_MAXDIST)."""
    if not S.demos:
        return None
    scored = []
    for d in S.demos:
        f = d["f"]
        dist = 0.0
        for a, b in zip(feat, f):
            dist += (a - b) * (a - b)
        scored.append((dist, d["a"]))
    scored.sort(key=lambda x: x[0])
    if scored[0][0] > IMIT_MAXDIST:
        return None
    votes = {}
    for dist, a in scored[:k]:
        key = (int(a[0]), int(a[1]))
        votes[key] = votes.get(key, 0.0) + 1.0 / (1.0 + dist)
    return max(votes, key=votes.get)


def _safe_neighbor(start, cell, ice, soon):
    """`cell` est-elle un pas voisin sur (dans la grille, hors glace, hors danger
    imminent, sans couper un coin de glace en diagonale) ?"""
    if not in_grid(*cell) or cell in ice or cell in soon:
        return False
    dr, dc = cell[0] - start[0], cell[1] - start[1]
    if abs(dr) > 1 or abs(dc) > 1:
        return False
    if dr != 0 and dc != 0:
        if (start[0] + dr, start[1]) in ice or (start[0], start[1] + dc) in ice:
            return False
    return True


# ----------------------------------------------------------------------------
# BOUCLE PRINCIPALE
# ----------------------------------------------------------------------------
def bot_loop():
    print("[BOT] Demarre. space=pause  q=quitter")
    while not S.quit:
        if S.paused or not S.running:
            time.sleep(0.1)
            continue

        now = time.time()
        dt = (now - S.last_t) if S.last_t else 0.0
        S.last_t = now
        if dt > 0:
            S.fps = 0.8 * S.fps + 0.2 * (1.0 / dt)

        img = grab_frame()
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # --- GATING DE TOUR : ne jouer que quand c'est TON tour (ton visage present).
        turn, face_cell = detect_my_turn(img)
        if turn:
            S.turn_miss = 0
        else:
            S.turn_miss += 1
        if S.face_tmpl is not None and S.turn_miss >= TURN_LOST_FRAMES:
            if S.my_turn:                     # ton tour vient de se terminer
                if S.playing:
                    register_death()          # fin de run -> apprentissage
                S.my_turn = False
                S.commit = None
                S.prev_gray = None
                print(f"[BOT] Ce n'est plus ton tour (visage absent, score visage "
                      f"{S.face_score:.2f}) -> souris liberee.")
            time.sleep(0.15)                  # on lache la souris, calcul minimal
            continue
        S.my_turn = True
        if face_cell is not None:
            S.player = face_cell              # position fiable via ton visage

        ice_set = S.ice                           # glace fixe (cache au demarrage)
        ball_pts = detect_blob_pixels(hsv, GREEN_LOW, GREEN_HIGH)
        dets = [local_to_gridf(x, y) for (x, y) in ball_pts]
        balls = tracker.update(dets, dt)          # tracker : dir + vitesse
        spheres = [b.cell for b in balls]
        yellow = detect_yellow(hsv)

        # --- TRACKING DE L'AVATAR par le mouvement (complement si pas de visage).
        if face_cell is None:
            cell = track_avatar(img, ball_pts)
            if cell is not None:
                S.player = cell               # position REELLE de l'habbo
        else:
            S.prev_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # --- MODE SPECTATEUR : le bot te REGARDE jouer et apprend tes coups
        #     (aucun clic). A chaque changement de case, on memorise
        #     (etat precedent -> ta direction) pour pouvoir IMITER ton style.
        if S.observe:
            if yellow is not None:
                feat = state_features(balls, S.player, yellow)
                if (S.obs_prev_cell is not None and S.obs_prev_feat is not None
                        and S.player != S.obs_prev_cell):
                    dr = int(np.sign(S.player[0] - S.obs_prev_cell[0]))
                    dc = int(np.sign(S.player[1] - S.obs_prev_cell[1]))
                    if (dr, dc) != (0, 0):
                        S.demos.append({"f": S.obs_prev_feat, "a": [dr, dc]})
                        if len(S.demos) > DEMO_MAX:
                            S.demos = S.demos[-DEMO_MAX:]
                        S.demo_count = len(S.demos)
                        if S.demo_count % 25 == 0:
                            save_demos()
                S.obs_prev_cell = S.player
                S.obs_prev_feat = feat
            S.mode = "OBSERVE"
            S.act = "WATCH"
            S.nballs = len(balls)
            draw_debug(img, ice_set, spheres, yellow, None, "OBSERVE", 0.0)
            time.sleep(LOOP_DELAY)
            continue

        if yellow is None:
            # pas de dalle : soit teleport (clignotement bref), soit MORT (reset).
            S.no_yellow += 1
            S.yellow_gone = True          # elle a disparu -> prochaine = nouvelle
            if S.playing and S.no_yellow >= NO_YELLOW_DEATH:
                register_death()
            time.sleep(LOOP_DELAY)
            continue
        S.no_yellow = 0
        S.playing = True

        # --- NOUVELLE INSTANCE de dalle ? (elle a bouge OU a clignote au teleport)
        if (S.last_yellow is not None and yellow != S.last_yellow) or S.yellow_gone:
            S.reached = False             # on pourra re-compter un contact
        S.yellow_gone = False
        S.last_yellow = yellow
        if S.deadline is None:
            S.deadline = time.time() + TIME_LIMIT

        # --- CONTACT : detecte par l'ARRIVEE sur la dalle (marche meme si la
        # nouvelle dalle re-apparait AU MEME endroit ou juste a cote).
        if not S.reached and S.player == yellow:
            S.score += 1
            S.best_score = max(S.best_score, S.score)
            S.deadline = time.time() + TIME_LIMIT   # chrono relance a 10 s
            S.reached = True
            S.move_accum = 0.0
            S.commit = None            # re-planifie proprement vers la PROCHAINE dalle
            print(f"[BOT] Dalle atteinte ! Score = {S.score} (best {S.best_score})")

        # temps restant -> mode (autorise a forcer si le chrono l'exige)
        remaining = (S.deadline - time.time()) if S.deadline else TIME_LIMIT
        elapsed = TIME_LIMIT - remaining
        if elapsed >= PANIC_AFTER:
            mode = "PANIC"
        elif elapsed >= URGENT_AFTER:
            mode = "URGENT"
        else:
            mode = "SAFE"
        S.mode = mode
        S.remaining = remaining
        S.nballs = len(balls)

        # APPRENTISSAGE : marge = 2 cases par defaut (anticipation demandee).
        # Rayon MORTEL porte a 2 si la prudence apprise est haute OU si la
        # situation ressemble a une mort deja vecue (accumulation des erreurs).
        S.pre_sig = situation_signature(balls, S.player)
        S.last_alive_cell = S.player          # memorise la case (pour apprendre la mort)
        risky = matches_death(S.pre_sig)
        hard_r = 2 if (S.caution >= CAUTION_HARD_TH or risky) else MARGIN_HARD
        soft_r = max(MARGIN_SOFT, hard_r + 1)

        # PREDICTION espace-temps (2 couches) + anti-sandwich.
        hard, soft, balls_at = predict_occupancy(balls, ice_set, HORIZON,
                                                 MOVE_SPEED, hard_r=hard_r, soft_r=soft_r)
        sandwich = sandwich_cells(balls_at[1]) | sandwich_cells(balls_at[2])
        if not DODGE:                              # esquive desactivee : seul le
            soft = [set() for _ in soft]           # danger mortel est evite
            sandwich = set()
        soon = hard[1]                             # cases mortelles imminentes

        path = spacetime_astar(S.player, yellow, ice_set, hard, soft, sandwich,
                               allow_lethal=(mode == "PANIC"), start_dir=S.commit_dir)
        if not path:   # aucun chemin sur -> on force (dernier recours) via A* simple
            path = astar(S.player, yellow, ice_set, {}, risk=0.0)

        draw_debug(img, ice_set, spheres, yellow, path, mode, remaining)

        target = None       # case a CLIQUER (peut etre loin)
        step_cell = None    # case vers laquelle le modele avance ce tick
        act = mode

        # Temps estime pour rejoindre la dalle + duree de securite de ma case.
        travel = ((len(path) - 1) / MOVE_SPEED + CLICK_LATENCY) if (path and len(path) >= 2) else 99.0
        my_safe = safe_until(S.player, hard)

        # IMITATION : dans une situation qui ressemble a ce que TU as deja fait
        # (mode SAFE, hors danger imminent), rejoue TON coup. Securite anti-mort :
        # on ne bouge que vers une case voisine sure (sinon on laisse l'algo decider).
        imit_cell = None
        if IMITATE and S.demos and mode == "SAFE" and my_safe > 2 and not S.reached:
            act_i = imitate_action(state_features(balls, S.player, yellow))
            if act_i and act_i != (0, 0):
                cand = (S.player[0] + act_i[0], S.player[1] + act_i[1])
                if _safe_neighbor(S.player, cand, ice_set, soon) and cand not in soft[1]:
                    imit_cell = cand

        # DECISION - 3 priorites claires :
        #   1) FONCER si le temps presse ou PANIC (il FAUT toucher la dalle),
        #   2) sinon S'EXTIRPER vers l'espace libre si on est en danger (direction
        #      simple et ENGAGEE, sans revenir sur ses pas / sans feinter),
        #   3) sinon TEMPORISER (rester au large, bouger le moins possible).
        time_critical = remaining <= travel + HOLD_BUFFER
        must_go = time_critical or mode == "PANIC"
        if not TEMPORIZE:
            must_go = True                         # temporisation desactivee -> foncer
        blocked = bool(path and len(path) >= 2 and path[1] in soon)
        danger_now = (my_safe <= EXTRACT_TH) or blocked

        if imit_cell is not None:
            # rejoue TON style (un pas dans la direction apprise)
            target = step_cell = imit_cell
            S.commit = None
            act = "IMIT"
        elif must_go and path and len(path) >= 2:
            if blocked and mode != "PANIC":
                # une boule bloque le chemin direct -> s'extirper (sans demi-tour).
                tgt, step = escape_target(S.player, yellow, ice_set, soon, balls, S.commit_dir)
                target, step_cell = (tgt, step) if tgt else (path[1], path[1])
                S.commit = tgt
            elif (S.commit is not None and S.commit != S.player
                  and S.commit in path and not blocked):
                # ENGAGEMENT : on garde le cap deja pris (anti aller-retour inutile).
                target = S.commit
                step_cell = path[1]
            else:
                target = commit_target(path, soon)   # clic loin en ligne droite
                step_cell = path[1]
                S.commit = target
            act = "GO"
        elif danger_now and mode != "PANIC":
            # S'EXTIRPER vers l'espace libre : direction simple, engagee, on gagne
            # de l'espace au lieu de feinter/reculer. Puis on pourra temporiser.
            tgt, step = escape_target(S.player, yellow, ice_set, soon, balls, S.commit_dir)
            if tgt:
                target, step_cell = tgt, step
                S.commit = tgt
                act = "ESQ"
            elif path and len(path) >= 2:
                target = step_cell = path[1]
                act = "GO"
        else:
            # TEMPORISER : attendre au large, en bougeant le moins possible.
            hold = best_hold_cell(S.player, yellow, ice_set, hard, soft, sandwich, balls)
            S.commit = None
            act = "HOLD"
            if hold != S.player:
                target = step_cell = hold            # petit repositionnement d'esquive
            # sinon target=None -> immobile, on attend l'ouverture

        if step_cell:
            S.commit_dir = (int(np.sign(step_cell[0] - S.player[0])),
                            int(np.sign(step_cell[1] - S.player[1])))

        if target:
            x, y = cell_to_screen_abs(*target)
            pyautogui.click(int(x), int(y))          # clic loin : le perso y va
            S.move_accum += dt * MOVE_SPEED
            if S.move_accum >= 1.0 and step_cell:
                S.move_accum -= 1.0
                S.player = step_cell
            S.act = act
            print(f"[BOT] {act} t={remaining:4.1f}s clic->{target} but{yellow} "
                  f"boules{spheres} score={S.score}")
            time.sleep(CLICK_DELAY)
        else:
            S.act = act
            time.sleep(LOOP_DELAY)


# ----------------------------------------------------------------------------
# DEMARRAGE (detection auto - plus de calibrage manuel)
# ----------------------------------------------------------------------------
def on_press(key):
    try:
        k = key.char
    except AttributeError:
        k = None

    if k == 'q':
        S.quit = True
        print("[BOT] Arret.")
        return False

    if key == keyboard.Key.space:
        S.paused = not S.paused
        print(f"[BOT] {'PAUSE' if S.paused else 'REPRISE'}")
        return

    # 'p' : (re)detecte le plateau, capture ton visage (spawn centre) et demarre
    if k == 'p':
        print("[BOT] Detection automatique du plateau...")
        if detect_board():
            S.calibrated = True
            S.running = True
            S.observe = False
            S.last_yellow = None
            S.deadline = None
            S.move_accum = 0.0
            S.last_t = None
            S.no_yellow = 0
            S.playing = False
            S.score = 0
            S.reached = False
            S.yellow_gone = False
            S.prev_gray = None
            S.commit = None
            S.commit_dir = (0, 0)
            S.turn_miss = 0
            tracker.reset()
            print("[BOT] Demarrage ! (p=re-detecter/recapturer, f=recapturer visage, "
                  "space=pause, q=quitter)")
        else:
            print("[BOT] Echec detection. Verifie que le plateau est bien visible puis reappuie 'p'.")
        return

    # 'f' : recapture ton visage (a faire quand ton perso est au centre)
    if k == 'f' and S.calibrated:
        capture_face(grab_frame())
        return

    # 'o' : mode spectateur (le bot te regarde jouer et apprend tes coups)
    if k == 'o':
        print("[BOT] Detection du plateau (mode spectateur)...")
        if detect_board():
            S.calibrated = True
            S.observe = True
            S.obs_prev_cell = None
            S.obs_prev_feat = None
            S.running = True
            print("[BOT] MODE SPECTATEUR : joue normalement, j'apprends tes coups. "
                  "(p=jouer, space=pause, q=quitter)")
        return


def main():
    print("Pret. Ouvre le jeu, place la fenetre du plateau bien visible,")
    print("puis appuie sur 'p' : le bot detecte le plateau et joue tout seul.")
    print("(space = pause/reprise, q = quitter, p = re-detecter le plateau)")
    load_memory()                       # apprentissage anti-mort persistant
    load_demos()                        # coups appris (imitation) persistants
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    bot_loop()
    listener.stop()
    save_demos()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
