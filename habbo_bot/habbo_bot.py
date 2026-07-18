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
MOVE_SPEED = 3.0             # vitesse estimee du perso (cases/seconde) pour le suivi
HORIZON = 14                 # nb de pas anticipes (planification espace-temps)
PATCH = 6                    # demi-taille du carre echantillonne au centre d'une case
SPHERE_MIN_AREA = 120        # aire mini d'un blob pour etre une sphere
MARGIN = 60                  # marge (px) autour du plateau pour la capture
SHOW_DEBUG = True            # fenetre OpenCV : grille, spheres, dalle, chemin

# Reaction : si une boule fonce vers une case a <= REACT_DIST cases, on change
# de direction. Si la boule s'eloigne (trajectoire opposee), c'est "passable"
# -> on avance quand meme (gere automatiquement car la projection est directionnelle).
REACT_DIST = 2               # distance de reaction (en cases)
PREDICT_STEPS = 3            # nb de cases anticipees devant chaque boule (cout doux)
BALL_FASTER = 1.4            # les boules ~40% plus rapides que le joueur

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


S = State()
mouse_ctl = mouse.Controller()


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
    mask = cv2.inRange(hsv, TAN_LOW, TAN_HIGH)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

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
    print(f"[BOT] Plateau detecte. centre(3,3)={tuple(int(v) for v in cell_to_screen_abs(3,3))} "
          f"| zone {S.bbox}")
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
    """Retourne l'ensemble des cases occupees par de la glace."""
    mask = color_mask(hsv, ICE_LOW, ICE_HIGH)
    ice = set()
    for r in range(GRID):
        for c in range(GRID):
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
    EMA = 0.5            # lissage de la vitesse
    MIN_SPEED = 0.4      # en dessous, on garde l'ancienne direction

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


def predict_occupancy(balls, ice, horizon, player_speed):
    """Simule chaque boule (ligne droite + rebond sur bord/glace/coin) et renvoie
    occ[t] = cases MORTELLES au pas t (boule + ses 8 voisines : etre a 1 case =
    perdu). t compte les pas du JOUEUR ; les boules avancent 'ratio' cases/pas."""
    occ = [set() for _ in range(horizon + 1)]

    def add_lethal(t, r, c):
        for ar in (-1, 0, 1):
            for ac in (-1, 0, 1):
                nr, nc = r + ar, c + ac
                if in_grid(nr, nc):
                    occ[t].add((nr, nc))

    for b in balls:
        r, c = b.cell
        d = b.dir
        ratio = max(0.3, b.speed / max(0.1, player_speed)) if b.speed > 0 else 1.0
        acc = 0.0
        for t in range(horizon + 1):
            add_lethal(t, r, c)
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
    return occ


# ----------------------------------------------------------------------------
# PATHFINDING (A*, 8 directions, evite glace + danger)
# ----------------------------------------------------------------------------
DIRS8 = [(-1, 0), (1, 0), (0, -1), (0, 1),
         (-1, -1), (-1, 1), (1, -1), (1, 1)]


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


def safe_step(start, goal, ice, soon):
    """Choisit une case voisine sure (hors glace et hors trajectoire imminente
    des boules) qui rapproche le plus du but. Sert a esquiver dans l'urgence."""
    best = None
    best_h = 1e9
    for dr, dc in DIRS8:
        nr, nc = start[0] + dr, start[1] + dc
        if not in_grid(nr, nc) or (nr, nc) in ice or (nr, nc) in soon:
            continue
        if dr != 0 and dc != 0:
            if (start[0] + dr, start[1]) in ice or (start[0], start[1] + dc) in ice:
                continue
        h = math.hypot(goal[0] - nr, goal[1] - nc)
        if h < best_h:
            best_h = h
            best = (nr, nc)
    return best


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
        for dr, dc in DIRS8:
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


def spacetime_astar(start, goal, ice, occ, allow_lethal=False):
    """A* dans l'espace-temps (case, t). occ[t] = cases mortelles au pas t.
    L'attente sur place est autorisee (move (0,0)). Renvoie la suite de cases."""
    H = len(occ) - 1
    moves = DIRS8 + [(0, 0)]
    start_s = (start, 0)
    open_h = [(0.0, 0.0, start_s)]
    came = {start_s: None}
    g = {start_s: 0.0}
    while open_h:
        _, gc, (cell, t) = heapq.heappop(open_h)
        if cell == goal:
            path = []
            s = (cell, t)
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
            if not allow_lethal and ncell in occ[nt] and ncell != goal:
                continue
            step = 1.0 if (dr == 0 or dc == 0) else 1.41
            ng = gc + step
            st = (ncell, nt)
            if st not in g or ng < g[st]:
                g[st] = ng
                came[st] = (cell, t)
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
    cv2.putText(vis, f"{mode}  t={remaining:4.1f}s  score={S.score}",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                color.get(mode, (255, 255, 255)), 2)

    cv2.imshow("Habbo Bot - debug (q pour quitter)", vis)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        S.quit = True


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

        img = grab_frame()
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        ice = detect_ice(hsv)
        ice_set = set(ice)
        ball_pts = detect_blob_pixels(hsv, GREEN_LOW, GREEN_HIGH)
        dets = [local_to_gridf(x, y) for (x, y) in ball_pts]
        balls = tracker.update(dets, dt)          # tracker : dir + vitesse
        spheres = [b.cell for b in balls]
        yellow = detect_yellow(hsv)

        if yellow is None:
            time.sleep(LOOP_DELAY)
            continue

        # nouvelle dalle -> +1 score, chrono relance, RE-SYNC : le perso est
        # forcement sur l'ancienne dalle qu'il vient de toucher.
        if S.last_yellow is None or yellow != S.last_yellow:
            if S.last_yellow is not None:
                S.score += 1
                S.player = S.last_yellow      # re-synchronisation fiable
                S.move_accum = 0.0
                print(f"[BOT] Dalle atteinte ! Score = {S.score}")
            S.deadline = time.time() + TIME_LIMIT
        S.last_yellow = yellow

        # temps restant -> mode (autorise a forcer si le chrono l'exige)
        remaining = (S.deadline - time.time()) if S.deadline else TIME_LIMIT
        elapsed = TIME_LIMIT - remaining
        if elapsed >= PANIC_AFTER:
            mode = "PANIC"
        elif elapsed >= URGENT_AFTER:
            mode = "URGENT"
        else:
            mode = "SAFE"

        # PREDICTION espace-temps : ou sera chaque boule (+ ses voisines) a chaque
        # pas -> chemin garanti sans collision, re-calcule a chaque image.
        occ = predict_occupancy(balls, ice_set, HORIZON, MOVE_SPEED)
        soon = occ[1]                              # cases mortelles imminentes

        path = spacetime_astar(S.player, yellow, ice_set, occ,
                               allow_lethal=(mode == "PANIC"))
        if not path:   # aucun chemin sur -> on force (dernier recours) via A* simple
            path = astar(S.player, yellow, ice_set, {}, risk=0.0)

        draw_debug(img, ice_set, spheres, yellow, path, mode, remaining)

        target = None       # case a CLIQUER (peut etre loin)
        step_cell = None    # case vers laquelle le modele avance ce tick

        if path and len(path) >= 2:
            if path[1] in soon and mode != "PANIC":
                # une boule va bloquer/toucher -> on CHANGE de direction tout de
                # suite (esquive laterale sure a >= 1 case de toute boule).
                ev = safe_step(S.player, yellow, ice_set, soon)
                if ev:
                    target = step_cell = ev
                else:
                    # piege (aucune case sure) : bouger vers le but reste moins
                    # pire que rester fige (mort certaine sinon).
                    target = step_cell = path[1]
            else:
                target = commit_target(path, soon)   # clic loin en ligne droite
                step_cell = path[1]

        if target:
            x, y = cell_to_screen_abs(*target)
            pyautogui.click(int(x), int(y))          # clic loin : le perso y va
            # suivi du modele dans le temps (avance vers la case suivante)
            S.move_accum += dt * MOVE_SPEED
            if S.move_accum >= 1.0 and step_cell:
                S.move_accum -= 1.0
                S.player = step_cell
            print(f"[BOT] {mode} t={remaining:4.1f}s clic->{target} pas->{step_cell} "
                  f"but{yellow} boules{spheres} score={S.score}")
            time.sleep(CLICK_DELAY)
        else:
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

    # 'p' : (re)detecte le plateau et (re)demarre
    if k == 'p':
        print("[BOT] Detection automatique du plateau...")
        if detect_board():
            S.calibrated = True
            S.running = True
            S.last_yellow = None
            S.deadline = None
            S.move_accum = 0.0
            S.last_t = None
            tracker.reset()
            print("[BOT] Demarrage ! (space=pause, q=quitter, p=re-detecter)")
        else:
            print("[BOT] Echec detection. Verifie que le plateau est bien visible puis reappuie 'p'.")
        return


def main():
    print("Pret. Ouvre le jeu, place la fenetre du plateau bien visible,")
    print("puis appuie sur 'p' : le bot detecte le plateau et joue tout seul.")
    print("(space = pause/reprise, q = quitter, p = re-detecter le plateau)")
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    bot_loop()
    listener.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
