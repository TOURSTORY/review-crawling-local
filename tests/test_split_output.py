# -*- coding: utf-8 -*-
"""국가별 · 지역(Area)별 결과 Excel 나누기 시험 (가짜 수집기)."""
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from openpyxl import load_workbook

from core import pipeline
from core.browser_profiles import BrowserProfileManager

FAIL = []


def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok:
        FAIL.append(n)


TMP = Path(tempfile.mkdtemp())
rows = []
for d in pd.date_range("2026-11-16", "2026-11-22"):
    for area, ag in [("Seoul", "L"), ("Seoul", "KK"), ("Busan", "L"), ("Tokyo", "L"), ("Osaka", "GG"),
                     ("Sydney", "L"), ("Seoul", "VI")]:
        rows.append({"Date": d, "Agency": ag, "Agency Code": f"{ag}{d:%m%d}{area[:3]}", "Area": area,
                     "Product": f"{area} Tour", "Main Guide": f"G-{area}", "People": 2})
SRC = pd.DataFrame(rows)
XL = TMP / "bookings.xlsx"
SRC.to_excel(XL, index=False)


class FakeBrowser:
    def __init__(self, debug_address=""):
        pass

    def connect(self):
        pass


def fake(ch):
    def collect(ctx, a, b):
        sub = SRC[(SRC.Agency == ch) & (SRC.Date >= a) & (SRC.Date <= b)]
        return {c: {"rating": str([5, 4, 2][i % 3]), "content": f"r {c}", "review_date": a}
                for i, c in enumerate(sub["Agency Code"])}
    return collect


pipeline.BrowserSession = FakeBrowser
pipeline.COLLECTORS = {ch: fake(ch) for ch in pipeline.COLLECTORS}
mgr = BrowserProfileManager(config_path=TMP / "routing.json")
mgr.ensure_profile = lambda *a, **k: (False, True)
AREAS = ["Seoul", "Busan", "Tokyo", "Osaka", "Sydney"]


def run(split, combined=True, areas=AREAS, out=None):
    return pipeline.run_phase1(str(XL), "2026-11-16", "2026-11-22", areas=areas, browser_manager=mgr,
                               log=lambda m: None, output_dir=str(out or TMP / split), split_by=split,
                               include_combined=combined)


def overall(path):
    ws = load_workbook(path)["Overall"]
    hdr = [c.value for c in ws[1]]
    return {h: ws.cell(2, i + 1).value for i, h in enumerate(hdr)}


def master_areas(path):
    return set(pd.read_excel(path, sheet_name="Master")["Area"])


print("[1] 국가별 (한국 · 일본 · 호주) + 통합")
r = run("country")
labels = [lab for lab, _ in r.output_files]
ck("통합 + 국가 3개", labels[0] == "통합" and len(labels) == 4, labels)
names = [Path(p).name for _, p in r.output_files[1:]]
ck("파일 이름에 국가", [n.split()[-1] for n in names] == ["Korea.xlsx", "Japan.xlsx", "Australia.xlsx"], names)
ck("나눈 파일은 하위 폴더", all(Path(p).parent.name.endswith("(국가별)") for _, p in r.output_files[1:]),
   Path(r.output_files[1][1]).parent.name)
files = dict(r.output_files)
korea = next(p for lab, p in r.output_files if lab.startswith("한국"))
ck("한국 파일 = Seoul, Busan 만", master_areas(korea) == {"Seoul", "Busan"}, master_areas(korea))
tot = overall(files["통합"])
parts = [overall(p) for lab, p in r.output_files[1:]]
for key in ("Total Booking", "Reviews", "Good", "Bad", "5 Star", "Unsupported"):
    ck(f"국가별 {key} 합 = 통합", sum(p[key] for p in parts) == tot[key], f"{[p[key] for p in parts]} vs {tot[key]}")
wb = load_workbook(korea)
ck("한국 파일 맨 앞 3시트", wb.sheetnames[:3] == ["지사 요약", "성과제", "투어별 리뷰 총정리"])
ck("한국 지사 요약 Area 표시", "Seoul, Busan" in str(wb["지사 요약"]["A2"].value), wb["지사 요약"]["A2"].value)
st = pd.read_excel(korea, sheet_name="Collection Status")
ck("한국 수집 상태 = 한국 OTA 만", set(st["Agency"]) == {"L", "KK"}, set(st["Agency"]))
ck("한국 수집 상태 Area 한국만", all(set(str(a).split(", ")) <= {"Seoul", "Busan"} for a in st["Area"]))
ck("한국 미지원(VI) 포함", overall(korea)["Unsupported"] == 7, overall(korea)["Unsupported"])

print("\n[2] 지역(Area)별, 통합 없이")
r = run("area", combined=False)
labels = [lab for lab, _ in r.output_files]
ck("Area 5개 · 통합 없음", labels == ["Busan", "Seoul", "Osaka", "Tokyo", "Sydney"], labels)
ck("파일 이름 국가-지역", Path(r.output_files[0][1]).name.endswith("Korea-Busan.xlsx"), Path(r.output_files[0][1]).name)
ck("각 파일 Area 하나", all(master_areas(p) == {lab} for lab, p in r.output_files))
ck("결과 대표 파일 = 첫 파일", r.output_path == r.output_files[0][1])
ws = load_workbook(dict(r.output_files)["Seoul"])["지사 요약"]
ck("Seoul 파일 KPI 예약 21", ws.cell(6, 2).value == 21 or ws.cell(6, 1).value == 21,
   [ws.cell(6, c).value for c in range(1, 6)])

print("\n[3] 한 국가만 고르면 나눌 필요 없음 → 1개")
r = run("country", areas=["Seoul", "Busan"], out=TMP / "one")
ck("Excel 1개", [lab for lab, _ in r.output_files] == ["통합"], r.output_files)

print("\n[4] 통합 1개 (기본)")
r = run("none", out=TMP / "none")
ck("Excel 1개", len(r.output_files) == 1 and Path(r.output_path).name.endswith("Korea_Japan_Australia.xlsx"),
   Path(r.output_path).name)

print("\n" + ("전부 통과" if not FAIL else f"실패 {len(FAIL)}건"))
sys.exit(1 if FAIL else 0)
