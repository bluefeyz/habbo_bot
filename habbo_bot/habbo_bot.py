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
CLICK_DELAY = 0.035          # spam de clics : delai mini entre 2 clics
LOOP_DELAY = 0.008           # pause entre deux analyses d'image (reactivite max)
CLICK_LATENCY = 0.10         # ping du jeu (~100 ms) : compense la prediction des boules
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


def estimate_sphere_dirs(spheres):
    """Estime la direction de chaque sphere en la comparant a la frame precedente."""
    dirs = {}
    for (r, c) in spheres:
        best = None
        best_d = 99
        for (pr, pc) in S.prev_spheres:
            d = abs(pr - r) + abs(pc - c)
            if d < best_d:
                best_d = d
                best = (pr, pc)
        if best and best != (r, c):
            dr = np.sign(r - best[0])
            dc = np.sign(c - best[1])
            dirs[(r, c)] = (int(dr), int(dc))
        else:
            dirs[(r, c)] = (0, 0)
    return dirs


def build_cost_map(spheres, dirs):
    """Carte de couts (7x7) : plus une case est dangereuse, plus elle coute cher.
    On projette chaque boule PREDICT_STEPS cases en avant (elles vont plus vite
    que nous) pour anticiper la collision. On ne bloque pas totalement (sauf
    glace) afin de garder des chemins evasifs et pouvoir forcer si le chrono
    l'exige."""
    cost = {}
    for (r, c) in spheres:
        _bump(cost, r, c, COST_SPHERE)
        dr, dc = dirs.get((r, c), (0, 0))
        for step in range(1, PREDICT_STEPS + 1):
            _bump(cost, r + dr * step, c + dc * step, COST_PREDICT / step)
        for ar in (-1, 0, 1):
            for ac in (-1, 0, 1):
                if (ar, ac) != (0, 0):
                    _bump(cost, r + ar, c + ac, COST_ADJACENT)
    return cost


def predicted_ball_cells(spheres, dirs):
    """Cases ou une boule sera d'ici REACT_DIST cases, DANS SON SENS de marche
    (projection directionnelle) -> si la boule s'eloigne, la case devant nous
    n'est PAS marquee = "passable", on avance. Sinon on change de direction."""
    reach = max(REACT_DIST, int(round(REACT_DIST * BALL_FASTER)))
    cells = set()
    for (r, c) in spheres:
        cells.add((r, c))
        dr, dc = dirs.get((r, c), (0, 0))
        for step in range(1, reach + 1):
            nr, nc = r + dr * step, c + dc * step
            if in_grid(nr, nc):
                cells.add((nr, nc))
    return cells


def _bump(cost, r, c, val):
    if in_grid(r, c):
        cost[(r, c)] = cost.get((r, c), 0.0) + val


# ----------------------------------------------------------------------------
# PATHFINDING (A*, 8 directions, evite glace + danger)
# ----------------------------------------------------------------------------
DIRS8 = [(-1, 0), (1, 0), (0, -1), (0, 1),
         (-1, -1), (-1, 1), (1, -1), (1, 1)]


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

    # spheres
    for (r, c) in spheres:
        x, y = cell_to_local(r, c)
        cv2.circle(vis, (x, y), 12, (0, 0, 255), 2)

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

        img = grab_frame()
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        ice = detect_ice(hsv)
        spheres = detect_blobs(hsv, GREEN_LOW, GREEN_HIGH)
        yellow = detect_yellow(hsv)
        dirs = estimate_sphere_dirs(spheres)
        S.prev_spheres = spheres

        if yellow is None:
            time.sleep(LOOP_DELAY)
            continue

        # nouvelle dalle detectee -> +1 score et chrono relance a 10 s
        if S.last_yellow is None or yellow != S.last_yellow:
            if S.last_yellow is not None:
                S.score += 1
                print(f"[BOT] Dalle atteinte ! Score = {S.score}")
            S.deadline = time.time() + TIME_LIMIT
        S.last_yellow = yellow

        # temps restant -> niveau de risque accepte
        remaining = (S.deadline - time.time()) if S.deadline else TIME_LIMIT
        elapsed = TIME_LIMIT - remaining
        if elapsed >= PANIC_AFTER:
            risk = 0.12          # PANIQUE : fonce, quasi-ignore les spheres
            mode = "PANIC"
        elif elapsed >= URGENT_AFTER:
            risk = 0.5           # URGENT : accepte de frôler
            mode = "URGENT"
        else:
            risk = 1.0           # NORMAL : evitement maximal
            mode = "SAFE"

        ice_set = set(ice)
        danger = build_cost_map(spheres, dirs)
        danger.pop(S.player, None)          # ne jamais penaliser la case de depart
        soon = predicted_ball_cells(spheres, dirs)   # cases boules imminentes

        path = astar(S.player, yellow, ice_set, danger, risk=risk)
        if not path:  # secours : ignore le danger, garde juste la glace
            path = astar(S.player, yellow, ice_set, {}, risk=0.0)

        draw_debug(img, ice_set, spheres, yellow, path, mode, remaining)

        if path and len(path) >= 2:
            nxt = path[1]
            # SECURITE : ne jamais entrer sur une case ou une boule sera dans
            # l'instant (sauf PANIC ou il faut absolument atteindre la dalle).
            if nxt in soon and mode != "PANIC":
                # tente un pas d'esquive lateral sur une case sure, sinon attend
                alt = safe_step(S.player, yellow, ice_set, soon)
                if alt:
                    nxt = alt
                else:
                    time.sleep(LOOP_DELAY)
                    continue
            x, y = cell_to_screen_abs(*nxt)
            pyautogui.click(int(x), int(y))
            S.player = nxt
            print(f"[BOT] {mode} t={remaining:4.1f}s ->{nxt} but{yellow} "
                  f"boules{spheres} score={S.score}")
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
