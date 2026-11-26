"""② 리뷰 수집: 예약 Excel → 보고 단위(주/월) → 지사 → OTA → Chrome 연결 확인 → 수집."""
from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from collectors.config import CHANNEL_DISPLAY, SUPPORTED_CHANNELS
from core.browser_profiles import REGION_LABELS, area_group
from core.chrome_check import LOGIN_REQUIRED, OK
from core.excel_loader import load_bookings
from core.periods import list_periods
from core.pipeline import default_output_path, run_phase1, split_groups
from core.scope import build_scope
from ui import theme as T

APP_DIR = Path(__file__).resolve().parents[1]


class CollectPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.BG)
        self.app = app
        self.loaded = None
        self.excel_path = ""
        self.output_dir = ""
        self.nav_hint = "예약 Excel 선택"

        self.file_var = tk.StringVar(value="예약 Excel(틴트 리포트)을 선택하세요")
        self.file_meta_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="week")
        self.period_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        self.period_hint_var = tk.StringVar(value="")
        self.area_all_var = tk.BooleanVar(value=True)
        self.channel_all_var = tk.BooleanVar(value=True)
        self.area_vars: dict[str, tk.BooleanVar] = {}
        self.country_vars: dict[str, tk.BooleanVar] = {}
        self.channel_vars: dict[str, tk.BooleanVar] = {}
        self.unsupported_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value="")
        self.split_var = tk.StringVar(value="none")       # none / country / area
        self.combined_var = tk.BooleanVar(value=True)
        self.files_var = tk.StringVar(value="")
        self.summary_vars = {k: tk.StringVar(value="-") for k in ("total", "eligible", "selected", "unsupported")}
        self._periods = {}
        self.log_q: queue.Queue = queue.Queue()
        self.worker = None

        self.form = T.ScrollFrame(self)
        self.form.pack(fill="both", expand=True)
        self.progress_view = tk.Frame(self, bg=T.BG)
        self._build_form(self.form.body)
        self._build_progress(self.progress_view)
        self.start_var.trace_add("write", lambda *_: self.update_preview())
        self.end_var.trace_add("write", lambda *_: self.update_preview())

    @property
    def manager(self):
        return self.app.manager

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------
    def _build_form(self, body):
        wrap = tk.Frame(body, bg=T.BG)
        wrap.pack(fill="x", padx=26, pady=20)
        tk.Label(wrap, text="리뷰 수집", bg=T.BG, fg=T.TEXT, font=(T.FONT, 18, "bold")).pack(anchor="w")
        tk.Label(wrap, text="ReviewCrawler v25 처럼 주단위 / 월단위로 기간을 고르고, 국가(지사)를 선택해 수집합니다. "
                            "날짜 기준은 예약 Excel 의 투어일(Date)입니다.",
                 bg=T.BG, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(2, 14))

        # 1. 예약 Excel
        c = T.card(wrap)
        head = T.section_title(c, "예약 Excel", step=1)
        ttk.Button(head, text="파일 선택", style="Accent.TButton", command=self.choose_file).pack(side="right")
        tk.Label(c, textvariable=self.file_var, bg=T.CARD, fg=T.TEXT, font=(T.FONT, 10, "bold")).pack(anchor="w", pady=(10, 1))
        tk.Label(c, textvariable=self.file_meta_var, bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w")

        # 2. 보고 단위
        c = T.card(wrap)
        T.section_title(c, "보고 단위 · 기간", step=2)
        modes = tk.Frame(c, bg=T.CARD)
        modes.pack(fill="x", pady=(10, 6))
        for text, val in (("주단위  (월~일 · 성과제 주간)", "week"),
                          ("월단위  (1일~말일)", "month"),
                          ("직접 설정", "custom")):
            ttk.Radiobutton(modes, text=text, value=val, variable=self.mode_var, style="Mode.TRadiobutton",
                            command=self.on_mode_change).pack(side="left", padx=(0, 22))
        pick = tk.Frame(c, bg=T.CARD)
        pick.pack(fill="x", pady=(4, 0))
        self.period_label = tk.Label(pick, text="주 선택", bg=T.CARD, fg=T.MUTED, width=8, anchor="w")
        self.period_label.pack(side="left")
        self.period_combo = ttk.Combobox(pick, textvariable=self.period_var, state="disabled", width=62)
        self.period_combo.pack(side="left", padx=(4, 18))
        self.period_combo.bind("<<ComboboxSelected>>", lambda e: self.on_period_pick())
        tk.Label(pick, text="시작일", bg=T.CARD, fg=T.MUTED).pack(side="left")
        self.start_entry = ttk.Entry(pick, textvariable=self.start_var, width=12)
        self.start_entry.pack(side="left", padx=(5, 10))
        tk.Label(pick, text="종료일", bg=T.CARD, fg=T.MUTED).pack(side="left")
        self.end_entry = ttk.Entry(pick, textvariable=self.end_var, width=12)
        self.end_entry.pack(side="left", padx=(5, 10))
        self.sheet_btn = ttk.Button(pick, text="시트 전체", style="Small.TButton", command=self.set_sheet_range)
        self.sheet_btn.pack(side="left")
        tk.Label(c, textvariable=self.period_hint_var, bg=T.CARD, fg=T.ACCENT, font=(T.FONT, 9)).pack(anchor="w", pady=(6, 0))

        # 3. 지사
        c = T.card(wrap)
        T.section_title(c, "지사 (국가 선택 → Area)", step=3)
        self.country_box = tk.Frame(c, bg=T.CARD)
        self.country_box.pack(fill="x", pady=(10, 4))
        self.area_box = tk.Frame(c, bg=T.CARD)
        self.area_box.pack(fill="x")

        # 4. OTA
        c = T.card(wrap)
        T.section_title(c, "리뷰 채널 (OTA)", step=4)
        self.channel_box = tk.Frame(c, bg=T.CARD)
        self.channel_box.pack(fill="x", pady=(10, 4))
        tk.Label(c, textvariable=self.unsupported_var, bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9),
                 wraplength=1000, justify="left").pack(anchor="w")

        # 5. Chrome 연결 미리보기
        c = T.card(wrap)
        head = T.section_title(c, "Chrome 연결 확인 (지역별)", step=5)
        ttk.Button(head, text="① 지역별 Chrome 화면", command=lambda: self.app.show("chrome")).pack(side="right")
        tk.Label(c, text="선택한 예약을 어떤 지역 Chrome 으로 수집하는지 보여 줍니다. 꺼진 Chrome 은 수집 시작 때 자동으로 켜집니다.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(4, 8))
        frame, self.route_tree = T.make_tree(
            c, ("Chrome 계정", "Area", "OTA", "예약", "Chrome", "로그인"),
            {"Chrome 계정": 150, "Area": 260, "OTA": 220, "예약": 70, "Chrome": 90, "로그인": 170}, height=6)
        frame.pack(fill="x")
        self.route_tree.tag_configure("bad", foreground=T.BAD)
        self.route_tree.tag_configure("warn", foreground=T.WARN)

        # 6. 요약 + 실행
        c = T.card(wrap)
        T.section_title(c, "수집 대상", step=6)
        grid = tk.Frame(c, bg=T.CARD)
        grid.pack(fill="x", pady=(10, 8))
        for i, (label, key, bg) in enumerate((("전체 예약", "total", "#F2F5F9"),
                                              ("지원 OTA 예약", "eligible", T.ACCENT_SOFT),
                                              ("이번에 수집", "selected", T.GOOD_SOFT),
                                              ("미지원 에이전시", "unsupported", T.WARN_SOFT))):
            box = tk.Frame(grid, bg=bg, highlightthickness=1, highlightbackground=T.BORDER)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0))
            grid.grid_columnconfigure(i, weight=1)
            tk.Label(box, text=label, bg=bg, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", padx=12, pady=(9, 2))
            tk.Label(box, textvariable=self.summary_vars[key], bg=bg, fg=T.TEXT,
                     font=(T.FONT, 17, "bold")).pack(anchor="w", padx=12, pady=(0, 9))
        split = tk.Frame(c, bg=T.CARD)
        split.pack(fill="x", pady=(2, 4))
        tk.Label(split, text="결과 Excel", bg=T.CARD, fg=T.MUTED, width=9, anchor="w").pack(side="left")
        for text, val in (("통합 1개", "none"), ("국가별로 나눠서", "country"), ("지역(Area)별로 나눠서", "area")):
            ttk.Radiobutton(split, text=text, value=val, variable=self.split_var,
                            command=self.update_preview).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(split, text="통합 파일도 함께 저장", variable=self.combined_var,
                        command=self.update_preview).pack(side="left", padx=(10, 0))
        tk.Label(c, textvariable=self.files_var, bg=T.CARD, fg=T.ACCENT, font=(T.FONT, 9),
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))
        out = tk.Frame(c, bg=T.CARD)
        out.pack(fill="x", pady=(2, 10))
        tk.Label(out, text="결과 저장", bg=T.CARD, fg=T.MUTED).pack(side="left")
        tk.Label(out, textvariable=self.output_var, bg=T.CARD, fg=T.TEXT, font=(T.FONT, 9)).pack(side="left", padx=8)
        ttk.Button(out, text="저장 폴더 변경", style="Small.TButton", command=self.choose_output_dir).pack(side="right")
        self.run_btn = ttk.Button(c, text="▶  리뷰 수집 시작", style="Big.TButton", command=self.start)
        self.run_btn.pack(fill="x")

        self._render_areas()
        self._render_channels()
        self.on_mode_change()

    def _build_progress(self, f):
        tk.Label(f, text="리뷰 수집 중", bg=T.BG, fg=T.TEXT, font=(T.FONT, 18, "bold")).pack(anchor="w", padx=30, pady=(24, 2))
        tk.Label(f, text="지역별 Chrome 에 차례로 연결해 수집합니다. 수집 중에는 Chrome 창을 닫지 마세요.",
                 bg=T.BG, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", padx=30)
        self.step_var = tk.StringVar(value="준비 중")
        tk.Label(f, textvariable=self.step_var, bg=T.BG, fg=T.ACCENT, font=(T.FONT, 10, "bold")).pack(anchor="w", padx=30, pady=(14, 4))
        self.pbar = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.pbar.pack(fill="x", padx=30, pady=(0, 12))
        box = tk.Frame(f, bg="#101826", padx=10, pady=10)
        box.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        self.log_text = tk.Text(box, bg="#101826", fg="#E5E7EB", font=("Consolas", 9), wrap="word", relief="flat")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------------
    # 파일 · 기간
    # ------------------------------------------------------------------
    def choose_file(self, path: str | None = None):
        path = path or filedialog.askopenfilename(
            title="예약 Excel 선택", filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if not path:
            return
        try:
            loaded = load_bookings(path)
        except Exception as exc:
            messagebox.showerror("파일 오류", str(exc))
            return
        self.loaded, self.excel_path = loaded, path
        self.file_var.set(Path(path).name)
        self.file_meta_var.set(f"시트 {loaded.sheet_name}  ·  {loaded.min_date:%Y-%m-%d} ~ {loaded.max_date:%Y-%m-%d}"
                               f"  ·  예약 {len(loaded.df):,}건  ·  Area {len(loaded.areas)}개")
        self.period_var.set("")
        self.area_all_var.set(True)
        self.channel_all_var.set(True)
        self._render_areas()
        self._render_channels()
        self.on_mode_change()

    def on_mode_change(self):
        mode = self.mode_var.get()
        custom = mode == "custom"
        for w in (self.start_entry, self.end_entry):
            w.configure(state="normal" if custom else "disabled")
        self.sheet_btn.configure(state="normal" if custom else "disabled")
        if custom or not self.loaded:
            self.period_combo.configure(state="disabled", values=[])
            self.period_label.configure(text="주/월 선택")
            if custom and self.loaded and not self.start_var.get():
                self.set_sheet_range()
            self.update_preview()
            return
        self.period_label.configure(text="주 선택" if mode == "week" else "월 선택")
        periods = list_periods(self.loaded.df["Date"], mode, self.loaded.min_date, self.loaded.max_date)
        self._periods = {p.label: p for p in periods}
        labels = list(self._periods)
        self.period_combo.configure(state="readonly" if labels else "disabled", values=labels)
        if self.period_var.get() not in self._periods:
            self.period_var.set(labels[0] if labels else "")
        self.on_period_pick()

    def on_period_pick(self):
        p = self._periods.get(self.period_var.get())
        if not p:
            return
        self.start_var.set(f"{p.start:%Y-%m-%d}")
        self.end_var.set(f"{p.end:%Y-%m-%d}")

    def set_sheet_range(self):
        if self.loaded:
            self.start_var.set(f"{self.loaded.min_date:%Y-%m-%d}")
            self.end_var.set(f"{self.loaded.max_date:%Y-%m-%d}")

    def _dates(self):
        try:
            return pd.Timestamp(self.start_var.get()).normalize(), pd.Timestamp(self.end_var.get()).normalize()
        except Exception:
            return None, None

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="결과 저장 폴더", initialdir=self.output_dir or (
            str(Path(self.excel_path).parent) if self.excel_path else None))
        if d:
            self.output_dir = d
            self.update_preview()

    # ------------------------------------------------------------------
    # 지사 · 채널
    # ------------------------------------------------------------------
    def _render_areas(self):
        for box in (self.country_box, self.area_box):
            for w in box.winfo_children():
                w.destroy()
        self.area_vars, self.country_vars = {}, {}
        if not self.loaded:
            tk.Label(self.area_box, text="예약 Excel 을 먼저 선택하세요.", bg=T.CARD, fg=T.MUTED).pack(anchor="w")
            return
        groups: dict[str, list[str]] = {}
        for a in self.loaded.areas:
            groups.setdefault(area_group(a), []).append(a)
        tk.Label(self.country_box, text="국가", bg=T.CARD, fg=T.MUTED, width=6, anchor="w").pack(side="left")
        for g in REGION_LABELS:
            if g not in groups:
                continue
            n = int(self.loaded.df["Area"].isin(groups[g]).sum())
            var = tk.BooleanVar(value=True)
            self.country_vars[g] = var
            ttk.Checkbutton(self.country_box, text=f"{REGION_LABELS[g]} ({n:,}건)", variable=var,
                            command=lambda g=g: self.on_country(g)).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(self.area_box, text="ALL", variable=self.area_all_var,
                        command=self.toggle_all_areas).grid(row=0, column=0, sticky="w", padx=(0, 14), pady=3)
        col = 1
        row = 0
        for g in REGION_LABELS:
            for a in groups.get(g, []):
                var = tk.BooleanVar(value=True)
                self.area_vars[a] = var
                ttk.Checkbutton(self.area_box, text=a, variable=var, command=self.on_area).grid(
                    row=row, column=col, sticky="w", padx=(0, 14), pady=3)
                col += 1
                if col > 7:
                    row, col = row + 1, 1

    def _render_channels(self):
        for w in self.channel_box.winfo_children():
            w.destroy()
        self.channel_vars = {}
        if not self.loaded:
            tk.Label(self.channel_box, text="예약 Excel 을 먼저 선택하세요.", bg=T.CARD, fg=T.MUTED).pack(anchor="w")
            self.unsupported_var.set("")
            return
        ttk.Checkbutton(self.channel_box, text="ALL", variable=self.channel_all_var,
                        command=self.toggle_all_channels).pack(side="left", padx=(0, 14))
        for ch in SUPPORTED_CHANNELS:
            n = int((self.loaded.df["Agency"] == ch).sum())
            if not n:
                continue
            var = tk.BooleanVar(value=True)
            self.channel_vars[ch] = var
            ttk.Checkbutton(self.channel_box, text=f"{CHANNEL_DISPLAY[ch]} ({n:,})", variable=var,
                            command=self.on_channel).pack(side="left", padx=(0, 14))
        others = self.loaded.df[~self.loaded.df["Agency"].isin(SUPPORTED_CHANNELS)]
        if others.empty:
            self.unsupported_var.set("미지원 에이전시: 없음")
        else:
            parts = [f"{a} {n:,}" for a, n in others.groupby("Agency").size().sort_values(ascending=False).items()]
            self.unsupported_var.set("리뷰 수집 미지원 에이전시 (예약 수에는 포함): " + " · ".join(parts))

    def toggle_all_areas(self):
        for v in self.area_vars.values():
            v.set(self.area_all_var.get())
        self._sync_countries()
        self.update_preview()

    def on_area(self):
        self.area_all_var.set(bool(self.area_vars) and all(v.get() for v in self.area_vars.values()))
        self._sync_countries()
        self.update_preview()

    def on_country(self, g):
        for a, v in self.area_vars.items():
            if area_group(a) == g:
                v.set(self.country_vars[g].get())
        self.area_all_var.set(all(v.get() for v in self.area_vars.values()))
        self.update_preview()

    def _sync_countries(self):
        for g, var in self.country_vars.items():
            members = [v for a, v in self.area_vars.items() if area_group(a) == g]
            var.set(bool(members) and all(m.get() for m in members))

    def toggle_all_channels(self):
        for v in self.channel_vars.values():
            v.set(self.channel_all_var.get())
        self.update_preview()

    def on_channel(self):
        self.channel_all_var.set(bool(self.channel_vars) and all(v.get() for v in self.channel_vars.values()))
        self.update_preview()

    def selected_areas(self):
        return [a for a, v in self.area_vars.items() if v.get()]

    def selected_channels(self):
        return [c for c, v in self.channel_vars.items() if v.get()]

    # ------------------------------------------------------------------
    # 미리보기
    # ------------------------------------------------------------------
    def _scope(self):
        if not self.loaded:
            return None
        s, e = self._dates()
        areas, chans = self.selected_areas(), self.selected_channels()
        if s is None or e is None or s > e or not areas:
            return None
        try:
            return build_scope(self.loaded.df, s, e, areas=areas, channels=chans)
        except Exception:
            return None

    def update_preview(self):
        scope = self._scope()
        tree = self.route_tree
        tree.delete(*tree.get_children())
        if scope is None:
            for v in self.summary_vars.values():
                v.set("-")
            self.period_hint_var.set("")
            self.output_var.set("")
            self.nav_hint = "예약 Excel 선택" if not self.loaded else "조건 확인 필요"
            self.app.refresh_nav()
            return
        self.summary_vars["total"].set(T.nfmt(len(scope.scope_df)))
        self.summary_vars["eligible"].set(T.nfmt(len(scope.eligible_df)))
        self.summary_vars["selected"].set(T.nfmt(len(scope.crawl_df)))
        self.summary_vars["unsupported"].set(T.nfmt(len(scope.unsupported_df)))
        days = (scope.end_date - scope.start_date).days + 1
        self.period_hint_var.set(f"기간 {scope.start_date:%Y-%m-%d} ~ {scope.end_date:%Y-%m-%d} ({days}일) · "
                                 f"지사 {len(scope.selected_areas)}개 · 예약 {len(scope.scope_df):,}건")
        out = default_output_path(self.excel_path, scope.start_date, scope.end_date, scope.selected_areas,
                                  self.output_dir or None)
        groups = split_groups(scope.selected_areas, self.split_var.get(), set(scope.scope_df["Area"].astype(str)))
        if len(groups) > 1:
            names = [g[0] for g in groups]
            n = len(groups) + (1 if self.combined_var.get() else 0)
            self.files_var.set(f"→ Excel {n}개: " + ("통합 + " if self.combined_var.get() else "")
                               + " · ".join(names) + "   (나눈 파일은 아래 폴더 안의 하위 폴더에 저장)")
            self.output_var.set(str(out.parent))
        else:
            if self.split_var.get() != "none":
                self.files_var.set("→ 선택한 지사가 한 그룹뿐이라 Excel 1개로 저장합니다.")
            else:
                self.files_var.set("→ 선택한 지사 전체를 Excel 1개로 저장")
            self.output_var.set(str(out))
        self.nav_hint = f"{scope.start_date:%m/%d}~{scope.end_date:%m/%d} · 예약 {len(scope.crawl_df):,}"
        self.app.refresh_nav()

        m = self.manager
        rows: dict[str | None, dict] = {}
        for (area, ch), g in scope.crawl_df.groupby(["Area", "Agency"]):
            prof = m.route_profile(str(area), str(ch))
            item = rows.setdefault(prof, {"areas": set(), "chs": set(), "n": 0})
            item["areas"].add(str(area))
            item["chs"].add(str(ch))
            item["n"] += len(g)
        for prof, item in sorted(rows.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            chs = [c for c in SUPPORTED_CHANNELS if c in item["chs"]]
            ch_text = ", ".join(CHANNEL_DISPLAY.get(c, c) for c in chs)
            if prof is None:
                tree.insert("", "end", values=("⚠ 미설정", ", ".join(sorted(item["areas"])), ch_text, item["n"],
                                               "-", "OTA 연결표에서 지정 필요"), tags=("bad",))
                continue
            running = m.is_running(prof)
            states = self.app.login_states.get(prof, {})
            need = [CHANNEL_DISPLAY.get(c, c) for c in chs if getattr(states.get(c), "status", None) == LOGIN_REQUIRED]
            okc = [c for c in chs if getattr(states.get(c), "status", None) == OK]
            login = ("로그인 필요: " + ", ".join(need)) if need else ("확인됨" if len(okc) == len(chs) else "미확인")
            tag = "bad" if need else ""
            tree.insert("", "end", values=(f"{prof} · {REGION_LABELS.get(m.profile_region(prof), '')}",
                                           ", ".join(sorted(item["areas"])), ch_text, item["n"],
                                           "● 실행 중" if running else "○ 자동 실행", login), tags=(tag,))

    update_route_preview = update_preview

    def on_show(self):
        self.update_preview()

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------
    def start(self):
        if not self.loaded:
            messagebox.showwarning("확인", "예약 Excel 을 먼저 선택하세요.")
            return
        s, e = self._dates()
        areas, chans = self.selected_areas(), self.selected_channels()
        if s is None or e is None or s > e:
            messagebox.showwarning("확인", "기간(시작일/종료일)을 확인하세요.")
            return
        if not areas:
            messagebox.showwarning("확인", "최소 1개 지사를 선택하세요.")
            return
        if not chans:
            messagebox.showwarning("확인", "최소 1개 OTA 를 선택하세요.")
            return
        scope = build_scope(self.loaded.df, s, e, areas=areas, channels=chans)
        if scope.scope_df.empty:
            messagebox.showwarning("확인", "선택 조건에 해당하는 예약이 없습니다.")
            return
        missing = self.manager.unconfigured_routes(scope.crawl_df, chans)
        if missing:
            text = "\n".join(f"• {x['area']} / {CHANNEL_DISPLAY.get(x['channel'], x['channel'])}" for x in missing[:20])
            if not messagebox.askyesno(
                    "Chrome 계정 미설정",
                    "아래 Area/OTA 는 연결된 Chrome 계정이 없어 수집하지 않습니다 (결과에서 수집 제외로 표시).\n\n"
                    + text + "\n\n이대로 계속할까요?  [아니오] 를 누르면 ① 지역별 Chrome > OTA 연결표 로 이동합니다."):
                self.app.show("chrome")
                self.app.pages["chrome"].nb.select(1)
                return
        need_login = []
        for prof, info in self.manager.required_profiles(scope.crawl_df, chans).items():
            st = self.app.login_states.get(prof, {})
            need_login += [f"{prof} · {CHANNEL_DISPLAY.get(c, c)}" for c in info["channels"]
                           if getattr(st.get(c), "status", None) == LOGIN_REQUIRED]
        if need_login and not messagebox.askyesno(
                "로그인 필요", "마지막 확인에서 로그인이 필요했던 OTA 가 있습니다:\n\n" + "\n".join(need_login)
                + "\n\n로그인을 마쳤다면 [예] 를 눌러 계속합니다."):
            return
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            started, failed = self.manager.ensure_required(scope.crawl_df, chans)
        except Exception as exc:
            messagebox.showerror("Chrome 오류", str(exc))
            return
        finally:
            self.config(cursor="")
        if failed:
            messagebox.showerror("Chrome 연결", "다음 지역 Chrome 을 켤 수 없습니다: " + ", ".join(failed))
            return
        if started and not messagebox.askokcancel(
                "지역 Chrome 자동 실행",
                f"꺼져 있던 지역 Chrome 을 켰습니다: {', '.join(started)}\n\n"
                "처음 쓰는 Chrome 이면 열린 OTA 탭에서 로그인한 뒤 [확인] 을 눌러 수집을 시작하세요."):
            return

        self.form.pack_forget()
        self.progress_view.pack(fill="both", expand=True)
        self.log_text.delete("1.0", "end")
        self.pbar.configure(value=0)
        self.step_var.set("준비 중")
        # Tk 변수는 메인 스레드에서만 읽는다 (작업 스레드에서 읽으면 RuntimeError).
        opts = {"split_by": self.split_var.get(), "include_combined": self.combined_var.get(),
                "output_dir": self.output_dir or None}
        self.worker = threading.Thread(target=self._work, args=(s, e, areas, chans, opts), daemon=True)
        self.worker.start()
        self.after(100, self._poll)

    def _work(self, s, e, areas, chans, opts):
        try:
            res = run_phase1(
                excel_path=self.excel_path, start_date=s, end_date=e, areas=areas, channels=chans,
                log=lambda m: self.log_q.put(("log", str(m))),
                progress=lambda d, t, txt: self.log_q.put(("progress", (d, t, txt))),
                browser_manager=self.manager, auto_launch_browsers=True,
                **opts,
            )
            self.log_q.put(("done", res))
        except Exception:
            self.log_q.put(("error", traceback.format_exc()))

    def _poll(self):
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "log":
                    self.log_text.insert("end", payload + "\n")
                    self.log_text.see("end")
                elif kind == "progress":
                    d, t, txt = payload
                    self.pbar.configure(value=(d / max(t, 1)) * 100)
                    self.step_var.set(f"{txt}   ({d}/{t})")
                elif kind == "done":
                    self._back_to_form()
                    self.app.set_result(payload)
                    return
                elif kind == "error":
                    self._back_to_form()
                    messagebox.showerror("수집 오류", friendly_error(payload))
                    return
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _back_to_form(self):
        self.progress_view.pack_forget()
        self.form.pack(fill="both", expand=True)


def friendly_error(tb: str) -> str:
    low = (tb or "").lower()
    try:
        (APP_DIR / "error.log").write_text(tb or "", encoding="utf-8")
        note = f"\n\n자세한 내용: {APP_DIR / 'error.log'}"
    except Exception:
        note = ""
    if "permissionerror" in low and ".xlsx" in low:
        return "결과 Excel 을 저장할 수 없습니다. 같은 이름의 Excel 이 열려 있으면 닫고 다시 실행하세요." + note
    if "chrome" in low and ("not connected" in low or "debug" in low or "cannot connect" in low):
        return "지역 Chrome 연결에 문제가 있습니다. ① 지역별 Chrome 화면에서 해당 Chrome 을 열고 로그인 상태를 확인하세요." + note
    lines = [x for x in (tb or "").strip().splitlines() if x.strip()]
    return "수집 중 오류가 발생했습니다.\n\n" + "\n".join(lines[-10:]) + note
