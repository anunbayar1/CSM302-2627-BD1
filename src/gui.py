#!/usr/bin/env python3
"""Tkinter UI: live buffer animation for the Producer-Consumer simulation."""
import tkinter as tk
from tkinter import ttk, messagebox

from bounded_buffer import Simulation

COLORS = {"idle": "#d0d0d0", "sleeping": "#bdbdbd", "producing": "#4caf50",
          "waiting": "#ffc107", "consuming": "#2196f3", "paused": "#ab47bc",
          "stopped": "#757575"}
DEFAULTS = dict(size="5", prod="2", cons="2", psleep="1.0", csleep="1.0")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Producer-Consumer: bounded buffer")
        self.sim = None
        self.seen = 0
        self.vars = {k: tk.StringVar(value=v) for k, v in DEFAULTS.items()}
        self.start_paused = tk.BooleanVar(value=False)
        self._controls()
        self.canvas = tk.Canvas(self, width=980, height=450, bg="white")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.logbox = tk.Text(self, height=9, state="disabled")
        self.logbox.grid(row=2, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self._tick()

    def _controls(self):
        f = ttk.Frame(self, padding=6)
        f.grid(row=0, column=0, sticky="ew")
        fields = [("Buffer size (1-20)", "size"), ("Producers (1-10)", "prod"),
                  ("Consumers (1-10)", "cons"), ("Prod. max sleep s", "psleep"),
                  ("Cons. max sleep s", "csleep")]
        for i, (label, key) in enumerate(fields):
            ttk.Label(f, text=label).grid(row=0, column=i, padx=4)
            ttk.Entry(f, textvariable=self.vars[key], width=10).grid(row=1, column=i, padx=4)
        ttk.Checkbutton(f, text="Start paused (step mode)",
                        variable=self.start_paused).grid(row=1, column=5, padx=8)
        b = ttk.Frame(f)
        b.grid(row=2, column=0, columnspan=6, pady=6, sticky="w")
        self.btn_pause = ttk.Button(b, text="Pause", command=self.on_pause)
        for text, cmd in [("Start", self.on_start), (None, None), ("Step", self.on_step),
                          ("Stop", self.on_stop), ("Reset", self.on_reset)]:
            w = self.btn_pause if text is None else ttk.Button(b, text=text, command=cmd)
            w.pack(side="left", padx=3)

    # ---- actions
    def on_start(self):
        if self.sim and not self.sim.snapshot()["stopped"]:
            return
        try:
            v = self.vars
            sim = Simulation(v["size"].get(), v["prod"].get(), v["cons"].get(),
                             v["psleep"].get(), v["csleep"].get())
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return
        self._clear_log()
        self.sim = sim
        if self.start_paused.get():
            sim.pause()
        sim.start()

    def on_pause(self):
        if self.sim:
            self.sim.resume() if self.sim.paused.is_set() else self.sim.pause()

    def on_step(self):
        if self.sim:
            self.sim.step()

    def on_stop(self):
        if self.sim:
            self.sim.stop_all()

    def on_reset(self):
        if self.sim:
            self.sim.stop_all()
        self.sim = None
        for k, v in DEFAULTS.items():
            self.vars[k].set(v)
        self._clear_log()

    def _clear_log(self):
        self.seen = 0
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

    # ---- drawing
    def _tick(self):
        self._draw()
        self.after(100, self._tick)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        if not self.sim:
            c.create_text(490, 200, text="Set parameters and press Start",
                          font=("Arial", 16), fill="#888")
            self._legend(c)
            return
        s = self.sim.snapshot()
        self.btn_pause.config(text="Resume" if s["paused"] else "Pause")
        n = len(s["slots"])
        w = min(60, 920 // n)
        x0 = 30
        c.create_text(x0, 20, anchor="w", font=("Arial", 12, "bold"),
                      text="Circular buffer")
        for i, val in enumerate(s["slots"]):
            x = x0 + i * w
            c.create_rectangle(x, 50, x + w, 100, fill="#ff9800" if val is not None else "#eeeeee",
                               outline="#d32f2f" if i == s["last"] else "#555",
                               width=3 if i == s["last"] else 1)
            c.create_text(x + w / 2, 75, text="" if val is None else str(val),
                          font=("Arial", 13, "bold"))
            c.create_text(x + w / 2, 112, text=str(i), fill="#888")
        ox = x0 + s["out_idx"] * w + w / 2
        ix = x0 + s["in_idx"] * w + w / 2
        c.create_text(ox, 38, text="out v", fill="#1565c0", font=("Arial", 10, "bold"))
        c.create_text(ix, 128, text="^ in", fill="#2e7d32", font=("Arial", 10, "bold"))
        # workers
        prods = [k for k in s["states"] if k.startswith("P")]
        cons = [k for k in s["states"] if k.startswith("C")]
        for names, title, x in ((prods, "Producers", 30), (cons, "Consumers", 270)):
            c.create_text(x, 160, anchor="w", text=title, font=("Arial", 12, "bold"))
            for j, name in enumerate(names):
                st = s["states"][name]
                y = 180 + j * 26
                c.create_rectangle(x, y, x + 200, y + 22, fill=COLORS.get(st, "#fff"), outline="#555")
                c.create_text(x + 8, y + 11, anchor="w", text=f"{name}: {st}")
        # semaphores + counters
        c.create_text(540, 160, anchor="w", text="Synchronization", font=("Arial", 12, "bold"))
        lines = [f"empty = {s['empty']}", f"full  = {s['full']}",
                 f"mutex = {'LOCKED' if s['mutex_locked'] else 'free'}",
                 f"produced = {s['produced']}", f"consumed = {s['consumed']}",
                 f"in buffer = {s['produced'] - s['consumed']}"]
        for j, t in enumerate(lines):
            c.create_text(540, 185 + j * 22, anchor="w", text=t, font=("Courier", 12))
        self._legend(c)
        new = s["log"][self.seen:]
        if new:
            self.logbox.config(state="normal")
            self.logbox.insert("end", "\n".join(new) + "\n")
            self.logbox.see("end")
            self.logbox.config(state="disabled")
            self.seen = len(s["log"])

    def _legend(self, c):
        c.create_text(760, 160, anchor="w", text="Legend", font=("Arial", 12, "bold"))
        items = [("sleeping", "sleeping"), ("producing", "producing (item generated)"),
                 ("waiting", "waiting on semaphore/mutex"), ("consuming", "consuming"),
                 ("paused", "paused (waiting for Step)")]
        for j, (k, label) in enumerate(items):
            y = 182 + j * 24
            c.create_rectangle(760, y, 780, y + 16, fill=COLORS[k], outline="#555")
            c.create_text(788, y + 8, anchor="w", text=label)
        c.create_rectangle(760, 304, 780, 320, fill="#ff9800", outline="#555")
        c.create_text(788, 312, anchor="w", text="slot full (value)")
        c.create_rectangle(760, 328, 780, 344, fill="#eee", outline="#d32f2f", width=2)
        c.create_text(788, 336, anchor="w", text="last changed slot")


if __name__ == "__main__":
    App().mainloop()