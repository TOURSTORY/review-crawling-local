"""투어 상세 창 (채널별 · 별점 분포 · 원본 리뷰 · AI 리뷰 분석). v1.3 화면을 그대로 옮겼다."""
from __future__ import annotations

import threading
import traceback
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import pandas as pd

from analysis.review_ai import analyze_reviews
from collectors.config import CHANNEL_DISPLAY
from core.metrics import build_channel_metrics
from ui.collect_page import friendly_error
from ui.theme import (ACCENT_DARK, ACCENT_SOFT, BAD, BG, BORDER, FONT, GOOD, MUTED, TEXT,
                      CARD as CARD_BG, nfmt, pct)


def open_tour_detail(app, area: str, tour: str):
    _Detail(app).show_tour_detail(area, tour)


class _Detail:
    def __init__(self, app):
        self.app = app

    @property
    def result(self):
        return self.app.result

    @property
    def root(self):
        return self.app.root

    @property
    def openai_api_key(self):
        return self.app.openai_api_key or ""

    @openai_api_key.setter
    def openai_api_key(self, value):
        self.app.openai_api_key = value

    def show_tour_detail(self, area: str, tour: str):
        master = self.result.master
        sub = master[(master["Area"].astype(str) == str(area)) &
                     (master["Product Normalized"].astype(str) == str(tour))].copy()
        if sub.empty:
            return
        metric = self.result.tours[(self.result.tours["Area"].astype(str) == str(area)) &
                                   (self.result.tours["Tour"].astype(str) == str(tour))].iloc[0]

        win = tk.Toplevel(self.root)
        win.title(f"{tour} - Tour Detail")
        win.geometry("1120x760")
        win.configure(bg=BG)

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(top, text=tour, bg=BG, fg=TEXT, font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(top, text=f"{area} · {self.result.scope.start_date.strftime('%Y-%m-%d')} ~ {self.result.scope.end_date.strftime('%Y-%m-%d')}",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        cards = tk.Frame(win, bg=BG)
        cards.pack(fill="x", padx=22, pady=(4, 10))
        items = [
            ("TOTAL", metric["Total Booking"], ""),
            ("ELIGIBLE", metric["Eligible"], ""),
            ("REVIEWS", metric["Reviews"], pct(metric["Review Rate"])),
            ("GOOD", metric["Good"], pct(metric["Good Rate"])),
            ("BAD", metric["Bad"], pct(metric["Bad Rate"])),
        ]
        for i, (label, value, subtext) in enumerate(items):
            c = tk.Frame(cards, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER, padx=12, pady=9)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 4 if i < 4 else 0))
            cards.grid_columnconfigure(i, weight=1)
            tk.Label(c, text=label, bg=CARD_BG, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
            tk.Label(c, text=nfmt(value), bg=CARD_BG, fg=BAD if label == "BAD" else GOOD if label == "GOOD" else TEXT,
                     font=(FONT, 16, "bold")).pack(anchor="w")
            tk.Label(c, text=subtext, bg=CARD_BG, fg=MUTED, font=(FONT, 8)).pack(anchor="w")

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        # Channel tab
        ch_tab = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(ch_tab, text="채널별")
        ch_metrics = build_channel_metrics(sub)
        ccols = ["Agency", "Total Booking", "Reviews", "Review Rate", "Good", "Bad", "Bad Rate"]
        ctree = ttk.Treeview(ch_tab, columns=ccols, show="headings")
        for c in ccols:
            ctree.heading(c, text=c)
            ctree.column(c, width=130 if c != "Agency" else 160, anchor="center")
        ctree.pack(fill="both", expand=True, padx=10, pady=10)
        for _, r in ch_metrics.iterrows():
            name = CHANNEL_DISPLAY.get(str(r["Agency"]), str(r["Agency"]))
            ctree.insert("", "end", values=[name, nfmt(r["Total Booking"]), nfmt(r["Reviews"]), pct(r["Review Rate"]),
                                              nfmt(r["Good"]), nfmt(r["Bad"]), pct(r["Bad Rate"])])

        # Ratings tab
        rating_tab = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(rating_tab, text="별점 분포")
        total_reviews = max(int(metric["Reviews"]), 1)
        for star in [5, 4, 3, 2, 1]:
            count = int(metric[f"{star} Star"])
            rowf = tk.Frame(rating_tab, bg=CARD_BG)
            rowf.pack(fill="x", padx=24, pady=8)
            tk.Label(rowf, text="★" * star, width=10, anchor="w", bg=CARD_BG, fg=TEXT,
                     font=(FONT, 11)).pack(side="left")
            tk.Label(rowf, text=f"{count:,} reviews", width=15, anchor="w", bg=CARD_BG, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(side="left")
            tk.Label(rowf, text=f"{count / total_reviews * 100:.1f}%", bg=CARD_BG, fg=MUTED,
                     font=(FONT, 10)).pack(side="left")

        # Reviews tab
        rev_tab = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(rev_tab, text=f"원본 리뷰 ({int(metric['Reviews']):,})")
        filter_row = tk.Frame(rev_tab, bg=CARD_BG)
        filter_row.pack(fill="x", padx=10, pady=(10, 5))
        rev_filter = tk.StringVar(value="ALL")
        rev_search = tk.StringVar(value="")
        for text, val in [("ALL", "ALL"), ("BAD", "BAD"), ("GOOD", "GOOD"), ("3★", "3"), ("2★", "2"), ("1★", "1"), ("5★", "5"), ("4★", "4")]:
            ttk.Radiobutton(filter_row, text=text, value=val, variable=rev_filter).pack(side="left", padx=(0, 9))
        tk.Label(filter_row, text="검색", bg=CARD_BG, fg=MUTED).pack(side="left", padx=(16, 5))
        ttk.Entry(filter_row, textvariable=rev_search, width=24).pack(side="left")

        rcols = ["Rating", "Group", "Agency", "Tour Date", "Review Date", "Guide", "Review Preview"]
        rframe = tk.Frame(rev_tab, bg=CARD_BG)
        rframe.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        rtree = ttk.Treeview(rframe, columns=rcols, show="headings")
        ry = ttk.Scrollbar(rframe, orient="vertical", command=rtree.yview)
        rx = ttk.Scrollbar(rframe, orient="horizontal", command=rtree.xview)
        rtree.configure(yscrollcommand=ry.set, xscrollcommand=rx.set)
        rtree.grid(row=0, column=0, sticky="nsew")
        ry.grid(row=0, column=1, sticky="ns")
        rx.grid(row=1, column=0, sticky="ew")
        rframe.grid_rowconfigure(0, weight=1)
        rframe.grid_columnconfigure(0, weight=1)
        for c in rcols:
            rtree.heading(c, text=c)
            rtree.column(c, width=110 if c != "Review Preview" else 420, anchor="w")

        rev_df = sub[sub["Review Found"].eq(True)].copy().reset_index(drop=True)

        def fill_reviews(*_):
            rtree.delete(*rtree.get_children())
            d = rev_df.copy()
            f = rev_filter.get()
            if f == "BAD":
                d = d[d["Review Group"] == "BAD"]
            elif f == "GOOD":
                d = d[d["Review Group"] == "GOOD"]
            elif f.isdigit():
                d = d[pd.to_numeric(d["Rating"], errors="coerce") == int(f)]
            q = rev_search.get().strip().lower()
            if q:
                d = d[d["Review Text"].astype(str).str.lower().str.contains(q, na=False)]
            d = d.sort_values(["Rating", "Date"], ascending=[True, False])
            for idx, r in d.iterrows():
                preview = str(r.get("Review Text", "") or "").replace("\n", " ")[:180]
                guide = str(r.get("Main Guide", "") or "")
                agency = CHANNEL_DISPLAY.get(str(r["Agency"]), str(r["Agency"]))
                date_str = pd.Timestamp(r["Date"]).strftime("%Y-%m-%d") if pd.notna(r["Date"]) else ""
                rtree.insert("", "end", iid=str(idx), values=[int(float(r["Rating"])), r["Review Group"], agency,
                                                                  date_str, r.get("Review Date", ""), guide, preview])

        def open_review(_event=None):
            sel = rtree.selection()
            if not sel:
                return
            idx = int(sel[0])
            r = rev_df.loc[idx]
            pop = tk.Toplevel(win)
            pop.title("Original Review")
            pop.geometry("760x500")
            pop.configure(bg=BG)
            hdr = f"{int(float(r['Rating']))}★ · {CHANNEL_DISPLAY.get(str(r['Agency']), str(r['Agency']))} · {r['Review Group']}"
            tk.Label(pop, text=hdr, bg=BG, fg=TEXT, font=(FONT, 13, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
            tk.Label(pop, text=f"Tour Date: {pd.Timestamp(r['Date']).strftime('%Y-%m-%d')}  ·  Review Date: {r.get('Review Date','')}  ·  Booking: {r.get('Agency Code','')}",
                     bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=18, pady=(0, 10))
            txt = tk.Text(pop, wrap="word", font=(FONT, 11), padx=12, pady=12)
            txt.pack(fill="both", expand=True, padx=18, pady=(0, 18))
            txt.insert("1.0", str(r.get("Review Text", "") or ""))
            txt.configure(state="disabled")

        rev_filter.trace_add("write", fill_reviews)
        rev_search.trace_add("write", fill_reviews)
        rtree.bind("<Double-1>", open_review)
        fill_reviews()

        # AI analysis tab (selected tour only)
        self._build_ai_analysis_tab(notebook, win, sub, area, tour)

    # ------------------------------------------------------------------
    # AI review analysis
    # ------------------------------------------------------------------
    def _ensure_openai_key(self, parent=None) -> str:
        if self.openai_api_key.strip():
            return self.openai_api_key.strip()
        key = simpledialog.askstring(
            "OpenAI API Key",
            "OpenAI API Key를 입력하세요.\n\n키는 파일에 저장하지 않고 이번 실행 중에만 사용합니다.",
            parent=parent or self.root,
            show="*",
        )
        if key and key.strip():
            self.openai_api_key = key.strip()
        return self.openai_api_key.strip()

    def _build_ai_analysis_tab(self, notebook, parent_win, sub: pd.DataFrame, area: str, tour: str):
        ai_tab = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(ai_tab, text="AI 리뷰 분석")

        top = tk.Frame(ai_tab, bg=CARD_BG)
        top.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(
            top,
            text="의미 기반 리뷰 분석",
            bg=CARD_BG,
            fg=TEXT,
            font=(FONT, 12, "bold"),
        ).pack(side="left")
        tk.Label(
            top,
            text="  ·  BAD: Category → Issue → 원본 리뷰   |   GOOD: Category → Positive → 원본 리뷰",
            bg=CARD_BG,
            fg=MUTED,
            font=(FONT, 9),
        ).pack(side="left")

        key_status = tk.StringVar(
            value="API Key 설정됨" if self.openai_api_key.strip() else "API Key 미설정"
        )
        status_var = tk.StringVar(value="AI 분석을 실행하면 이 투어의 리뷰만 분석합니다.")

        actions = tk.Frame(ai_tab, bg=CARD_BG)
        actions.pack(fill="x", padx=12, pady=(0, 8))

        def set_key():
            # Explicitly allow replacing a session key.
            key = simpledialog.askstring(
                "OpenAI API Key",
                "OpenAI API Key를 입력하세요.\n\n키는 파일에 저장하지 않고 이번 실행 중에만 사용합니다.",
                parent=parent_win,
                show="*",
            )
            if key and key.strip():
                self.openai_api_key = key.strip()
                key_status.set("API Key 설정됨")

        ttk.Button(actions, text="API Key 설정", command=set_key).pack(side="left")
        tk.Label(actions, textvariable=key_status, bg=CARD_BG, fg=MUTED, font=(FONT, 9)).pack(
            side="left", padx=(8, 18)
        )

        run_btn = ttk.Button(actions, text="AI 분석 실행", style="Accent.TButton")
        run_btn.pack(side="left")

        ai_progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        ai_progress.pack(side="left", padx=(14, 8))
        tk.Label(actions, textvariable=status_var, bg=CARD_BG, fg=MUTED, font=(FONT, 9)).pack(
            side="left", fill="x", expand=True
        )

        note = tk.Label(
            ai_tab,
            text="※ 한 리뷰에 여러 이슈/강점이 있을 수 있어 비율 합계가 100%를 넘을 수 있습니다. 4점 리뷰의 명시적 아쉬움은 별도 ‘4점 개선’ 탭에 표시됩니다.",
            bg=ACCENT_SOFT,
            fg=TEXT,
            font=(FONT, 8),
            anchor="w",
            padx=10,
            pady=7,
        )
        note.pack(fill="x", padx=12, pady=(0, 8))

        inner_nb = ttk.Notebook(ai_tab)
        inner_nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        state = {"result": None}

        def make_analysis_panel(title: str, kind: str, star_options):
            panel = tk.Frame(inner_nb, bg=CARD_BG)
            inner_nb.add(panel, text=title)

            filter_row = tk.Frame(panel, bg=CARD_BG)
            filter_row.pack(fill="x", padx=8, pady=(8, 5))
            star_var = tk.StringVar(value="ALL")
            for label, val in star_options:
                ttk.Radiobutton(
                    filter_row,
                    text=label,
                    value=val,
                    variable=star_var,
                ).pack(side="left", padx=(0, 10))

            paned = ttk.Panedwindow(panel, orient="vertical")
            paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

            summary_box = tk.Frame(paned, bg=CARD_BG)
            review_box = tk.Frame(paned, bg=CARD_BG)
            paned.add(summary_box, weight=2)
            paned.add(review_box, weight=3)

            sum_cols = ["Reviews", "Rate"]
            stree = ttk.Treeview(summary_box, columns=sum_cols, show="tree headings")
            sy = ttk.Scrollbar(summary_box, orient="vertical", command=stree.yview)
            stree.configure(yscrollcommand=sy.set)
            stree.heading("#0", text="Category / Theme")
            stree.column("#0", width=430, anchor="w")
            stree.heading("Reviews", text="Reviews")
            stree.column("Reviews", width=100, anchor="center")
            stree.heading("Rate", text="Rate")
            stree.column("Rate", width=100, anchor="center")
            stree.pack(side="left", fill="both", expand=True)
            sy.pack(side="right", fill="y")

            rcols = ["Rating", "Agency", "Tour Date", "Review Date", "AI Summary", "Review Preview"]
            rtree2 = ttk.Treeview(review_box, columns=rcols, show="headings")
            ry2 = ttk.Scrollbar(review_box, orient="vertical", command=rtree2.yview)
            rx2 = ttk.Scrollbar(review_box, orient="horizontal", command=rtree2.xview)
            rtree2.configure(yscrollcommand=ry2.set, xscrollcommand=rx2.set)
            rtree2.grid(row=0, column=0, sticky="nsew")
            ry2.grid(row=0, column=1, sticky="ns")
            rx2.grid(row=1, column=0, sticky="ew")
            review_box.grid_rowconfigure(0, weight=1)
            review_box.grid_columnconfigure(0, weight=1)
            for c in rcols:
                rtree2.heading(c, text=c)
                if c == "Review Preview":
                    width = 420
                elif c == "AI Summary":
                    width = 300
                else:
                    width = 105
                rtree2.column(c, width=width, anchor="w")

            selected = {"category": None, "theme": None, "row_map": {}}

            def current_detail():
                result = state.get("result")
                if result is None or result.detail is None or result.detail.empty:
                    return pd.DataFrame()
                d = result.detail[result.detail["Kind"] == kind].copy()
                val = star_var.get()
                if val != "ALL":
                    d = d[pd.to_numeric(d["Rating"], errors="coerce") == int(val)]
                return d

            def refresh_reviews():
                rtree2.delete(*rtree2.get_children())
                selected["row_map"] = {}
                d = current_detail()
                if d.empty:
                    return
                category = selected.get("category")
                theme = selected.get("theme")
                if category:
                    d = d[d["Category"] == category]
                if theme:
                    d = d[d["Theme"] == theme]
                # One display row per review even if it has multiple matching themes.
                d = d.drop_duplicates("Review Key").sort_values(["Rating", "Tour Date"], ascending=[True, False])
                for pos, (_, r) in enumerate(d.iterrows()):
                    iid = f"r{pos}"
                    selected["row_map"][iid] = r.to_dict()
                    agency = CHANNEL_DISPLAY.get(str(r.get("Agency", "")), str(r.get("Agency", "")))
                    preview = str(r.get("Review Text", "") or "").replace("\n", " ")[:180]
                    rtree2.insert(
                        "",
                        "end",
                        iid=iid,
                        values=[
                            int(float(r.get("Rating", 0))),
                            agency,
                            r.get("Tour Date", ""),
                            r.get("Review Date", ""),
                            str(r.get("Summary KO", "") or "")[:180],
                            preview,
                        ],
                    )

            def refresh_summary(*_):
                stree.delete(*stree.get_children())
                selected["category"] = None
                selected["theme"] = None
                d = current_detail()
                if d.empty:
                    refresh_reviews()
                    return
                unique_reviews = int(d["Review Key"].nunique())
                for category in sorted(d["Category"].dropna().astype(str).unique().tolist()):
                    cd = d[d["Category"] == category]
                    ccount = int(cd["Review Key"].nunique())
                    parent_id = "cat::" + category
                    stree.insert(
                        "",
                        "end",
                        iid=parent_id,
                        text=category,
                        values=[ccount, f"{ccount / max(unique_reviews, 1) * 100:.1f}%"],
                        open=True,
                    )
                    themes = (
                        cd.groupby("Theme")["Review Key"]
                        .nunique()
                        .sort_values(ascending=False)
                    )
                    for ti, (theme, count) in enumerate(themes.items()):
                        stree.insert(
                            parent_id,
                            "end",
                            iid=f"theme::{category}::{ti}",
                            text=str(theme),
                            values=[int(count), f"{int(count) / max(unique_reviews, 1) * 100:.1f}%"],
                        )
                refresh_reviews()

            def on_summary_select(_event=None):
                sel = stree.selection()
                if not sel:
                    return
                iid = sel[0]
                item = stree.item(iid)
                if iid.startswith("cat::"):
                    selected["category"] = iid.split("::", 1)[1]
                    selected["theme"] = None
                elif iid.startswith("theme::"):
                    parent = stree.parent(iid)
                    selected["category"] = parent.split("::", 1)[1] if parent.startswith("cat::") else None
                    selected["theme"] = str(item.get("text", ""))
                refresh_reviews()

            def open_ai_review(_event=None):
                sel = rtree2.selection()
                if not sel:
                    return
                r = selected["row_map"].get(sel[0])
                if not r:
                    return
                pop = tk.Toplevel(parent_win)
                pop.title("AI Review Detail")
                pop.geometry("820x620")
                pop.configure(bg=BG)
                hdr = tk.Frame(pop, bg=BG)
                hdr.pack(fill="x", padx=18, pady=(16, 8))
                tk.Label(
                    hdr,
                    text=f"{int(float(r.get('Rating', 0)))}★ · {CHANNEL_DISPLAY.get(str(r.get('Agency', '')), str(r.get('Agency', '')))}",
                    bg=BG,
                    fg=TEXT,
                    font=(FONT, 13, "bold"),
                ).pack(anchor="w")
                tk.Label(
                    hdr,
                    text=f"Tour Date: {r.get('Tour Date', '')}  ·  Review Date: {r.get('Review Date', '')}  ·  Booking: {r.get('Agency Code', '')}",
                    bg=BG,
                    fg=MUTED,
                    font=(FONT, 9),
                ).pack(anchor="w", pady=(2, 0))

                analysis_box = tk.Frame(pop, bg=ACCENT_SOFT, padx=12, pady=10)
                analysis_box.pack(fill="x", padx=18, pady=(0, 10))
                tk.Label(analysis_box, text="AI 요약", bg=ACCENT_SOFT, fg=TEXT, font=(FONT, 10, "bold")).pack(anchor="w")
                tk.Label(
                    analysis_box,
                    text=str(r.get("Summary KO", "") or ""),
                    bg=ACCENT_SOFT,
                    fg=TEXT,
                    font=(FONT, 10),
                    justify="left",
                    wraplength=750,
                ).pack(anchor="w", pady=(4, 0))
                tk.Label(
                    analysis_box,
                    text=f"{r.get('Category', '')}  >  {r.get('Theme', '')}",
                    bg=ACCENT_SOFT,
                    fg=ACCENT_DARK,
                    font=(FONT, 10, "bold"),
                ).pack(anchor="w", pady=(6, 0))

                tk.Label(pop, text="Original Review", bg=BG, fg=TEXT, font=(FONT, 10, "bold")).pack(anchor="w", padx=18)
                txt = tk.Text(pop, wrap="word", font=(FONT, 11), padx=12, pady=12)
                txt.pack(fill="both", expand=True, padx=18, pady=(5, 18))
                txt.insert("1.0", str(r.get("Review Text", "") or ""))
                txt.configure(state="disabled")

            star_var.trace_add("write", refresh_summary)
            stree.bind("<<TreeviewSelect>>", on_summary_select)
            rtree2.bind("<Double-1>", open_ai_review)

            return {"refresh": refresh_summary}

        panels = {
            "bad": make_analysis_panel(
                "BAD 이슈",
                "ISSUE",
                [("전체", "ALL"), ("3★", "3"), ("2★", "2"), ("1★", "1")],
            ),
            "good": make_analysis_panel(
                "GOOD 강점",
                "POSITIVE",
                [("전체", "ALL"), ("5★", "5"), ("4★", "4")],
            ),
            "improvement": make_analysis_panel(
                "4점 개선",
                "IMPROVEMENT",
                [("4★", "4")],
            ),
        }

        def refresh_all_panels():
            for p in panels.values():
                p["refresh"]()

        def worker(api_key: str):
            try:
                reviews = sub[sub["Review Found"].eq(True)].copy()
                result = analyze_reviews(
                    reviews,
                    api_key=api_key,
                    progress=lambda m: parent_win.after(0, lambda msg=str(m): status_var.set(msg)),
                )
                state["result"] = result
                parent_win.after(0, on_done)
            except Exception:
                err = traceback.format_exc()
                parent_win.after(0, lambda: on_error(err))

        def on_done():
            ai_progress.stop()
            run_btn.configure(state="normal")
            result = state.get("result")
            if result is not None:
                status_var.set(
                    f"완료 · AI {result.api_count:,}개 / 캐시 {result.cached_count:,}개 · model {result.model}"
                )
            else:
                status_var.set("AI 분석 완료")
            refresh_all_panels()

        def on_error(err: str):
            ai_progress.stop()
            run_btn.configure(state="normal")
            status_var.set("AI 분석 실패")
            messagebox.showerror("AI 분석 오류", friendly_error(err), parent=parent_win)

        def run_ai():
            api_key = self._ensure_openai_key(parent_win)
            if not api_key:
                key_status.set("API Key 미설정")
                return
            key_status.set("API Key 설정됨")
            review_count = int(sub["Review Found"].eq(True).sum())
            if review_count <= 0:
                messagebox.showinfo("AI 분석", "분석할 원본 리뷰가 없습니다.", parent=parent_win)
                return
            run_btn.configure(state="disabled")
            ai_progress.start(12)
            status_var.set(f"AI 분석 준비 중 · {review_count:,} reviews")
            threading.Thread(target=worker, args=(api_key,), daemon=True).start()

        run_btn.configure(command=run_ai)
