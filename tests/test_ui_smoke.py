# -*- coding: utf-8 -*-
"""화면 전체 흐름 시험 (실제 OTA · Chrome 없이).

① 지역별 Chrome  → ② 리뷰 수집(주/월, 국가, 미리보기, 실행)  → ③ 결과(투어표, 보고 텍스트, 성과제,
수집 상태, GPT Excel, 투어 상세) 를 가짜 수집기로 끝까지 돌린다. 설정 파일은 임시 폴더를 쓴다.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from tkinter import filedialog, messagebox

FAIL = []


def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok:
        FAIL.append(n)


ASKED = []
for name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, name, lambda *a, _n=name, **k: ASKED.append((_n, a[:2])))
for name in ("askyesno", "askokcancel"):
    setattr(messagebox, name, lambda *a, _n=name, **k: (ASKED.append((_n, a[:2])), True)[1])

TMP = Path(tempfile.mkdtemp())
XL = TMP / "bookings.xlsx"
rows = []
for d in pd.date_range("2026-10-26", "2026-11-29"):
    for area, ag, guide in [("Seoul", "L", "김민준"), ("Seoul", "KK", "이서연"), ("Busan", "GG", "박지훈"),
                            ("Tokyo", "L", "Sato"), ("Tokyo", "TPC", "Sato"), ("Sydney", "L", "Kim"),
                            ("Seoul", "ETC", "김민준")]:
        rows.append({"Date": d, "Agency": ag, "Agency Code": f"{ag}{d:%m%d}{area[:2]}", "Area": area,
                     "Product": f"{area} Day Tour", "Main Guide": guide, "People": 2})
pd.DataFrame(rows).to_excel(XL, index=False)

# ---- 가짜 브라우저 · 수집기 -----------------------------------------------
from core import pipeline
from core.browser_profiles import BrowserProfileManager

SRC = pd.DataFrame(rows)


class FakeBrowser:
    def __init__(self, debug_address=""):
        pass

    def connect(self):
        pass


def fake(ch):
    def collect(ctx, a, b):
        sub = SRC[(SRC.Agency == ch) & (SRC.Date >= a) & (SRC.Date <= b)]
        ctx.log(f"[{ch}] fake {len(sub)}")
        return {c: {"rating": str([5, 5, 4, 2][i % 4]), "content": f"리뷰 {c}", "review_date": a}
                for i, c in enumerate(sub["Agency Code"])}
    return collect


pipeline.BrowserSession = FakeBrowser
pipeline.COLLECTORS = {ch: fake(ch) for ch in pipeline.COLLECTORS}
if "TPC" in pipeline.COLLECTORS:
    def tpc_fail(ctx, a, b):
        raise RuntimeError("Trip.com/Ctrip request capture failed")
    pipeline.COLLECTORS["TPC"] = tpc_fail

mgr = BrowserProfileManager(config_path=TMP / "routing.json")
mgr._port_open = lambda port, timeout=0.35: False   # 실제로 켜져 있는 Chrome 과 무관하게
mgr.ensure_profile = lambda *a, **k: (False, True)
mgr.ensure_required = lambda *a, **k: ([], [])

from ui.app import App

app = App(manager=mgr)
app.root.withdraw()

print("=" * 66); print("① 지역별 Chrome"); print("=" * 66)
cp = app.pages["chrome"]
ck("지역 카드 4개 (KR/JP/AU/UK)", sorted(cp.cards) == ["AU", "JP", "KR", "UK"], sorted(cp.cards))
ck("KR 카드 담당 OTA 칩 5개", len(cp.cards["KR"]["chips"]) == 5, list(cp.cards["KR"]["chips"]))
ck("JP 카드 칩 = Klook, GYG", list(cp.cards["JP"]["chips"]) == ["L", "GG"], list(cp.cards["JP"]["chips"]))
legacy = cp._legacy_to_link()
ck("v1.3 로그인 폴더 감지", bool(legacy), [str(x[0].name) for x in legacy])
if legacy:
    cp._link_legacy(legacy[0][0])
    ck("KR 이 v1.3 Chrome_debug 를 사용", mgr.profile_dir("KR").name == "Chrome_debug", mgr.profile_dir("KR"))
    ck("연결 후 배너 숨김", not cp._legacy_to_link())
mgr.upsert_profile("JP_TPC", "일본 Trip.com", mgr.next_free_port(), "", "JAPAN")
cp.load_routes()
cp.route_vars[("JAPAN", "TPC")].set("JP_TPC")
cp.save_routes()
ck("새 계정 카드 생성", "JP_TPC" in cp.cards)
ck("일본 TPC → JP_TPC 저장", mgr.route_profile("Tokyo", "TPC") == "JP_TPC")
ck("KR 카드에서 일본 TPC 빠짐", "일본" not in mgr.channels_for_profile("KR") or
   "TPC" not in mgr.channels_for_profile("KR")["일본"], mgr.channels_for_profile("KR"))
mgr.set_area_route("Busan", "GG", None)
cp.refresh_area_routes()
ck("Area 예외 표시", len(cp.area_tree.get_children()) == 1)
try:
    mgr.delete_profile("JP_TPC")
    ck("사용 중 계정 삭제 막기", False)
except ValueError:
    ck("사용 중 계정 삭제 막기", True)

print("\n" + "=" * 66); print("② 리뷰 수집"); print("=" * 66)
app.show("collect")
cl = app.pages["collect"]
cl.choose_file(str(XL))
ck("기본 = 주단위 최신 주", (cl.start_var.get(), cl.end_var.get()) == ("2026-11-23", "2026-11-29"),
   (cl.start_var.get(), cl.end_var.get()))
ck("국가 체크박스", list(cl.country_vars) == ["KOREA", "JAPAN", "AUSTRALIA"], list(cl.country_vars))
cl.mode_var.set("month"); cl.on_mode_change()
ck("월단위 = 11월 전체", (cl.start_var.get(), cl.end_var.get()) == ("2026-11-01", "2026-11-30"))
cl.mode_var.set("week"); cl.on_mode_change()
cl.period_var.set(list(cl._periods)[1]); cl.on_period_pick()
ck("이전 주 선택", cl.start_var.get() == "2026-11-16", cl.start_var.get())
cl.country_vars["AUSTRALIA"].set(False); cl.on_country("AUSTRALIA")
ck("호주 해제 → Sydney 제외", "Sydney" not in cl.selected_areas(), cl.selected_areas())
routes = [cl.route_tree.item(i, "values") for i in cl.route_tree.get_children()]
print("   미리보기:", routes)
ck("Busan GYG 예외 → 미설정 행", any(r[0].startswith("⚠ 미설정") and "Busan" in r[1] for r in routes))
ck("Tokyo TPC → JP_TPC 행", any(r[0].startswith("JP_TPC") for r in routes))
ck("결과 파일명", "Review Crawler 주간 2026-11-16_2026-11-22 Korea_Japan.xlsx" in cl.output_var.get(),
   cl.output_var.get())
cl.output_dir = str(TMP)
cl.split_var.set("area"); cl.update_preview()
ck("지역별 미리보기", "Excel 4개" in cl.files_var.get() and "Busan" in cl.files_var.get(), cl.files_var.get())
cl.split_var.set("country"); cl.update_preview()
ck("국가별 미리보기", "Excel 3개" in cl.files_var.get(), cl.files_var.get())
ASKED.clear()
cl.start()
ck("미설정 경고 후 계속", any("미설정" in str(a[1]) for a in ASKED), [a[1][0] for a in ASKED])
deadline = time.time() + 60
while app.result is None and time.time() < deadline:
    app.root.update()
    time.sleep(0.05)
ck("수집 완료 → 결과 화면", app.result is not None and app.current == "results", app.current)

print("\n" + "=" * 66); print("③ 결과"); print("=" * 66)
res = app.result
ck("통합 + 국가별 2개 저장", [lab for lab, _ in res.output_files] == ["통합", "한국 (Busan, Seoul)", "일본 (Tokyo)"],
   [lab for lab, _ in res.output_files])
ck("파일 모두 존재", all(Path(p).exists() for _, p in res.output_files))
out = Path(res.output_path)
ck("결과 Excel 저장", out.exists(), out.name)
from openpyxl import load_workbook
wb = load_workbook(out)
ck("시트: 지사 요약 · 성과제 · 투어별 리뷰 총정리 먼저", wb.sheetnames[:3] == ["지사 요약", "성과제", "투어별 리뷰 총정리"])
st = res.collection_status
ck("TPC 실패 기록", st["TPC"]["status"] == "FAILED", st["TPC"]["status"])
ck("GYG 미설정 기록", st["GG"]["status"] in ("FAILED",) and "UNCONFIGURED" in st["GG"]["profiles"],
   st["GG"]["status"])
rp = app.pages["results"]
ck("실패 시 수집 상태 탭 먼저", rp.nb.index(rp.nb.select()) == 3)
for mode in ("BAD", "GOOD", "ALL"):
    rp.mode_var.set(mode); rp._mode_changed()
ck("투어표 행", len(rp.tree.get_children()) == len(res.tours), f"{len(rp.tree.get_children())} vs {len(res.tours)}")
rp._sort_by("Reviews"); rp._sort_by("Reviews")
rp.star_var.set("5"); rp.refresh_tours()
rp.search_var.set("seoul"); rp.refresh_tours()
ck("검색 필터", all("Seoul" in rp._item_keys[i][1] for i in rp.tree.get_children()))
rp.search_var.set(""); rp.star_var.set("ALL"); rp.refresh_tours()
ck("보고 텍스트(전체)", "전체 요약" in rp._texts[0] and "🏢 [지사: Seoul]" in rp._texts[0])
ck("보고 텍스트(지사별)", set(rp._texts[1]) == {"Seoul", "Busan", "Tokyo"}, list(rp._texts[1]))
rp._copy_report()
ck("클립보드 복사", "전체 요약" in app.root.clipboard_get())
gpt = TMP / "gpt.xlsx"
filedialog.asksaveasfilename = lambda **k: str(gpt)
rp._select_visible()
rp.export_gpt()
ck("GPT Excel", gpt.exists() and load_workbook(gpt).sheetnames[0] == "GPT_READ_ME_FIRST")
from ui.tour_detail import open_tour_detail
before = set(app.root.winfo_children())
area, tour = next(iter(rp._item_keys.values()))
open_tour_detail(app, area, tour)
new = [w for w in app.root.winfo_children() if w not in before]
ck("투어 상세 창", len(new) == 1)
for w in new:
    w.destroy()
app.show("chrome")
app.root.update()
app.root.destroy()

print("\n" + "=" * 66)
print(f"실패 {len(FAIL)}건" if FAIL else "전부 통과")
for x in FAIL:
    print("  -", x)
sys.exit(1 if FAIL else 0)
