# -*- coding: utf-8 -*-
"""주간/월간 보고 시트 3개 시험 (OTA 접속 없이 가짜 수집 결과로).

작업지시서의 테스트 체크리스트를 그대로 확인한다.
"""
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from openpyxl import load_workbook

from core.matcher import build_master_dataset
from core.metrics import build_overall_metrics
from core.scope import build_scope
from export.excel import save_phase1_excel
from export.weekly_report import period_kind

FAIL = []


def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok:
        FAIL.append(n)


def bookings():
    rows = []
    def add(date, area, product, agency, code, guide, people=2):
        rows.append({"Date": pd.Timestamp(date), "Area": area, "Product": product,
                     "Product Normalized": product, "Agency": agency, "Agency Code": code,
                     "Main Guide": guide, "People": people})
    # Seoul, 2026-11-23(월) ~ 11-29(일)
    add("2026-11-23", "Seoul", "DMZ 반일 투어", "L", "L001", "김민준")
    add("2026-11-23", "Seoul", "DMZ 반일 투어", "KK", "K001", "김민준")
    add("2026-11-23", "Seoul", "DMZ 반일 투어", "TPC", "T001", "김민준")
    add("2026-11-23", "Seoul", "DMZ 반일 투어", "ETC", "E001", "김민준")   # 미지원 에이전시
    add("2026-11-24", "Seoul", "DMZ 반일 투어", "L", "L002", "이서연")
    add("2026-11-24", "Seoul", "남이섬 투어", "GG", "G001", "이서연")
    add("2026-11-25", "Seoul", "남이섬 투어", "MRT", "M001", "")           # 가이드 미지정
    add("2026-11-26", "Seoul", "남이섬 투어", "L", "L003", "김민준")
    # Busan
    add("2026-11-23", "Busan", "부산 시티 투어", "L", "L101", "박지훈")
    add("2026-11-23", "Busan", "부산 시티 투어", "KK", "K101", "박지훈")
    # 범위 밖
    add("2026-11-30", "Seoul", "DMZ 반일 투어", "L", "L999", "김민준")
    return pd.DataFrame(rows)


COLLECTED = {
    "L": {"L001": {"rating": "5", "content": "최고였어요", "review_date": "2026-11-24"},
          "L002": {"rating": "5", "content": "", "review_date": "2026-11-25"},
          "L003": {"rating": "2", "content": "늦었어요", "review_date": "2026-11-27"},
          "L101": {"rating": "5", "content": "Great " * 3000, "review_date": "2026-11-24"}},
    "KK": {"K001": {"rating": "3", "content": "보통", "review_date": "2026-11-24"},
           "K101": {"rating": "5", "content": "Good " * 4000, "review_date": "2026-11-25"}},
    "GG": {"G001": {"rating": "4", "content": "nice", "review_date": "2026-11-25"}},
    "TPC": {"T001": {"rating": "5", "content": "좋아요", "review_date": "2026-11-25"}},
    "MRT": {"M001": {"rating": "5", "content": "가이드 없음 리뷰", "review_date": "2026-11-26"}},
}
STATUS = {ch: {"status": "SUCCESS", "count": len(v)} for ch, v in COLLECTED.items()}


def run(areas, start="2026-11-23", end="2026-11-29", collected=COLLECTED):
    df = bookings()
    scope = build_scope(df, start, end, areas=areas)
    master = build_master_dataset(scope.scope_df, collected, STATUS)
    out = Path(tempfile.mkdtemp()) / "Review Analyzer test.xlsx"
    save_phase1_excel(str(out), master=master, overall=build_overall_metrics(master),
                      tours=pd.DataFrame(), areas=pd.DataFrame(), channels=pd.DataFrame(),
                      unsupported=pd.DataFrame(), collection_status=STATUS,
                      start_date=scope.start_date, end_date=scope.end_date,
                      selected_areas=scope.selected_areas)
    return load_workbook(out), master


def find_row(ws, text, col=1):
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, col).value == text:
            return r
    return None


print("=" * 66); print("[1] 한 지사 · 주간 (Seoul)"); print("=" * 66)
wb, master = run(["Seoul"])
ck("시트 순서: 새 시트 3개가 맨 앞", wb.sheetnames[:3] == ["지사 요약", "성과제", "투어별 리뷰 총정리"], wb.sheetnames)
ck("기존 7개 시트 유지", wb.sheetnames[3:] == ["Overall", "Tour Metrics", "Area Metrics", "Channel Metrics",
                                         "Unsupported", "Collection Status", "Master"], wb.sheetnames[3:])
ck("열면 지사 요약 탭 선택", wb.active.title == "지사 요약")
s = wb["지사 요약"]
ck("기간 표시", "2026.11.23 ~ 2026.11.29" in str(s["A2"].value), s["A2"].value)
ck("주간 라벨", s.cell(5, 1).value == "이번 주 투어", s.cell(5, 1).value)
kpi = [s.cell(6, c).value for c in range(1, 6)]
overall = wb["Overall"]
hdr = [c.value for c in overall[1]]
ov = {h: overall.cell(2, i + 1).value for i, h in enumerate(hdr)}
ck("예약 = Overall Total Booking", kpi[1] == ov["Total Booking"], f"{kpi[1]} vs {ov['Total Booking']}")
ck("총 리뷰 = Overall Reviews", kpi[4] == ov["Reviews"], f"{kpi[4]} vs {ov['Reviews']}")
ck("투어 = 날짜·투어·가이드 조합", kpi[0] == 5, kpi)
ck("에이전시 수 (미지원 포함)", kpi[2] == 6, kpi)
ck("가이드 수 (빈 값 제외)", kpi[3] == 2, kpi)
r_tot = find_row(s, "합계")
ck("투어 표 합계 = 핵심 숫자", [s.cell(r_tot, c).value for c in (2, 3, 4)] == [kpi[0], kpi[1], kpi[4]],
   [s.cell(r_tot, c).value for c in (2, 3, 4)])

p = wb["성과제"]
hdr4 = [p.cell(4, c).value for c in range(1, 11)]
ck("성과제 열 (투어 이름 → 투어 날짜 · 팀 · 인원 · 리뷰율)", hdr4 == [
    "순위", "가이드 이름", "투어명", "투어 날짜", "팀 (예약)", "인원", "5점 개수", "3점 이하 (제외)",
    "실제 지급 수량", "리뷰율"], hdr4)
rows = []
r = 5
while p.cell(r, 1).value not in (None, "합계"):
    rows.append([p.cell(r, c).value for c in range(1, 11)]); r += 1
print("   성과제:", rows)
fives = [x[6] for x in rows]
ck("5점 0개인 줄 없음", all(f >= 1 for f in fives))
ck("5점 개수 내림차순", fives == sorted(fives, reverse=True))
total_five = p.cell(r, 7).value
ck("5점 합계 = Overall 5 Star − 미지정", total_five == ov["5 Star"] - 1, f"{total_five} vs {ov['5 Star']}-1")
ck("김민준 DMZ 11/23: 4팀 8명 · 5점 2 · −1 · 지급 1 · 리뷰율 100%",
   rows[0][1:] == ["김민준", "DMZ 반일 투어", "2026-11-23 (월)", 4, 8, 2, -1, 1, 1.0], rows[0])
ck("이서연 DMZ 11/24: 1팀 2명 · 5점 1", rows[1][1:7] == ["이서연", "DMZ 반일 투어", "2026-11-24 (화)", 1, 2, 1], rows[1])
ck("5점 없는 날(김민준 남이섬 11/26)은 제외", len(rows) == 2, len(rows))
ck("합계: 팀 5 · 인원 10 · 지급 2 · 리뷰율 100%",
   [p.cell(r, c).value for c in (5, 6, 9, 10)] == [5, 10, 2, 1.0], [p.cell(r, c).value for c in range(5, 11)])
ck("리뷰율 % 서식", p.cell(5, 10).number_format == "0.0%")
ck("미지정 안내문", any("가이드 미지정 5점 리뷰 1개는 제외됨" in str(p.cell(i, 1).value or "")
                     for i in range(1, p.max_row + 1)))
ck("3점 이하 빨간 글씨", p.cell(5, 8).font.color.rgb.endswith("A12A12"))

t = wb["투어별 리뷰 총정리"]
bvals = [t.cell(i, 2).value for i in range(6, t.max_row + 1) if t.cell(i, 2).value]
n_reviews = sum(sum(1 for line in v.split("\n")[1:] if line[:1].isdigit()) for v in bvals)
ck("탭3 리뷰 개수 합계 = 총 리뷰", n_reviews == kpi[4], f"{n_reviews} vs {kpi[4]}")
ck("B열 첫 줄 맥락", bvals[0].startswith("[DMZ 반일 투어 / 2026-11-23 / 가이드 김민준]"), bvals[0][:50])
ck("별점 내림차순 · 에이전시 이름", "1) ★5 · Klook — 최고였어요" in bvals[0] and "★3 · KKday" in bvals[0], bvals[0])
ck("본문 없음 표시", any("(본문 없음)" in v for v in bvals))
ck("가이드 미지정 표시", any("가이드 (미지정)" in v for v in bvals))
ck("줄바꿈 켜짐", t.cell(6, 2).alignment.wrap_text)

print("\n" + "=" * 66); print("[2] 지사 2개 (Seoul + Busan)"); print("=" * 66)
wb, master = run(["Seoul", "Busan"])
s = wb["지사 요약"]
ck("Area 구분 줄 (선택 순서: 전체/Seoul/Busan)", [s.cell(r, 1).value for r in (4, 8, 12)] == ["전체", "Seoul", "Busan"],
   [s.cell(r, 1).value for r in (4, 8, 12)])
hdr_row = find_row(s, "Area")
ck("투어 표 Area 열", hdr_row is not None)
ck("성과제 Area 열", wb["성과제"].cell(4, 2).value == "Area")
t = wb["투어별 리뷰 총정리"]
long_cells = [t.cell(i, 2).value for i in range(6, t.max_row + 1) if "부산 시티" in str(t.cell(i, 2).value)]
ck("모든 셀 32,767자 이하", all(len(str(t.cell(i, 2).value or "")) <= 32767 for i in range(1, t.max_row + 1)))
ck("32,767자 넘는 묶음은 (이어서 2/2)로 분할", any("(이어서 2/2)" in str(v) for v in long_cells), len(long_cells))
ck("분할돼도 리뷰 빠짐없음", sum(str(v).count(" · ") for v in long_cells) == 2)
ck("긴 리뷰도 잘리지 않음(행 높이 ≤409)", all((t.row_dimensions[i].height or 0) <= 409 for i in range(6, t.max_row + 1)))

print("\n" + "=" * 66); print("[3] 리뷰 0개"); print("=" * 66)
wb, _ = run(["Seoul"], collected={})
ck("빈 시트 3개 + 안내", "리뷰 없음" in str(wb["성과제"].cell(5, 1).value)
   and "리뷰 없음" in str(wb["투어별 리뷰 총정리"].cell(6, 1).value), wb["성과제"].cell(5, 1).value)

print("\n" + "=" * 66); print("[4] 기간 종류 판정"); print("=" * 66)
ck("월~일 = 주간", period_kind("2026-11-23", "2026-11-29") == "week")
ck("1일~말일 = 월간", period_kind("2026-11-01", "2026-11-30") == "month")
ck("2월 월간", period_kind("2026-02-01", "2026-02-28") == "month")
ck("그 외 = 기간", period_kind("2026-11-02", "2026-11-20") == "range")

print("\n" + "=" * 66)
print(f"실패 {len(FAIL)}건" if FAIL else "전부 통과")
for x in FAIL:
    print("  -", x)
sys.exit(1 if FAIL else 0)
