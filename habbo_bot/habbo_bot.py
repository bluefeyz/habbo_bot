"""
Habbo - Bot auto-joueur pour le mini-jeu de survie (glace / sphères / dalle jaune).

Ce script tourne EN LOCAL sur ton PC. Il :
  1. capture l'ecran a l'endroit du plateau,
  2. detecte la glace (bleu), les spheres (vert), la dalle jaune,
  3. calcule le meilleur chemin (evite glace + spheres),
  4. clique automatiquement la case suivante pour atteindre la dalle jaune.

Touches :
  p     -> lancer le calibrage puis demarrer le bot
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
CLICK_DELAY = 0.11           # pause apres chaque clic (laisse le perso avancer)
LOOP_DELAY = 0.02            # pause entre deux analyses d'image (reactivite max)
PATCH = 6                    # demi-taille du carre echantillonne au centre d'une case
SPHERE_MIN_AREA = 120        # aire mini d'un blob pour etre une sphere
MARGIN = 60                  # marge (px) autour du plateau pour la capture

# Chrono du jeu : il faut toucher la dalle dans les 10 s.
TIME_LIMIT = 10.0            # secondes imparties par dalle
URGENT_AFTER = 6.0           # au-dela, le bot prend des risques pour arriver a temps
PANIC_AFTER = 8.0            # au-dela, chemin le plus court coute que coute

# Couts de A* : la glace est infranchissable, les spheres sont "cheres" mais
# franchissables quand le temps presse -> mouvements complexes et adaptatifs.
COST_SPHERE = 40.0           # penalite case occupee par une sphere
COST_PREDICT = 18.0          # penalite case juste devant une sphere
COST_ADJACENT = 6.0          # penalite case adjacente a une sphere

# Plages de couleurs en HSV (OpenCV: H 0-179, S 0-255, V 0-255)
# Ajuste-les si besoin en observant les logs.
ICE_LOW,    ICE_HIGH    = np.array([85,  40, 150]), np.array([110, 200, 255])   # bleu clair
GREEN_LOW,  GREEN_HIGH  = np.array([70,  60,  40]), np.array([95,  255, 220])   # sphere verte/teal
YELLOW_LOW, YELLOW_HIGH = np.array([22, 120, 150]), np.array([35,  255, 255])   # dalle jaune

pyautogui.FAILSAFE = True    # bouge la souris dans un coin pour couper d'urgence


# ----------------------------------------------------------------------------
# ETAT GLOBAL
# ----------------------------------------------------------------------------
class State:
    def __init__(self):
        self.calibrated = False
        self.running = False
        self.paused = False
        self.quit = False
        # points de reference (centres de 3 cases) en coord ecran
        self.p00 = None   # case (0,0)
        self.p06 = None   # case (0,6)
        self.p60 = None   # case (6,0)
        self.origin = None
        self.col_vec = None
        self.row_vec = None
        self.inv = None
        self.player = (3, 3)          # position estimee du joueur (r,c)
        self.prev_spheres = []        # spheres detectees a la frame precedente
        self.score = 0
        self.last_yellow = None
        self.deadline = None          # instant limite pour atteindre la dalle
        self.bbox = None              # zone de capture {top,left,width,height}


S = State()
mouse_ctl = mouse.Controller()


# ----------------------------------------------------------------------------
# GEOMETRIE ISOMETRIQUE : ecran <-> grille
# ----------------------------------------------------------------------------
def build_transform():
    """Construit la transformation affine a partir des 3 points calibres."""
    o = np.array(S.p00, dtype=float)
    S.origin = o
    S.col_vec = (np.array(S.p06, dtype=float) - o) / (GRID - 1)   # deplacement +1 colonne
    S.row_vec = (np.array(S.p60, dtype=float) - o) / (GRID - 1)   # deplacement +1 ligne
    M = np.array([[S.col_vec[0], S.row_vec[0]],
                  [S.col_vec[1], S.row_vec[1]]], dtype=float)
    S.inv = np.linalg.inv(M)

    # zone de capture englobant les 49 cases + marge
    pts = [cell_to_screen_abs(r, c) for r in range(GRID) for c in range(GRID)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    left = int(min(xs) - MARGIN)
    top = int(min(ys) - MARGIN)
    width = int(max(xs) - min(xs) + 2 * MARGIN)
    height = int(max(ys) - min(ys) + 2 * MARGIN)
    S.bbox = {"top": top, "left": left, "width": width, "height": height}


def cell_to_screen_abs(r, c):
    """Centre d'une case (r,c) en coordonnees ecran absolues."""
    p = S.origin + r * S.row_vec + c * S.col_vec
    return (p[0], p[1])


def cell_to_local(r, c):
    """Centre d'une case en coordonnees locales a la capture."""
    x, y = cell_to_screen_abs(r, c)
    return (int(x - S.bbox["left"]), int(y - S.bbox["top"]))


def screen_local_to_cell(x, y):
    """Convertit un point (local a la capture) en case (r,c) arrondie."""
    abs_x = x + S.bbox["left"]
    abs_y = y + S.bbox["top"]
    d = np.array([abs_x - S.origin[0], abs_y - S.origin[1]], dtype=float)
    c, r = S.inv.dot(d)
    return (int(round(r)), int(round(c)))


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
    On ne bloque pas totalement (sauf glace) pour garder des chemins evasifs
    complexes et pouvoir passer en force quand le chrono l'exige."""
    cost = {}
    for (r, c) in spheres:
        _bump(cost, r, c, COST_SPHERE)
        dr, dc = dirs.get((r, c), (0, 0))
        for step in (1, 2):
            _bump(cost, r + dr * step, c + dc * step, COST_PREDICT / step)
        for ar in (-1, 0, 1):
            for ac in (-1, 0, 1):
                if (ar, ac) != (0, 0):
                    _bump(cost, r + ar, c + ac, COST_ADJACENT)
    return cost


def _bump(cost, r, c, val):
    if in_grid(r, c):
        cost[(r, c)] = cost.get((r, c), 0.0) + val


# ----------------------------------------------------------------------------
# PATHFINDING (A*, 8 directions, evite glace + danger)
# ----------------------------------------------------------------------------
DIRS8 = [(-1, 0), (1, 0), (0, -1), (0, 1),
         (-1, -1), (-1, 1), (1, -1), (1, 1)]


def astar(start, goal, ice, danger, risk=1.0):
    """A* 8 directions. `ice` = infranchissable. `danger` = carte de couts.
    `risk` module l'aversion au danger (1.0 normal, ~0.15 en panique)."""
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
        # ne jamais penaliser la case de depart
        danger.pop(S.player, None)

        path = astar(S.player, yellow, ice_set, danger, risk=risk)
        if not path:  # secours : ignore le danger, garde juste la glace
            path = astar(S.player, yellow, ice_set, {}, risk=0.0)

        if path and len(path) >= 2:
            nxt = path[1]
            # securite : si la case visee est occupee par une sphere et qu'on
            # n'est pas en panique, on attend une frame plutot que de foncer.
            if nxt in spheres and mode == "SAFE":
                time.sleep(LOOP_DELAY)
                continue
            x, y = cell_to_screen_abs(*nxt)
            pyautogui.click(int(x), int(y))
            S.player = nxt
            print(f"[BOT] {mode} t={remaining:4.1f}s pos->{nxt} but{yellow} "
                  f"spheres{spheres} score={S.score}")
            time.sleep(CLICK_DELAY)
        else:
            time.sleep(LOOP_DELAY)

        time.sleep(LOOP_DELAY)


# ----------------------------------------------------------------------------
# CALIBRAGE (via position de la souris + touches 1/2/3/4)
# ----------------------------------------------------------------------------
def calibrate():
    print("\n===== CALIBRAGE =====")
    print("Place la SOURIS au CENTRE de la case demandee puis appuie sur la touche.")
    print(" 1 -> coin haut  (case 0,0)")
    print(" 2 -> case 0,6")
    print(" 3 -> case 6,0")
    print(" 4 -> case ou se trouve TON perso")
    print("Le bot demarre tout seul apres la touche 4.\n")


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

    if k == 'p' and not S.calibrated:
        calibrate()
        S.calibrating = True
        return

    if getattr(S, 'calibrating', False):
        pos = mouse_ctl.position
        if k == '1':
            S.p00 = pos; print(f"  case (0,0) = {pos}")
        elif k == '2':
            S.p06 = pos; print(f"  case (0,6) = {pos}")
        elif k == '3':
            S.p60 = pos; print(f"  case (6,0) = {pos}")
        elif k == '4':
            if not (S.p00 and S.p06 and S.p60):
                print("  !! calibre d'abord 1, 2 et 3 !!")
                return
            build_transform()
            S.player = screen_local_to_cell(pos[0] - S.bbox["left"],
                                            pos[1] - S.bbox["top"])
            S.calibrated = True
            S.calibrating = False
            S.running = True
            print(f"  perso a {S.player} | zone capture {S.bbox}")
            print("[BOT] Calibrage OK, demarrage !")


def main():
    print("Pret. Ouvre le jeu, place la fenetre bien visible, puis appuie sur 'p'.")
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    bot_loop()
    listener.stop()


if __name__ == "__main__":
    main()
