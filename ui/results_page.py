"""③ 결과 · 보고서."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from collectors.config import CHANNEL_DISPLAY
from core.periods import MODE_LABEL, period_kind
from core.report_text import build_report_text
from export.gpt_export import save_gpt_workbook
from export.weekly_report import _prepare, incentive_table, load_short_names
from ui import theme as T

STATUS_KR = {
    "SUCCESS": "성공", "PARTIAL": "일부 실패", "FAILED": "실패", "UNCONFIGURED": "계정 미설정",
    "NOT_SELECTED": "선택 안 함", "NOT_RUN": "실행 안 됨",
}


class ResultsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.BG)
        self.app = app
        self.result = None
        self.mode_var = tk.StringVar(value="BAD")
        self.star_var = tk.StringVar(value="ALL")
        self.area_var = tk.StringVar(value="ALL")
        self.search_var = tk.StringVar(value="")
        self.report_area_var = tk.StringVar(value="전체")
        self.selected_tours: set[tuple[str, str]] = set()
        self.sel_count_var = tk.StringVar(value="선택 0개")
        self._item_keys: dict[str, tuple[str, str]] = {}
        self._sort = (None, False)
        self._texts: tuple[str, dict] = ("", {})

    # ------------------------------------------------------------------
    def load(self, result):
        self.result = result
        self.selected_tours.clear()
        self._sort = (None, False)
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        r = self.result
        scope = r.scope
        kind = MODE_LABEL[period_kind(scope.start_date, scope.end_date)]

        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x", padx=26, pady=(18, 2))
        tk.Label(head, text=f"{kind} 리뷰 결과", bg=T.BG, fg=T.TEXT, font=(T.FONT, 18, "bold")).pack(side="left")
        ttk.Button(head, text="GPT 분석용 Excel", command=self.export_gpt).pack(side="right")
        ttk.Button(head, text="폴더 열기", command=lambda: self.app.open_path(Path(r.output_path).parent)).pack(side="right", padx=6)
        ttk.Button(head, text="결과 Excel 열기", style="Accent.TButton",
                   command=lambda: self.app.open_path(r.output_path)).pack(side="right")
        ttk.Button(head, text="← 조건 변경", command=lambda: self.app.show("collect")).pack(side="right", padx=6)
        tk.Label(self, text=f"{scope.start_date:%Y-%m-%d} ~ {scope.end_date:%Y-%m-%d}  ·  지사 {', '.join(scope.selected_areas)}"
                            f"  ·  저장: {r.output_path}",
                 bg=T.BG, fg=T.MUTED, font=(T.FONT, 9), anchor="w", wraplength=1080, justify="left").pack(fill="x", padx=28)
        files = getattr(r, "output_files", None) or []
        if len(files) > 1:
            bar = tk.Frame(self, bg=T.ACCENT_SOFT, padx=12, pady=7, highlightthickness=1, highlightbackground=T.BORDER)
            bar.pack(fill="x", padx=26, pady=(8, 0))
            tk.Label(bar, text=f"결과 Excel {len(files)}개", bg=T.ACCENT_SOFT, fg=T.TEXT,
                     font=(T.FONT, 9, "bold")).pack(side="left", padx=(0, 10))
            for label, path in files:
                ttk.Button(bar, text=f"{label} 열기", style="Small.TButton",
                           command=lambda p=path: self.app.open_path(p)).pack(side="left", padx=2, pady=2)
            split_dir = next((Path(p).parent for lab, p in files if lab != "통합"), None)
            if split_dir is not None:
                ttk.Button(bar, text="나눈 파일 폴더", style="Small.TButton",
                           command=lambda d=split_dir: self.app.open_path(d)).pack(side="right")

        o = r.overall.iloc[0]
        cards = tk.Frame(self, bg=T.BG)
        cards.pack(fill="x", padx=26, pady=(10, 6))
        rating = pd.to_numeric(r.master.loc[r.master["Review Found"].fillna(False).astype(bool), "Rating"], errors="coerce")
        items = [
            ("예약", T.nfmt(o["Total Booking"]), f"수집 대상 {T.nfmt(o['Valid Review Scope'])}", T.TEXT),
            ("리뷰", T.nfmt(o["Reviews"]), f"리뷰율 {T.pct(o['Review Rate'])}", T.TEXT),
            ("GOOD 4~5점", T.nfmt(o["Good"]), T.pct(o["Good Rate"]), T.GOOD),
            ("BAD 1~3점", T.nfmt(o["Bad"]), T.pct(o["Bad Rate"]), T.BAD),
            ("평균 별점", f"{rating.mean():.2f}" if len(rating) else "-", f"5점 {T.nfmt(o['5 Star'])}개", T.TEXT),
            ("수집 오류", T.nfmt(o["Collection Error"]), "예약 기준 (리뷰율 분모 제외)",
             T.BAD if int(o["Collection Error"]) else T.MUTED),
        ]
        for i, (label, value, sub, fg) in enumerate(items):
            box = T.kpi_box(cards, label, value, sub, fg)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0))
            cards.grid_columnconfigure(i, weight=1)
        dist = tk.Frame(self, bg=T.CARD, padx=14, pady=8, highlightthickness=1, highlightbackground=T.BORDER)
        dist.pack(fill="x", padx=26, pady=(0, 8))
        tk.Label(dist, text="별점 분포", bg=T.CARD, fg=T.TEXT, font=(T.FONT, 10, "bold")).pack(side="left", padx=(0, 14))
        tot = max(int(o["Reviews"]), 1)
        for star in (5, 4, 3, 2, 1):
            n = int(o[f"{star} Star"])
            tk.Label(dist, text=f"{'★' * star} {n:,} ({n / tot * 100:.1f}%)", bg=T.CARD,
                     fg=T.BAD if star <= 3 and n else T.TEXT, font=(T.FONT, 9)).pack(side="left", padx=(0, 14))
        failed = [ch for ch, info in r.collection_status.items() if info.get("status") in ("FAILED", "PARTIAL")]
        if failed:
            tk.Label(dist, text="⚠ 수집 실패: " + ", ".join(CHANNEL_DISPLAY.get(c, c) for c in failed) + " → 수집 상태 탭",
                     bg=T.CARD, fg=T.BAD, font=(T.FONT, 9, "bold")).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=26, pady=(0, 18))
        self.nb = nb
        t1, t2, t3, t4 = (tk.Frame(nb, bg=T.CARD) for _ in range(4))
        nb.add(t1, text="투어별 분석")
        nb.add(t2, text="지사 보고 텍스트 (복사)")
        nb.add(t3, text="성과제")
        nb.add(t4, text="수집 상태")
        self._build_tours(t1)
        self._build_report(t2)
        self._build_incentive(t3)
        self._build_status(t4)
        if failed:
            nb.select(3)

    # ------------------------------------------------------------------
    # 투어별 분석
    # ------------------------------------------------------------------
    def _build_tours(self, tab):
        bar = tk.Frame(tab, bg=T.CARD)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        for m in ("BAD", "GOOD", "ALL"):
            ttk.Radiobutton(bar, text=m, value=m, variable=self.mode_var,
                            command=self._mode_changed).pack(side="left", padx=(0, 12))
        tk.Label(bar, text="Area", bg=T.CARD, fg=T.MUTED).pack(side="left", padx=(20, 4))
        areas = ["ALL"] + sorted(self.result.tours["Area"].dropna().astype(str).unique().tolist()) \
            if not self.result.tours.empty else ["ALL"]
        cb = ttk.Combobox(bar, values=areas, textvariable=self.area_var, width=14, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_tours())
        self.area_var.set("ALL")
        tk.Label(bar, text="투어 검색", bg=T.CARD, fg=T.MUTED).pack(side="left", padx=(16, 4))
        ent = ttk.Entry(bar, textvariable=self.search_var, width=22)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self.refresh_tours())
        self.star_bar = tk.Frame(tab, bg=T.CARD)
        self.star_bar.pack(fill="x", padx=10)
        self._render_star_filter()

        sel = tk.Frame(tab, bg=T.CARD)
        sel.pack(fill="x", padx=10, pady=(4, 6))
        tk.Label(sel, text="☐ 를 눌러 GPT 분석용 투어 선택 · 행 더블클릭 = 투어 상세(원본 리뷰 · AI 분석)",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 8)).pack(side="left")
        ttk.Button(sel, text="선택 투어 → GPT Excel", command=self.export_gpt).pack(side="right")
        tk.Label(sel, textvariable=self.sel_count_var, bg=T.CARD, fg=T.MUTED).pack(side="right", padx=8)
        ttk.Button(sel, text="해제", style="Small.TButton", command=self._clear_sel).pack(side="right")
        ttk.Button(sel, text="보이는 투어 전체 선택", style="Small.TButton", command=self._select_visible).pack(side="right", padx=4)

        frame, self.tree = T.make_tree(tab, ("선택",))
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._open_detail)
        self.refresh_tours()

    def _mode_changed(self):
        self.star_var.set("ALL")
        self._sort = (None, False)
        self._render_star_filter()
        self.refresh_tours()

    def _render_star_filter(self):
        for w in self.star_bar.winfo_children():
            w.destroy()
        opts = [("전체", "ALL")]
        if self.mode_var.get() == "BAD":
            opts += [("★★★ 3점", "3"), ("★★ 2점", "2"), ("★ 1점", "1")]
        elif self.mode_var.get() == "GOOD":
            opts += [("★★★★★ 5점", "5"), ("★★★★ 4점", "4")]
        for text, val in opts:
            ttk.Radiobutton(self.star_bar, text=text, value=val, variable=self.star_var,
                            command=self.refresh_tours).pack(side="left", padx=(0, 12))

    def _columns(self):
        star, mode = self.star_var.get(), self.mode_var.get()
        base = ["선택", "Tour", "Area", "Total Booking", "Reviews", "Review Rate"]
        if star != "ALL":
            return base + [f"{star} Star", "Star Rate"]
        if mode == "BAD":
            return base + ["Bad", "3 Star", "2 Star", "1 Star", "Bad Rate", "Unsupported"]
        if mode == "GOOD":
            return base + ["Good", "5 Star", "4 Star", "Good Rate", "Unsupported"]
        return base + ["Good", "Bad", "Good Rate", "Bad Rate", "5 Star", "4 Star", "3 Star", "2 Star", "1 Star"]

    def refresh_tours(self):
        tree = self.tree
        cols = self._columns()
        tree.delete(*tree.get_children())
        tree["columns"] = cols
        for c in cols:
            w = 56 if c == "선택" else 260 if c == "Tour" else 110 if c == "Area" else 92
            tree.column(c, width=w, minwidth=50, anchor="w" if c in ("Tour", "Area") else "center")
        df = self.result.tours.copy()
        if df.empty:
            self._update_headers(cols)
            return
        if self.area_var.get() not in ("", "ALL"):
            df = df[df["Area"].astype(str) == self.area_var.get()]
        q = self.search_var.get().strip().lower()
        if q:
            df = df[df["Tour"].astype(str).str.lower().str.contains(q, na=False, regex=False)]
        star, mode = self.star_var.get(), self.mode_var.get()
        if star != "ALL":
            sc = f"{star} Star"
            df["Star Rate"] = [(a / b) if b else 0 for a, b in zip(df[sc], df["Reviews"])]
            default = (sc, True)
        else:
            default = {"BAD": ("Bad Rate", True), "GOOD": ("Good Rate", True)}.get(mode, ("Reviews", True))
        col, desc = self._sort if self._sort[0] in cols else default
        self._sort = (col, desc)
        keys = [col] + (["Reviews"] if col != "Reviews" else [])
        df = df.sort_values(keys, ascending=[not desc] + [False] * (len(keys) - 1))
        self._item_keys = {}
        rate_cols = {"Review Rate", "Good Rate", "Bad Rate", "Star Rate"}
        for idx, row in df.iterrows():
            key = (str(row["Area"]), str(row["Tour"]))
            vals = []
            for c in cols:
                if c == "선택":
                    vals.append("☑" if key in self.selected_tours else "☐")
                elif c in rate_cols:
                    vals.append(T.pct(row[c]))
                elif c in ("Tour", "Area"):
                    vals.append(str(row[c]))
                else:
                    vals.append(T.nfmt(row[c]))
            iid = str(idx)
            self._item_keys[iid] = key
            tree.insert("", "end", iid=iid, values=vals)
        self._update_headers(cols)
        self.sel_count_var.set(f"선택 {len(self.selected_tours):,}개")

    def _update_headers(self, cols):
        col, desc = self._sort
        for c in cols:
            text = c + ((" ▼" if desc else " ▲") if c == col else "")
            self.tree.heading(c, text=text, command=(lambda c=c: self._sort_by(c)) if c != "선택" else "")

    def _sort_by(self, c):
        col, desc = self._sort
        self._sort = (c, not desc if col == c else True)
        self.refresh_tours()

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        key = self._item_keys.get(iid)
        if not key:
            return "break"
        self.selected_tours.symmetric_difference_update({key})
        self.tree.set(iid, "선택", "☑" if key in self.selected_tours else "☐")
        self.sel_count_var.set(f"선택 {len(self.selected_tours):,}개")
        return "break"

    def _select_visible(self):
        for iid in self.tree.get_children():
            key = self._item_keys.get(iid)
            if key:
                self.selected_tours.add(key)
                self.tree.set(iid, "선택", "☑")
        self.sel_count_var.set(f"선택 {len(self.selected_tours):,}개")

    def _clear_sel(self):
        self.selected_tours.clear()
        self.refresh_tours()

    def _open_detail(self, event=None):
        if event is not None and self.tree.identify_column(event.x) == "#1":
            return
        sel = self.tree.selection()
        if not sel or sel[0] not in self._item_keys:
            return
        area, tour = self._item_keys[sel[0]]
        from ui.tour_detail import open_tour_detail
        open_tour_detail(self.app, area, tour)

    def export_gpt(self):
        if not self.selected_tours:
            if not self.result.tours.empty and messagebox.askyesno(
                    "GPT 분석용 Excel", "선택한 투어가 없습니다. 현재 결과의 모든 투어로 만들까요?"):
                self.selected_tours = set(zip(self.result.tours["Area"].astype(str),
                                              self.result.tours["Tour"].astype(str)))
            else:
                return
        path = filedialog.asksaveasfilename(
            title="GPT 분석용 Excel 저장", defaultextension=".xlsx",
            initialdir=str(Path(self.result.output_path).parent),
            initialfile=f"GPT_Review_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            filetypes=[("Excel files", "*.xlsx")])
        if not path:
            return
        try:
            n = save_gpt_workbook(path, self.result, self.selected_tours, self.app.manager)
        except PermissionError:
            messagebox.showerror("저장 오류", "같은 이름의 Excel 이 열려 있습니다. 닫거나 다른 이름으로 저장하세요.")
            return
        except Exception as exc:
            messagebox.showerror("저장 오류", str(exc))
            return
        self.refresh_tours()
        messagebox.showinfo("저장 완료", f"투어 {n['tours']}개 · 예약 {n['bookings']:,}건 · 리뷰 {n['reviews']:,}개\n\n{path}\n\n"
                                       "ChatGPT 에 이 파일을 올리고 '분석해줘' 라고만 입력하면 됩니다.")

    # ------------------------------------------------------------------
    # 지사 보고 텍스트
    # ------------------------------------------------------------------
    def _build_report(self, tab):
        s = self.result.scope
        self._texts = build_report_text(self.result.master, s.start_date, s.end_date, s.selected_areas)
        bar = tk.Frame(tab, bg=T.CARD)
        bar.pack(fill="x", padx=10, pady=10)
        tk.Label(bar, text="보기", bg=T.CARD, fg=T.MUTED).pack(side="left")
        values = ["전체"] + list(self._texts[1])
        cb = ttk.Combobox(bar, values=values, textvariable=self.report_area_var, state="readonly", width=18)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._show_report())
        self.report_area_var.set("전체")
        ttk.Button(bar, text="📋 이 내용 복사", style="Accent.TButton", command=self._copy_report).pack(side="left", padx=8)
        for a in self._texts[1]:
            ttk.Button(bar, text=f"{a} 복사", style="Small.TButton",
                       command=lambda a=a: self._copy(self._texts[1][a], a)).pack(side="left", padx=2)
        box = tk.Frame(tab, bg=T.CARD)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.report_text = tk.Text(box, font=("Malgun Gothic", 9), wrap="none", relief="flat", bg=T.CARD_ALT)
        ys = ttk.Scrollbar(box, orient="vertical", command=self.report_text.yview)
        xs = ttk.Scrollbar(box, orient="horizontal", command=self.report_text.xview)
        self.report_text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.report_text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        self._show_report()

    def _current_report(self) -> str:
        a = self.report_area_var.get()
        return self._texts[0] if a == "전체" else self._texts[1].get(a, "")

    def _show_report(self):
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", self._current_report())
        self.report_text.configure(state="disabled")

    def _copy_report(self):
        self._copy(self._current_report(), self.report_area_var.get())

    def _copy(self, text, label):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.app.pages["chrome"].status_var.set(f"[{label}] 보고 텍스트를 복사했습니다.")
        messagebox.showinfo("복사됨", f"[{label}] 보고 텍스트를 클립보드에 복사했습니다.")

    # ------------------------------------------------------------------
    # 성과제 · 수집 상태
    # ------------------------------------------------------------------
    def _build_incentive(self, tab):
        s = self.result.scope
        multi = len(s.selected_areas) > 1
        df = _prepare(self.result.master)
        table, unassigned = incentive_table(df, multi)
        short = load_short_names()
        tk.Label(tab, text="한 줄 = 가이드 + 투어 + 투어 날짜 · 실제 지급 = 5점 − 3점 이하 · "
                           "리뷰율 = 리뷰 ÷ 리뷰 수집 대상 팀  (결과 Excel '성과제' 시트와 같은 내용)",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", padx=12, pady=(10, 6))
        cols = ["순위"] + (["Area"] if multi else []) + ["가이드", "투어명", "투어 날짜", "팀", "인원",
                                                         "5점", "3점 이하", "실제 지급", "리뷰율"]
        frame, tree = T.make_tree(tab, cols, {"가이드": 160, "투어명": 280, "Area": 110, "투어 날짜": 130})
        frame.pack(fill="both", expand=True, padx=10)
        tree.tag_configure("total", font=(T.FONT, 9, "bold"), background="#F2F2F2")

        def ppl(v):
            return f"{int(v):,}명" if v is not None and pd.notna(v) else "-"

        def rate(v):
            return T.pct(v) if v is not None and pd.notna(v) else "-"

        for _, r in table.iterrows():
            d = pd.Timestamp(r["Date"])
            vals = [int(r["rank"])] + ([r["__area"]] if multi else []) + [
                r["__guide"], short.get(r["__tour"], r["__tour"]),
                f"{d:%Y-%m-%d} ({'월화수목금토일'[d.weekday()]})", f"{int(r['teams'])}팀", ppl(r["people"]),
                int(r["five"]), -int(r["low"]) if r["low"] else 0, int(r["pay"]), rate(r["rate"])]
            tree.insert("", "end", values=vals)
        if not table.empty:
            elig = int(table["eligible"].sum())
            people = pd.to_numeric(table["people"], errors="coerce")
            tree.insert("", "end", tags=("total",), values=["합계"] + ([""] if multi else []) + [
                "", "", "", f"{int(table['teams'].sum())}팀", ppl(people.sum() if people.notna().any() else None),
                int(table["five"].sum()), -int(table["low"].sum()), int(table["pay"].sum()),
                rate(table["reviews"].sum() / elig if elig else None)])
        note = f"가이드 미지정 5점 리뷰 {unassigned}개는 제외됨" if unassigned else ""
        if table.empty:
            note = "선택 기간에 5점 리뷰를 받은 가이드가 없습니다. " + note
        tk.Label(tab, text=note, bg=T.CARD, fg=T.WARN, font=(T.FONT, 9)).pack(anchor="w", padx=12, pady=8)

    def _build_status(self, tab):
        tk.Label(tab, text="OTA × 지역 Chrome 별 수집 결과. 실패한 예약은 리뷰율 분모에서 빠지며 '리뷰 없음' 으로 보지 않습니다.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", padx=12, pady=(10, 6))
        cols = ("OTA", "Chrome 계정", "Area", "상태", "수집 리뷰", "예약과 매칭", "오류")
        frame, tree = T.make_tree(tab, cols, {"Area": 220, "오류": 420, "Chrome 계정": 110})
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree.tag_configure("bad", foreground=T.BAD)
        for ch, info in self.result.collection_status.items():
            profiles = info.get("profiles") or {"-": info}
            for prof, p in profiles.items():
                st = p.get("status", "")
                tree.insert("", "end", tags=("bad",) if st not in ("SUCCESS", "NOT_SELECTED") else (), values=(
                    CHANNEL_DISPLAY.get(ch, ch), prof, ", ".join(p.get("areas") or []),
                    STATUS_KR.get(st, st), p.get("count", 0), info.get("matched", ""), p.get("error", "")))
