"""색 · 글꼴 · 공용 위젯."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#EEF2F7"
CARD = "#FFFFFF"
CARD_ALT = "#F7F9FC"
SIDEBAR = "#0B2545"
SIDEBAR_ACTIVE = "#13315C"
SIDEBAR_TEXT = "#C9D6E8"
TEXT = "#172033"
MUTED = "#5F6B7A"
ACCENT = "#0D63C7"
ACCENT_DARK = "#084A96"
ACCENT_SOFT = "#EAF3FF"
GOOD = "#16834A"
GOOD_SOFT = "#E8F6EE"
BAD = "#C43D3D"
BAD_SOFT = "#FDEEEE"
WARN = "#B26A00"
WARN_SOFT = "#FFF4E0"
BORDER = "#D5DEE9"
FONT = "Malgun Gothic"

REGION_COLORS = {
    "KOREA": "#0D63C7",
    "JAPAN": "#C43D3D",
    "AUSTRALIA": "#16834A",
    "UK": "#6B3FA0",
    "OTHER": "#5F6B7A",
}


def nfmt(v) -> str:
    try:
        return f"{int(v):,}"
    except Exception:
        return "0"


def pct(v) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except Exception:
        return "0.0%"


def configure_styles(root) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", font=(FONT, 9))
    style.configure("Treeview", rowheight=28, font=(FONT, 9), background="#FFFFFF",
                    fieldbackground="#FFFFFF", foreground=TEXT, bordercolor=BORDER)
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFFFFF")])
    style.configure("Treeview.Heading", font=(FONT, 9, "bold"), background="#E7EEF7",
                    foreground=TEXT, relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", "#DCE7F4")])
    style.configure("TButton", font=(FONT, 9), padding=(10, 6))
    style.configure("Accent.TButton", font=(FONT, 10, "bold"), foreground="#FFFFFF",
                    background=ACCENT, borderwidth=0, padding=(14, 9))
    style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK),
                                            ("disabled", "#9DB7D9")],
              foreground=[("disabled", "#EEF3FA")])
    style.configure("Big.TButton", font=(FONT, 12, "bold"), foreground="#FFFFFF",
                    background=ACCENT, borderwidth=0, padding=(18, 13))
    style.map("Big.TButton", background=[("active", ACCENT_DARK), ("disabled", "#9DB7D9")])
    style.configure("Small.TButton", font=(FONT, 8), padding=(7, 4))
    for name, bg in (("TCheckbutton", CARD), ("TRadiobutton", CARD)):
        style.configure(name, font=(FONT, 9), background=bg, foreground=TEXT)
        style.map(name, background=[("active", bg)])
    style.configure("Page.TRadiobutton", font=(FONT, 9), background=BG, foreground=TEXT)
    style.map("Page.TRadiobutton", background=[("active", BG)])
    style.configure("Mode.TRadiobutton", font=(FONT, 10, "bold"), background=CARD, foreground=TEXT)
    style.map("Mode.TRadiobutton", background=[("active", CARD)])
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", font=(FONT, 9, "bold"), padding=(14, 7))
    style.configure("TCombobox", padding=4)
    style.configure("TEntry", padding=4)
    style.configure("Horizontal.TProgressbar", thickness=14)


def card(parent, padx=16, pady=14, bg=CARD, **pack):
    f = tk.Frame(parent, bg=bg, padx=padx, pady=pady, highlightthickness=1, highlightbackground=BORDER)
    if pack is not None:
        opts = {"fill": "x", "pady": (0, 12)}
        opts.update(pack)
        f.pack(**opts)
    return f


def section_title(parent, text, sub=None, bg=CARD, step=None):
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x")
    if step is not None:
        tk.Label(row, text=str(step), bg=ACCENT, fg="#FFFFFF", font=(FONT, 9, "bold"),
                 width=2).pack(side="left", padx=(0, 8))
    tk.Label(row, text=text, bg=bg, fg=TEXT, font=(FONT, 12, "bold")).pack(side="left")
    if sub:
        tk.Label(parent, text=sub, bg=bg, fg=MUTED, font=(FONT, 9), justify="left",
                 wraplength=1000).pack(anchor="w", pady=(4, 0))
    return row


class ScrollFrame(tk.Frame):
    """세로 스크롤 영역. 마우스 휠은 포인터가 이 영역 위에 있을 때만 동작."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-event.delta / 120) * 2 or (-1 if event.delta > 0 else 1), "units")
        except Exception:
            pass


def kpi_box(parent, label, value, sub="", fg=TEXT, bg=CARD):
    box = tk.Frame(parent, bg=bg, padx=14, pady=10, highlightthickness=1, highlightbackground=BORDER)
    tk.Label(box, text=label, bg=bg, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
    tk.Label(box, text=value, bg=bg, fg=fg, font=(FONT, 18, "bold")).pack(anchor="w")
    tk.Label(box, text=sub, bg=bg, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
    return box


def make_tree(parent, columns, widths=None, height=None, show="headings"):
    frame = tk.Frame(parent, bg=CARD)
    tree = ttk.Treeview(frame, columns=columns, show=show, height=height or 10)
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    for i, c in enumerate(columns):
        tree.heading(c, text=c)
        w = (widths or {}).get(c, 110)
        tree.column(c, width=w, minwidth=50, anchor="w" if w >= 160 else "center")
    return frame, tree
