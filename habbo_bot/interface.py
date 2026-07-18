"""
Interface graphique de controle du Habbo Bot.

- Presets : Prudent / Equilibre / Agressif / EXTREME
- Curseurs en direct : vitesse de clic, vitesse perso, horizon, marges,
  cout d'anticipation, sandwich, marge de temporisation, incertitude...
- Toggles : Diagonales, Temporiser (attendre sur la dalle), Esquiver, Debug
- Affichage LIVE : etat, score, meilleur score, morts, mode, action, boules, FPS
- Boutons : Calibrer & Demarrer, Pause, Stop, Recapturer plateau

Lance simplement ce fichier (ou lancer_interface.bat).
"""

import threading
import tkinter as tk
from tkinter import ttk

import habbo_bot as bot


# ---- Presets (valeurs appliquees aux parametres du bot) ---------------------
PRESETS = {
    "Prudent": dict(CLICK_DELAY=0.05, MOVE_SPEED=2.6, HORIZON=18, MARGIN_HARD=2,
                    MARGIN_SOFT=3, SOFT_COST=6.0, SANDWICH_COST=16.0,
                    HOLD_BUFFER=2.2, UNC_GROW=2, LOOP_DELAY=0.008,
                    TEMPORIZE=True, DODGE=True, DIAGONALS=True),
    "Equilibre": dict(CLICK_DELAY=0.03, MOVE_SPEED=2.9, HORIZON=16, MARGIN_HARD=1,
                      MARGIN_SOFT=2, SOFT_COST=3.5, SANDWICH_COST=12.0,
                      HOLD_BUFFER=1.6, UNC_GROW=3, LOOP_DELAY=0.006,
                      TEMPORIZE=True, DODGE=True, DIAGONALS=True),
    "Agressif": dict(CLICK_DELAY=0.02, MOVE_SPEED=3.2, HORIZON=14, MARGIN_HARD=1,
                     MARGIN_SOFT=2, SOFT_COST=2.5, SANDWICH_COST=9.0,
                     HOLD_BUFFER=1.1, UNC_GROW=4, LOOP_DELAY=0.004,
                     TEMPORIZE=True, DODGE=True, DIAGONALS=True),
    "EXTREME": dict(CLICK_DELAY=0.012, MOVE_SPEED=3.6, HORIZON=14, MARGIN_HARD=1,
                    MARGIN_SOFT=2, SOFT_COST=2.0, SANDWICH_COST=8.0,
                    HOLD_BUFFER=0.8, UNC_GROW=5, LOOP_DELAY=0.002,
                    TEMPORIZE=True, DODGE=True, DIAGONALS=True),
}

# ---- Curseurs : (attribut bot, libelle, min, max, resolution) ---------------
SLIDERS = [
    ("CLICK_DELAY", "Vitesse de clic (s) - petit = rapide", 0.005, 0.15, 0.001),
    ("LOOP_DELAY", "Rafraichissement analyse (s)", 0.002, 0.03, 0.001),
    ("MOVE_SPEED", "Vitesse perso (cases/s)", 1.5, 5.0, 0.1),
    ("HORIZON", "Horizon de prevision (pas)", 8, 22, 1),
    ("MARGIN_HARD", "Rayon MORTEL (cases)", 1, 3, 1),
    ("MARGIN_SOFT", "Rayon ANTICIPATION (cases)", 1, 4, 1),
    ("SOFT_COST", "Cout anticipation (evitement)", 0.0, 15.0, 0.5),
    ("SANDWICH_COST", "Cout anti-sandwich", 0.0, 30.0, 1.0),
    ("TURN_COST", "Penalite de virage (tout droit)", 0.0, 3.0, 0.1),
    ("HOLD_BUFFER", "Marge avant de foncer (s)", 0.3, 3.0, 0.1),
    ("UNC_GROW", "Incertitude boules (petit = prudent)", 1, 8, 1),
    ("URGENT_AFTER", "Passage URGENT a (s ecoulees)", 3.0, 9.0, 0.5),
    ("PANIC_AFTER", "Passage PANIC a (s ecoulees)", 4.0, 9.5, 0.5),
    ("FACE_TH", "(inutilise) seuil visage", 0.3, 0.9, 0.05),
]

TOGGLES = [
    ("DIAGONALS", "Diagonales (gagne de l'espace)"),
    ("TEMPORIZE", "Temporiser (attendre sur/pres de la dalle)"),
    ("DODGE", "Esquiver activement les boules"),
    ("SHOW_DEBUG", "Fenetre de debug (grille live)"),
]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Habbo Bot - Panneau de controle")
        root.configure(bg="#12141c")
        root.geometry("560x900")

        self.vars = {}

        # --- barre d'etat live -----------------------------------------------
        top = tk.Frame(root, bg="#1b1e2b")
        top.pack(fill="x", padx=8, pady=8)
        self.status = tk.Label(top, text="Arrete", font=("Consolas", 12, "bold"),
                               fg="#8be9fd", bg="#1b1e2b")
        self.status.pack(anchor="w", padx=10, pady=(8, 0))
        self.live = tk.Label(top, text="", font=("Consolas", 11), justify="left",
                             fg="#f8f8f2", bg="#1b1e2b")
        self.live.pack(anchor="w", padx=10, pady=(2, 8))

        # --- boutons de controle ---------------------------------------------
        ctrl = tk.Frame(root, bg="#12141c")
        ctrl.pack(fill="x", padx=8)
        self._btn(ctrl, "▶ Calibrer & Demarrer", self.start, "#50fa7b")
        self._btn(ctrl, "⏸ Pause / Reprendre", self.toggle_pause, "#f1fa8c")
        self._btn(ctrl, "■ Stop", self.stop, "#ff5555")
        self._btn(ctrl, "⟳ Recalibrer plateau", self.recalib, "#8be9fd")

        # --- presets ----------------------------------------------------------
        pf = tk.LabelFrame(root, text="Presets", fg="#bd93f9", bg="#12141c",
                           font=("Consolas", 10, "bold"))
        pf.pack(fill="x", padx=8, pady=8)
        row = tk.Frame(pf, bg="#12141c")
        row.pack(fill="x", pady=4)
        for name in PRESETS:
            color = "#ff79c6" if name == "EXTREME" else "#6272a4"
            b = tk.Button(row, text=name, command=lambda n=name: self.apply_preset(n),
                          bg=color, fg="white", relief="flat", font=("Consolas", 10, "bold"),
                          padx=8, pady=6)
            b.pack(side="left", expand=True, fill="x", padx=3)

        # --- toggles ----------------------------------------------------------
        tf = tk.LabelFrame(root, text="Comportements", fg="#bd93f9", bg="#12141c",
                           font=("Consolas", 10, "bold"))
        tf.pack(fill="x", padx=8, pady=4)
        for attr, label in TOGGLES:
            v = tk.BooleanVar(value=getattr(bot, attr))
            self.vars[attr] = v
            cb = tk.Checkbutton(tf, text=label, variable=v,
                                command=lambda a=attr: self.apply_toggle(a),
                                bg="#12141c", fg="#f8f8f2", selectcolor="#282a36",
                                activebackground="#12141c", activeforeground="#50fa7b",
                                font=("Consolas", 10), anchor="w")
            cb.pack(fill="x", padx=10, pady=1)

        # --- curseurs ---------------------------------------------------------
        sf = tk.LabelFrame(root, text="Reglages fins (en direct)", fg="#bd93f9",
                           bg="#12141c", font=("Consolas", 10, "bold"))
        sf.pack(fill="both", expand=True, padx=8, pady=4)
        for attr, label, lo, hi, res in SLIDERS:
            fr = tk.Frame(sf, bg="#12141c")
            fr.pack(fill="x", padx=8, pady=1)
            tk.Label(fr, text=label, bg="#12141c", fg="#f8f8f2",
                     font=("Consolas", 9), anchor="w").pack(anchor="w")
            v = tk.DoubleVar(value=float(getattr(bot, attr)))
            self.vars[attr] = v
            s = tk.Scale(fr, from_=lo, to=hi, resolution=res, orient="horizontal",
                         variable=v, command=lambda _v, a=attr: self.apply_slider(a),
                         bg="#12141c", fg="#8be9fd", troughcolor="#282a36",
                         highlightthickness=0, font=("Consolas", 8), length=520)
            s.pack(fill="x")

        self.refresh()

    # ------------------------------------------------------------------ utils
    def _btn(self, parent, text, cmd, color):
        tk.Button(parent, text=text, command=cmd, bg=color, fg="#12141c",
                  relief="flat", font=("Consolas", 10, "bold"), padx=6, pady=6
                  ).pack(side="left", expand=True, fill="x", padx=3, pady=4)

    def apply_slider(self, attr):
        val = self.vars[attr].get()
        if attr in ("HORIZON", "MARGIN_HARD", "MARGIN_SOFT", "UNC_GROW"):
            val = int(round(val))
        setattr(bot, attr, val)

    def apply_toggle(self, attr):
        setattr(bot, attr, bool(self.vars[attr].get()))

    def apply_preset(self, name):
        for attr, val in PRESETS[name].items():
            setattr(bot, attr, val)
            if attr in self.vars:
                self.vars[attr].set(val)
        self.status.config(text=f"Preset applique : {name}")

    # ---------------------------------------------------------------- actions
    def start(self):
        def do():
            if bot.detect_board():
                bot.S.last_yellow = None
                bot.S.deadline = None
                bot.S.move_accum = 0.0
                bot.S.last_t = None
                bot.S.no_yellow = 0
                bot.S.playing = False
                bot.S.score = 0
                bot.S.reached = False
                bot.S.yellow_gone = False
                bot.S.prev_gray = None
                bot.S.commit = None
                bot.S.commit_dir = (0, 0)
                bot.tracker.reset()
                bot.S.paused = False
                bot.S.running = True
        threading.Thread(target=do, daemon=True).start()

    def recalib(self):
        threading.Thread(target=lambda: bot.detect_board(), daemon=True).start()

    def toggle_pause(self):
        bot.S.paused = not bot.S.paused

    def stop(self):
        bot.S.running = False

    # ------------------------------------------------------------------- live
    def refresh(self):
        s = bot.S
        if not s.running:
            st, col = "ARRETE", "#ff5555"
        elif s.paused:
            st, col = "PAUSE", "#f1fa8c"
        else:
            st, col = "EN JEU", "#50fa7b"
        self.status.config(text=f"Etat : {st}", fg=col)
        self.live.config(text=(
            f"Score : {s.score}    Meilleur : {s.best_score}    Morts : {s.deaths}\n"
            f"Mode : {s.mode:6s} Action : {s.act:5s}   Temps : {s.remaining:4.1f}s\n"
            f"Boules : {s.nballs}   Prudence : {s.caution:.2f}   FPS : {s.fps:4.0f}"
        ))
        self.root.after(120, self.refresh)


def main():
    # demarre la boucle du bot en tache de fond (elle attend running=True)
    threading.Thread(target=bot.bot_loop, daemon=True).start()
    root = tk.Tk()
    App(root)
    root.mainloop()
    bot.S.quit = True


if __name__ == "__main__":
    main()
