"""① 지역별 Chrome 연결.

지역(Profile)마다 전용 Chrome 을 따로 켜고, 따로 로그인 상태를 확인하고, 따로 끈다.
  - 지역별 Chrome : 카드 하나 = Chrome 계정 하나 (KR / JP / AU / UK / 추가 계정)
  - OTA 연결표    : 국가 × OTA → 어떤 Chrome 계정으로 수집할지
  - Area 예외     : 같은 국가 안에서 특정 Area 만 다른 계정을 쓸 때
  - 계정 추가/수정 : 계정이 더 나뉘면 새 Chrome 계정(Profile) 추가
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from collectors.config import CHANNEL_DISPLAY, SUPPORTED_CHANNELS
from core.browser_profiles import REGION_LABELS, area_group, find_legacy_app_dirs
from core.chrome_check import LOGIN_REQUIRED, OK, check_profile_logins, open_login_pages
from ui import theme as T

CHIP_COLORS = {
    OK: (T.GOOD, T.GOOD_SOFT),
    LOGIN_REQUIRED: (T.BAD, T.BAD_SOFT),
}


class ChromePage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.BG)
        self.app = app
        self.cards: dict[str, dict] = {}
        self.status_var = tk.StringVar(value="")
        self._busy: set[str] = set()
        self._build()
        self._poll()

    @property
    def manager(self):
        return self.app.manager

    # ------------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x", padx=26, pady=(20, 6))
        tk.Label(head, text="지역별 Chrome 연결", bg=T.BG, fg=T.TEXT, font=(T.FONT, 18, "bold")).pack(side="left")
        ttk.Button(head, text="다음: 리뷰 수집 →", style="Accent.TButton",
                   command=lambda: self.app.show("collect")).pack(side="right")
        tk.Label(self, text="지역마다 전용 Chrome 이 따로 있습니다. 각 카드에서 Chrome 을 열어 OTA 에 한 번 로그인하면 "
                            "로그인 상태가 그 지역 Chrome 에 저장됩니다. 수집할 때는 필요한 지역 Chrome 만 자동으로 켜집니다.",
                 bg=T.BG, fg=T.MUTED, font=(T.FONT, 9), justify="left", wraplength=1050).pack(anchor="w", padx=28)

        self.banner = tk.Frame(self, bg=T.WARN_SOFT, padx=14, pady=10,
                               highlightthickness=1, highlightbackground="#F1D29A")
        self._build_legacy_banner()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=26, pady=(10, 6))
        self.nb = nb
        self.tab_cards = tk.Frame(nb, bg=T.BG)
        self.tab_routes = tk.Frame(nb, bg=T.CARD, padx=16, pady=14)
        self.tab_area = tk.Frame(nb, bg=T.CARD, padx=16, pady=14)
        self.tab_profiles = tk.Frame(nb, bg=T.CARD, padx=16, pady=14)
        nb.add(self.tab_cards, text="지역별 Chrome")
        nb.add(self.tab_routes, text="OTA 연결표 (국가 × OTA)")
        nb.add(self.tab_area, text="Area 예외")
        nb.add(self.tab_profiles, text="Chrome 계정 추가 · 수정")

        self._build_cards_tab()
        self._build_routes_tab()
        self._build_area_tab()
        self._build_profiles_tab()

        tk.Label(self, textvariable=self.status_var, bg=T.BG, fg=T.MUTED, font=(T.FONT, 9),
                 anchor="w").pack(fill="x", padx=28, pady=(0, 10))

    # ------------------------------------------------------------------
    # v1.3 로그인 폴더 연결 배너
    # ------------------------------------------------------------------
    def _legacy_to_link(self):
        out = []
        for legacy in find_legacy_app_dirs():
            cands = self.manager.legacy_candidates(legacy)
            todo = {k: p for k, p in cands.items() if self.manager.profile_dir(k).resolve() != p.resolve()}
            if todo:
                out.append((legacy, todo))
        return out

    def _build_legacy_banner(self):
        for w in self.banner.winfo_children():
            w.destroy()
        found = self._legacy_to_link()
        if not found:
            self.banner.pack_forget()
            return
        legacy, todo = found[0]
        self.banner.pack(fill="x", padx=26, pady=(10, 0))
        tk.Label(self.banner, text="기존 v1.3 로그인 폴더를 찾았습니다", bg=T.WARN_SOFT, fg=T.WARN,
                 font=(T.FONT, 10, "bold")).pack(anchor="w")
        tk.Label(self.banner,
                 text=f"{legacy.name} 안의 {', '.join(f'{k}({p.name})' for k, p in todo.items())} 를 그대로 쓰면 "
                      "OTA 에 다시 로그인하지 않아도 됩니다. 폴더는 복사하지 않고 연결만 합니다 (v1.3 폴더를 지우지 마세요).",
                 bg=T.WARN_SOFT, fg=T.TEXT, font=(T.FONT, 9), wraplength=980, justify="left").pack(anchor="w", pady=(3, 8))
        row = tk.Frame(self.banner, bg=T.WARN_SOFT)
        row.pack(anchor="w")
        ttk.Button(row, text="기존 로그인 그대로 사용", style="Accent.TButton",
                   command=lambda: self._link_legacy(legacy)).pack(side="left")
        ttk.Button(row, text="새로 로그인할게요 (숨기기)",
                   command=self.banner.pack_forget).pack(side="left", padx=8)

    def _link_legacy(self, legacy):
        running = [k for k in self.manager.legacy_candidates(legacy) if self.manager.is_running(k)]
        if running:
            messagebox.showwarning("Chrome 종료 필요",
                                   f"다음 지역 Chrome 이 켜져 있습니다: {', '.join(running)}\n"
                                   "카드의 [닫기] 로 끈 뒤 다시 눌러 주세요.")
            return
        linked = self.manager.link_legacy_profiles(legacy)
        self._build_legacy_banner()
        self.rebuild_cards()
        self.status_var.set(f"v1.3 로그인 폴더 연결 완료: {', '.join(linked)}")

    # ------------------------------------------------------------------
    # 지역별 Chrome 카드
    # ------------------------------------------------------------------
    def _build_cards_tab(self):
        bar = tk.Frame(self.tab_cards, bg=T.BG)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Button(bar, text="상태 새로고침", command=self.refresh_status).pack(side="left")
        ttk.Button(bar, text="켜진 Chrome 전부 로그인 확인", command=self.check_all_running).pack(side="left", padx=6)
        tk.Label(bar, text="● 실행 중   ○ 꺼짐   |   로그인 확인은 리뷰 페이지가 로그인 화면으로 넘어가는지 보는 추정입니다.",
                 bg=T.BG, fg=T.MUTED, font=(T.FONT, 8)).pack(side="right")
        self.scroll = T.ScrollFrame(self.tab_cards)
        self.scroll.pack(fill="both", expand=True)
        self.rebuild_cards()

    def rebuild_cards(self):
        body = self.scroll.body
        for w in body.winfo_children():
            w.destroy()
        self.cards = {}
        keys = self.manager.profile_keys
        order = list(REGION_LABELS)
        keys = sorted(keys, key=lambda k: (order.index(self.manager.profile_region(k))
                                           if self.manager.profile_region(k) in order else 99, k))
        for i, key in enumerate(keys):
            r, c = divmod(i, 2)
            frame = self._make_card(body, key)
            frame.grid(row=r, column=c, sticky="nsew", padx=(0 if c == 0 else 6, 6 if c == 0 else 0), pady=6)
            body.grid_columnconfigure(c, weight=1, uniform="cards")
        self.refresh_status()

    def _make_card(self, parent, key):
        m = self.manager
        region = m.profile_region(key)
        color = T.REGION_COLORS.get(region, T.MUTED)
        f = tk.Frame(parent, bg=T.CARD, highlightthickness=1, highlightbackground=T.BORDER)
        tk.Frame(f, bg=color, height=5).pack(fill="x")
        inner = tk.Frame(f, bg=T.CARD, padx=16, pady=12)
        inner.pack(fill="both", expand=True)

        top = tk.Frame(inner, bg=T.CARD)
        top.pack(fill="x")
        tk.Label(top, text=f"{REGION_LABELS.get(region, '기타')} · {key}", bg=T.CARD, fg=color,
                 font=(T.FONT, 14, "bold")).pack(side="left")
        dot = tk.Label(top, text="○ 꺼짐", bg=T.CARD, fg=T.MUTED, font=(T.FONT, 10, "bold"))
        dot.pack(side="right")
        tk.Label(inner, text=m.profile_name(key), bg=T.CARD, fg=T.TEXT, font=(T.FONT, 10)).pack(anchor="w", pady=(2, 0))
        folder = m.profile_dir(key)
        tk.Label(inner, text=f"port {m.profile_port(key)}  ·  {folder}", bg=T.CARD, fg=T.MUTED,
                 font=(T.FONT, 8), wraplength=520, justify="left").pack(anchor="w")

        uses = m.channels_for_profile(key)
        use_text = "\n".join(f"{region_name}  ·  {', '.join(CHANNEL_DISPLAY.get(c, c) for c in chs)}"
                             for region_name, chs in uses.items()) or "연결된 OTA 없음 (OTA 연결표에서 지정)"
        use_box = tk.Frame(inner, bg=T.CARD_ALT, padx=8, pady=6)
        use_box.pack(fill="x", pady=(8, 6))
        tk.Label(use_box, text="담당", bg=T.CARD_ALT, fg=T.MUTED, font=(T.FONT, 8, "bold")).pack(side="left", anchor="n")
        tk.Label(use_box, text=use_text, bg=T.CARD_ALT, fg=T.TEXT, font=(T.FONT, 9),
                 justify="left", anchor="w").pack(side="left", padx=(8, 0), fill="x")

        chips = tk.Frame(inner, bg=T.CARD)
        chips.pack(fill="x")
        chans = self._profile_channels(key)
        chip_labels = {}
        for i, ch in enumerate(chans):
            lab = tk.Label(chips, text=f"{CHANNEL_DISPLAY.get(ch, ch)} · 미확인", bg=T.CARD_ALT, fg=T.MUTED,
                           font=(T.FONT, 8, "bold"), padx=7, pady=3)
            lab.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 5), pady=2)
            chip_labels[ch] = lab

        btns = tk.Frame(inner, bg=T.CARD)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Chrome 열기 · OTA 로그인", style="Accent.TButton",
                   command=lambda k=key: self.open_chrome(k)).pack(side="left")
        ttk.Button(btns, text="로그인 확인", command=lambda k=key: self.check_logins(k)).pack(side="left", padx=6)
        ttk.Button(btns, text="닫기", command=lambda k=key: self.close_chrome(k)).pack(side="left")
        busy = tk.Label(btns, text="", bg=T.CARD, fg=T.ACCENT, font=(T.FONT, 8))
        busy.pack(side="right")
        self.cards[key] = {"dot": dot, "chips": chip_labels, "busy": busy}
        self._paint_chips(key)
        return f

    def _profile_channels(self, key) -> list[str]:
        chans = {c for lst in self.manager.channels_for_profile(key).values() for c in lst}
        return [c for c in SUPPORTED_CHANNELS if c in chans]

    def _paint_chips(self, key):
        card = self.cards.get(key)
        if not card:
            return
        states = self.app.login_states.get(key, {})
        for ch, lab in card["chips"].items():
            st = states.get(ch)
            if st is None:
                lab.configure(text=f"{CHANNEL_DISPLAY.get(ch, ch)} · 미확인", fg=T.MUTED, bg=T.CARD_ALT)
                continue
            fg, bg = CHIP_COLORS.get(st.status, (T.WARN, T.WARN_SOFT))
            mark = "✓" if st.status == OK else "✗" if st.status == LOGIN_REQUIRED else "?"
            lab.configure(text=f"{mark} {CHANNEL_DISPLAY.get(ch, ch)} · {st.label}", fg=fg, bg=bg)

    def refresh_status(self):
        for key, card in self.cards.items():
            try:
                running = self.manager.is_running(key)
            except KeyError:
                continue
            card["dot"].configure(text="● 실행 중" if running else "○ 꺼짐", fg=T.GOOD if running else T.MUTED)
        self.app.refresh_nav()

    def _poll(self):
        if self.app.current == "chrome":
            self.refresh_status()
        self.after(3000, self._poll)

    def on_show(self):
        self.manager.reload()
        self._build_legacy_banner()
        self.rebuild_cards()

    # ------------------------------------------------------------------
    # 카드 동작 (각 지역 Chrome 을 따로)
    # ------------------------------------------------------------------
    def _run_bg(self, key, label, fn, done):
        if key in self._busy:
            return
        self._busy.add(key)
        if key in self.cards:
            self.cards[key]["busy"].configure(text=label)

        def worker():
            try:
                res = fn()
                err = None
            except Exception as exc:
                res, err = None, exc
            self.after(0, lambda: finish(res, err))

        def finish(res, err):
            self._busy.discard(key)
            if key in self.cards:
                self.cards[key]["busy"].configure(text="")
            if err is not None:
                messagebox.showerror("Chrome", f"{key}: {err}")
            else:
                done(res)
            self.refresh_status()

        threading.Thread(target=worker, daemon=True).start()

    def open_chrome(self, key):
        chans = self._profile_channels(key)

        def done(started):
            self.status_var.set(
                f"{key} Chrome {'을 열었습니다' if started else '에 OTA 탭을 열었습니다'}. "
                "처음이면 각 탭에서 로그인한 뒤 [로그인 확인] 을 눌러 주세요.")
        self._run_bg(key, "여는 중...", lambda: open_login_pages(self.manager, key, chans), done)

    def check_logins(self, key):
        chans = self._profile_channels(key)
        if not chans:
            messagebox.showinfo("로그인 확인", f"{key} 에 연결된 OTA 가 없습니다. OTA 연결표에서 지정하세요.")
            return
        if not self.manager.is_running(key):
            if not messagebox.askyesno("로그인 확인", f"{key} Chrome 이 꺼져 있습니다. 켜고 확인할까요?"):
                return

        def fn():
            self.manager.ensure_profile(key)
            return check_profile_logins(self.manager, key, chans,
                                        log=lambda m: self.after(0, lambda: self.status_var.set(m)))

        def done(states):
            self.app.login_states[key] = {s.channel: s for s in states}
            self._paint_chips(key)
            need = [CHANNEL_DISPLAY.get(s.channel, s.channel) for s in states if s.status == LOGIN_REQUIRED]
            self.status_var.set(f"{key} 로그인 확인 완료" + (f" · 로그인 필요: {', '.join(need)}" if need else ""))
            pages = self.app.pages.get("collect")
            if pages is not None:
                pages.update_route_preview()
        self._run_bg(key, "확인 중...", fn, done)

    def check_all_running(self):
        keys = [k for k in self.manager.profile_keys if self.manager.is_running(k)]
        if not keys:
            messagebox.showinfo("로그인 확인", "켜진 지역 Chrome 이 없습니다.")
            return
        for k in keys:
            self.check_logins(k)

    def close_chrome(self, key):
        if not self.manager.is_running(key):
            self.status_var.set(f"{key} Chrome 은 이미 꺼져 있습니다.")
            return

        def done(ok):
            self.status_var.set(f"{key} Chrome 을 닫았습니다." if ok else
                                f"{key} Chrome 이 닫히지 않았습니다. Chrome 창을 직접 닫아 주세요.")
        self._run_bg(key, "닫는 중...", lambda: self.manager.close_profile(key), done)

    # ------------------------------------------------------------------
    # OTA 연결표
    # ------------------------------------------------------------------
    def _build_routes_tab(self):
        tab = self.tab_routes
        tk.Label(tab, text="국가 × OTA → Chrome 계정", bg=T.CARD, fg=T.TEXT, font=(T.FONT, 12, "bold")).pack(anchor="w")
        tk.Label(tab, text="현재 운영: 한국 5개 OTA = KR · 일본 Klook/GYG = JP, Trip.com/MRT = KR 공용 · "
                           "호주 Klook/GYG/Trip.com = AU · 영국 Klook/GYG = UK. "
                           "'미설정' 이면 그 조합은 수집하지 않습니다 (잘못된 계정으로 수집 방지).",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9), wraplength=1000, justify="left").pack(anchor="w", pady=(4, 12))
        grid = tk.Frame(tab, bg=T.CARD)
        grid.pack(anchor="w")
        tk.Label(grid, text="국가", bg=T.CARD, fg=T.TEXT, font=(T.FONT, 9, "bold"), width=12).grid(row=0, column=0, pady=6)
        for ci, ch in enumerate(SUPPORTED_CHANNELS, start=1):
            tk.Label(grid, text=CHANNEL_DISPLAY[ch], bg=T.CARD, fg=T.TEXT, font=(T.FONT, 9, "bold"),
                     width=16).grid(row=0, column=ci, padx=4, pady=6)
        self.route_vars: dict[tuple[str, str], tk.StringVar] = {}
        self.route_combos = []
        for ri, (group, label) in enumerate(REGION_LABELS.items(), start=1):
            tk.Label(grid, text=label, bg=T.CARD, fg=T.REGION_COLORS.get(group, T.TEXT),
                     font=(T.FONT, 10, "bold"), width=12).grid(row=ri, column=0, pady=7)
            for ci, ch in enumerate(SUPPORTED_CHANNELS, start=1):
                var = tk.StringVar()
                self.route_vars[(group, ch)] = var
                cb = ttk.Combobox(grid, textvariable=var, state="readonly", width=14)
                cb.grid(row=ri, column=ci, padx=4, pady=7)
                self.route_combos.append(cb)
        btns = tk.Frame(tab, bg=T.CARD)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text="다시 불러오기", command=self.load_routes).pack(side="left")
        ttk.Button(btns, text="연결 저장", style="Accent.TButton", command=self.save_routes).pack(side="left", padx=8)
        self.load_routes()

    def load_routes(self):
        self.manager.reload()
        values = ["미설정"] + self.manager.profile_keys
        for cb in self.route_combos:
            cb.configure(values=values)
        for (group, ch), var in self.route_vars.items():
            var.set(self.manager.config.get("routes", {}).get(group, {}).get(ch) or "미설정")

    def save_routes(self):
        try:
            for (group, ch), var in self.route_vars.items():
                self.manager.set_region_route(group, ch, None if var.get() == "미설정" else var.get())
        except Exception as exc:
            messagebox.showerror("저장 오류", str(exc))
            return
        self.rebuild_cards()
        self.status_var.set("OTA 연결표를 저장했습니다. 다음 수집부터 적용됩니다.")

    # ------------------------------------------------------------------
    # Area 예외
    # ------------------------------------------------------------------
    def _build_area_tab(self):
        tab = self.tab_area
        tk.Label(tab, text="Area 예외", bg=T.CARD, fg=T.TEXT, font=(T.FONT, 12, "bold")).pack(anchor="w")
        tk.Label(tab, text="같은 국가 안에서 특정 Area 의 OTA 만 다른 계정을 쓸 때 사용합니다. 예: Sapporo + Klook → JP_KLOOK_2. "
                           "예외가 없으면 OTA 연결표의 국가 기본값을 씁니다.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9), wraplength=1000, justify="left").pack(anchor="w", pady=(4, 10))
        frame, self.area_tree = T.make_tree(tab, ("Area", "국가", "OTA", "예외 계정", "실제 사용"),
                                            {"Area": 220, "국가": 110, "OTA": 160, "예외 계정": 140, "실제 사용": 140})
        frame.pack(fill="both", expand=True)
        btns = tk.Frame(tab, bg=T.CARD)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="+ 예외 추가", command=lambda: self.area_editor(None)).pack(side="left")
        ttk.Button(btns, text="선택 수정", command=self._edit_area).pack(side="left", padx=6)
        ttk.Button(btns, text="선택 삭제", command=self._delete_area).pack(side="left")
        self.refresh_area_routes()

    def refresh_area_routes(self):
        tree = self.area_tree
        tree.delete(*tree.get_children())
        n = 0
        for area, routes in sorted((self.manager.config.get("area_routes") or {}).items()):
            for ch, override in routes.items():
                n += 1
                tree.insert("", "end", iid=f"{n}", values=(
                    area, REGION_LABELS.get(area_group(area), "기타"), CHANNEL_DISPLAY.get(ch, ch),
                    override or "미설정", self.manager.route_profile(area, ch) or "미설정"))

    def _selected_area_row(self):
        sel = self.area_tree.selection()
        return self.area_tree.item(sel[0], "values") if sel else None

    def _edit_area(self):
        vals = self._selected_area_row()
        if vals:
            self.area_editor(vals)

    def _delete_area(self):
        vals = self._selected_area_row()
        if not vals:
            return
        ch = next((c for c in SUPPORTED_CHANNELS if CHANNEL_DISPLAY.get(c, c) == vals[2]), None)
        if ch:
            self.manager.remove_area_route(vals[0], ch)
            self.refresh_area_routes()
            self.rebuild_cards()

    def area_editor(self, existing):
        dlg = tk.Toplevel(self)
        dlg.title("Area 예외")
        dlg.configure(bg=T.BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        form = tk.Frame(dlg, bg=T.CARD, padx=18, pady=18)
        form.pack(fill="both", expand=True, padx=16, pady=16)
        areas = []
        collect = self.app.pages.get("collect")
        if collect is not None and getattr(collect, "loaded", None) is not None:
            areas = collect.loaded.areas
        area_var = tk.StringVar(value=existing[0] if existing else "")
        ch_init = "L"
        if existing:
            ch_init = next((c for c in SUPPORTED_CHANNELS if CHANNEL_DISPLAY.get(c, c) == existing[2]), "L")
        ch_var = tk.StringVar(value=ch_init)
        prof_var = tk.StringVar(value=existing[3] if existing else "(국가 기본값)")
        tk.Label(form, text="Area", bg=T.CARD).grid(row=0, column=0, sticky="w", pady=7)
        ttk.Combobox(form, textvariable=area_var, values=areas, width=32).grid(row=0, column=1, pady=7)
        tk.Label(form, text="OTA", bg=T.CARD).grid(row=1, column=0, sticky="w", pady=7)
        ttk.Combobox(form, textvariable=ch_var, values=list(SUPPORTED_CHANNELS), state="readonly",
                     width=32).grid(row=1, column=1, pady=7)
        tk.Label(form, text="Chrome 계정", bg=T.CARD).grid(row=2, column=0, sticky="w", pady=7)
        ttk.Combobox(form, textvariable=prof_var, values=["(국가 기본값)", "미설정"] + self.manager.profile_keys,
                     state="readonly", width=32).grid(row=2, column=1, pady=7)
        tk.Label(form, text="L=Klook · KK=KKday · GG=GetYourGuide · TPC=Trip.com/Ctrip · MRT=MyRealTrip",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 8)).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save():
            try:
                v = prof_var.get()
                if v == "(국가 기본값)":
                    self.manager.remove_area_route(area_var.get(), ch_var.get())
                else:
                    self.manager.set_area_route(area_var.get(), ch_var.get(), None if v == "미설정" else v)
            except Exception as exc:
                messagebox.showerror("저장 오류", str(exc), parent=dlg)
                return
            self.refresh_area_routes()
            self.rebuild_cards()
            dlg.destroy()

        row = tk.Frame(form, bg=T.CARD)
        row.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(row, text="취소", command=dlg.destroy).pack(side="left")
        ttk.Button(row, text="저장", style="Accent.TButton", command=save).pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------
    # Chrome 계정 추가 / 수정
    # ------------------------------------------------------------------
    def _build_profiles_tab(self):
        tab = self.tab_profiles
        tk.Label(tab, text="Chrome 계정 (Profile)", bg=T.CARD, fg=T.TEXT, font=(T.FONT, 12, "bold")).pack(anchor="w")
        tk.Label(tab, text="OTA 계정이 더 나뉘면 새 Chrome 계정을 추가하세요. 예: JP_TPC · AU_KLOOK_2. "
                           "계정마다 로그인 상태가 따로 저장되고, 추가하면 '지역별 Chrome' 에 카드가 생깁니다.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9), wraplength=1000, justify="left").pack(anchor="w", pady=(4, 10))
        frame, self.prof_tree = T.make_tree(tab, ("ID", "이름", "국가", "Port", "Profile 폴더", "사용처"),
                                            {"ID": 90, "이름": 170, "국가": 80, "Port": 70,
                                             "Profile 폴더": 340, "사용처": 260})
        frame.pack(fill="both", expand=True)
        btns = tk.Frame(tab, bg=T.CARD)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="+ 계정 추가", command=lambda: self.profile_editor(None)).pack(side="left")
        ttk.Button(btns, text="선택 수정", command=self._edit_profile).pack(side="left", padx=6)
        ttk.Button(btns, text="선택 삭제", command=self._delete_profile).pack(side="left")
        self.refresh_profiles()

    def refresh_profiles(self):
        tree = self.prof_tree
        tree.delete(*tree.get_children())
        for k in self.manager.profile_keys:
            tree.insert("", "end", iid=k, values=(
                k, self.manager.profile_name(k), REGION_LABELS.get(self.manager.profile_region(k), "기타"),
                self.manager.profile_port(k), str(self.manager.profile_dir(k)),
                ", ".join(self.manager.profile_uses(k)) or "-"))

    def _edit_profile(self):
        sel = self.prof_tree.selection()
        if sel:
            self.profile_editor(sel[0])

    def _delete_profile(self):
        sel = self.prof_tree.selection()
        if not sel:
            return
        key = sel[0]
        if not messagebox.askyesno("계정 삭제", f"{key} 계정을 목록에서 삭제할까요?\n(로그인 폴더 자체는 지우지 않습니다.)"):
            return
        try:
            self.manager.delete_profile(key)
        except Exception as exc:
            messagebox.showerror("삭제 불가", str(exc))
            return
        self._after_profile_change()

    def _after_profile_change(self):
        self.refresh_profiles()
        self.load_routes()
        self.rebuild_cards()

    def profile_editor(self, key):
        m = self.manager
        dlg = tk.Toplevel(self)
        dlg.title("Chrome 계정 수정" if key else "Chrome 계정 추가")
        dlg.configure(bg=T.BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        info = m.profile_info(key) if key else {}
        region_names = list(REGION_LABELS.values())
        v = {
            "id": tk.StringVar(value=key or ""),
            "name": tk.StringVar(value=info.get("name", "")),
            "region": tk.StringVar(value=REGION_LABELS.get(info.get("region", "OTHER"), "기타")),
            "port": tk.StringVar(value=str(info.get("port", m.next_free_port()))),
            "dir": tk.StringVar(value=info.get("profile_dir", "")),
        }
        form = tk.Frame(dlg, bg=T.CARD, padx=18, pady=18)
        form.pack(fill="both", expand=True, padx=16, pady=16)
        rows = [("계정 ID", "id"), ("표시 이름", "name"), ("국가", "region"), ("Debug Port", "port"),
                ("Profile 폴더", "dir")]
        for r, (label, k) in enumerate(rows):
            tk.Label(form, text=label, bg=T.CARD, width=12, anchor="w").grid(row=r, column=0, sticky="w", pady=6)
            if k == "region":
                w = ttk.Combobox(form, textvariable=v[k], values=region_names, state="readonly", width=40)
            else:
                w = ttk.Entry(form, textvariable=v[k], width=43)
            w.grid(row=r, column=1, sticky="w", pady=6)
            if key and k == "id":
                w.configure(state="disabled")
        tk.Label(form, text="Profile 폴더를 비워 두면 chrome_profiles/<계정 ID> 에 새로 만듭니다.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 8)).grid(row=5, column=0, columnspan=2, sticky="w")

        def save():
            region = next((g for g, lab in REGION_LABELS.items() if lab == v["region"].get()), "OTHER")
            try:
                new_key = m.upsert_profile(v["id"].get(), v["name"].get(), int(v["port"].get() or 0),
                                           v["dir"].get() or f"chrome_profiles/{v['id'].get().strip().upper()}",
                                           region)
            except Exception as exc:
                messagebox.showerror("저장 오류", str(exc), parent=dlg)
                return
            dlg.destroy()
            self._after_profile_change()
            self.status_var.set(f"{new_key} 계정을 저장했습니다. OTA 연결표에서 이 계정을 지정하세요.")

        row = tk.Frame(form, bg=T.CARD)
        row.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(row, text="취소", command=dlg.destroy).pack(side="left")
        ttk.Button(row, text="저장", style="Accent.TButton", command=save).pack(side="left", padx=(8, 0))
