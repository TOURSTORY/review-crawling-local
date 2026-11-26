"""메인 창: 왼쪽 단계 메뉴(① 지역별 Chrome → ② 리뷰 수집 → ③ 결과) + 오른쪽 화면."""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from core.browser_profiles import BrowserProfileManager
from ui import theme as T

APP_TITLE = "TOURSTORY Review Crawler"
VERSION = "v2.0"
APP_DIR = Path(__file__).resolve().parents[1]


class App:
    def __init__(self, manager: BrowserProfileManager | None = None):
        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {VERSION}")
        self.root.geometry("1360x880")
        self.root.minsize(1120, 720)
        self.root.configure(bg=T.BG)
        T.configure_styles(self.root)

        self.manager = manager or BrowserProfileManager()
        self.login_states: dict[str, dict[str, object]] = {}   # profile → {channel: LoginState}
        self.result = None                                     # PipelineResult
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        self._nav_buttons: dict[str, tk.Label] = {}
        self._nav_badges: dict[str, tk.StringVar] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.current = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        side = tk.Frame(self.root, bg=T.SIDEBAR, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="TOURSTORY", bg=T.SIDEBAR, fg="#FDB515",
                 font=(T.FONT, 17, "bold")).pack(anchor="w", padx=20, pady=(22, 0))
        tk.Label(side, text=f"Review Crawler {VERSION}", bg=T.SIDEBAR, fg="#FFFFFF",
                 font=(T.FONT, 11, "bold")).pack(anchor="w", padx=20)
        tk.Label(side, text="지역별 Chrome · 주간/월간 리뷰 수집", bg=T.SIDEBAR, fg=T.SIDEBAR_TEXT,
                 font=(T.FONT, 8)).pack(anchor="w", padx=20, pady=(2, 22))

        for key, label in (("chrome", "①  지역별 Chrome 연결"),
                           ("collect", "②  리뷰 수집"),
                           ("results", "③  결과 · 보고서")):
            self._nav_badges[key] = tk.StringVar(value="")
            btn = tk.Frame(side, bg=T.SIDEBAR, cursor="hand2")
            btn.pack(fill="x")
            lab = tk.Label(btn, text=label, bg=T.SIDEBAR, fg=T.SIDEBAR_TEXT, anchor="w",
                           font=(T.FONT, 10, "bold"), padx=20, pady=12, cursor="hand2")
            lab.pack(fill="x")
            badge = tk.Label(btn, textvariable=self._nav_badges[key], bg=T.SIDEBAR, fg="#8FA6C4",
                             anchor="w", font=(T.FONT, 8), padx=44, cursor="hand2")
            badge.pack(fill="x", pady=(0, 6))
            for w in (btn, lab, badge):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
            self._nav_buttons[key] = (btn, lab, badge)

        tk.Frame(side, bg=T.SIDEBAR).pack(fill="both", expand=True)
        tk.Label(side, text="수집기(Klook · KKday · GYG · Trip.com · MRT)\n는 v1.3 검증 버전 그대로 사용",
                 bg=T.SIDEBAR, fg="#6F86A6", font=(T.FONT, 7), justify="left").pack(anchor="w", padx=20, pady=16)

        self.content = tk.Frame(self.root, bg=T.BG)
        self.content.pack(side="left", fill="both", expand=True)

        from ui.chrome_page import ChromePage
        from ui.collect_page import CollectPage
        from ui.results_page import ResultsPage
        self.pages["chrome"] = ChromePage(self.content, self)
        self.pages["collect"] = CollectPage(self.content, self)
        self.pages["results"] = ResultsPage(self.content, self)
        self.show("chrome")
        self.refresh_nav()

    def show(self, key: str):
        if key == "results" and self.result is None:
            messagebox.showinfo("결과", "먼저 ② 리뷰 수집을 실행하세요.")
            return
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self.current = key
        on_show = getattr(self.pages[key], "on_show", None)
        if callable(on_show):
            on_show()
        for k, (btn, lab, badge) in self._nav_buttons.items():
            bg = T.SIDEBAR_ACTIVE if k == key else T.SIDEBAR
            fg = "#FFFFFF" if k == key else T.SIDEBAR_TEXT
            for w in (btn, lab, badge):
                w.configure(bg=bg)
            lab.configure(fg=fg)

    def refresh_nav(self):
        running = [k for k in self.manager.profile_keys if self.manager.is_running(k)]
        self._nav_badges["chrome"].set(
            f"실행 중 {len(running)}/{len(self.manager.profile_keys)}" + (f" · {', '.join(running)}" if running else ""))
        collect = self.pages.get("collect")
        self._nav_badges["collect"].set(getattr(collect, "nav_hint", "") if collect else "")
        if self.result is not None:
            s = self.result.scope
            self._nav_badges["results"].set(f"{s.start_date:%m/%d} ~ {s.end_date:%m/%d} · 리뷰 "
                                            f"{int(self.result.overall.iloc[0]['Reviews']):,}")
        else:
            self._nav_badges["results"].set("수집 후 표시")

    def set_result(self, result):
        self.result = result
        self.pages["results"].load(result)
        self.refresh_nav()
        self.show("results")

    def open_path(self, path):
        try:
            os.startfile(str(path))  # Windows
        except Exception as exc:
            messagebox.showinfo("위치", f"{path}\n\n{exc}")

    def run(self):
        self.root.mainloop()
