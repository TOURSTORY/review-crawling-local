"""주간 / 월간 보고용 시트 3개 (비개발자용).

결과 Excel 맨 앞에 붙는다.
  1. 지사 요약           : 핵심 숫자 5개 + 투어별 예약 수
  2. 성과제              : 가이드 + 투어별 5점 리뷰 수 · 실제 지급 수량
  3. 투어별 리뷰 총정리   : 투어·날짜·가이드별 리뷰를 셀 하나에 모음 (AI 붙여넣기용)

데이터는 run_phase1() 의 master DataFrame (예약 1행 = 1줄) 만 사용한다.
날짜 기준은 예약 엑셀의 투어일(Date). 리뷰 작성일은 집계에 쓰지 않는다.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from collectors.config import CHANNEL_DISPLAY
from core.periods import period_kind

try:  # openpyxl >= 3.1
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
except Exception:  # pragma: no cover
    CellRichText = None


SHEET_SUMMARY = "지사 요약"
SHEET_INCENTIVE = "성과제"
SHEET_TOUR_REVIEWS = "투어별 리뷰 총정리"
NEW_SHEETS = (SHEET_SUMMARY, SHEET_INCENTIVE, SHEET_TOUR_REVIEWS)

UNASSIGNED_GUIDE = "(미지정)"
EMPTY_REVIEW = "(본문 없음)"
EXCEL_CELL_LIMIT = 32767

# 투어 이름 → 약칭 (선택). 파일이 없으면 투어 이름을 그대로 쓴다.
SHORT_NAME_FILE = Path(__file__).resolve().parents[1] / "data" / "tour_short_names.csv"

FONT_NAME = "맑은 고딕"
TAB_COLOR = "107C41"
GREEN = "107C41"
ORANGE = "E8890C"
HEADER_FILL = PatternFill("solid", start_color="E8F1EC", end_color="E8F1EC")
TOTAL_FILL = PatternFill("solid", start_color="F2F2F2", end_color="F2F2F2")
PAY_FILL = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")
INFO_FILL = PatternFill("solid", start_color="F7FAF8", end_color="F7FAF8")
THIN = Side(style="thin", color="BFBFBF")
THICK = Side(style="medium", color="595959")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WEEKDAY_KR = "월화수목금토일"


# ----------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------
def _font(size=11, bold=False, color="000000"):
    return Font(name=FONT_NAME, size=size, bold=bold, color=color)


def _put(ws, row, col, value, *, bold=False, size=11, color="000000", fill=None,
         align=None, border=True, number_format=None, wrap=False, valign="center"):
    if hasattr(value, "item") and not isinstance(value, str):  # numpy scalar → python
        value = value.item()
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = _font(size, bold, color)
    if fill is not None:
        cell.fill = fill
    if align is None:
        align = "right" if isinstance(value, (int, float)) and not isinstance(value, bool) else "left"
    cell.alignment = Alignment(horizontal=align, vertical=valign, wrap_text=wrap)
    if border:
        cell.border = BORDER
    if number_format:
        cell.number_format = number_format
    return cell


def _header_row(ws, row, headers, start_col=1):
    for i, h in enumerate(headers):
        _put(ws, row, start_col + i, h, bold=True, fill=HEADER_FILL, align="center")


def _ymd(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y.%m.%d")


def _title_lines(ws, title, start, end, areas, width_cols):
    _put(ws, 1, 1, title, bold=True, size=16, border=False)
    _put(ws, 2, 1, f"기간: {_ymd(start)} ~ {_ymd(end)} · Area: {', '.join(areas) or '-'}",
         color="595959", border=False)
    ws.row_dimensions[1].height = 26
    ws.sheet_properties.tabColor = TAB_COLOR


def _guide(v) -> str:
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    return s if s and s.lower() not in {"nan", "none"} else UNASSIGNED_GUIDE


def _star(v) -> str:
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(v)


def load_short_names(path: Path = SHORT_NAME_FILE) -> dict[str, str]:
    """data/tour_short_names.csv (열: 투어 이름, 약칭) → {투어 이름: 약칭}."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    if row[0].strip() in {"투어 이름", "Tour", "Product"}:
                        continue
                    out[re.sub(r"\s+", " ", row[0].strip())] = row[1].strip()
    except Exception:
        return {}
    return out


def _prepare(master: pd.DataFrame) -> pd.DataFrame:
    df = master.copy()
    if "Product Normalized" not in df.columns:
        df["Product Normalized"] = df.get("Product", "")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df["__guide"] = df["Main Guide"].map(_guide) if "Main Guide" in df.columns else UNASSIGNED_GUIDE
    df["__tour"] = df["Product Normalized"].fillna("").astype(str)
    df["__area"] = df["Area"].fillna("").astype(str)
    df["__found"] = df["Review Found"].fillna(False).astype(bool)
    df["__rating"] = pd.to_numeric(df["Rating"], errors="coerce")
    return df


def _runs(df: pd.DataFrame) -> pd.DataFrame:
    """'투어 1건' = 날짜 · Area · 투어 · 가이드가 같은 조합."""
    return df[["Date", "__area", "__tour", "__guide"]].drop_duplicates()


# ----------------------------------------------------------------------
# Tab 1. 지사 요약
# ----------------------------------------------------------------------
KPI_SPEC = [
    # key, unit, band color
    ("tours", "건", GREEN),
    ("bookings", "개", GREEN),
    ("agencies", "곳", GREEN),
    ("guides", "명", GREEN),
    ("reviews", "개", ORANGE),
]


def summary_kpis(df: pd.DataFrame) -> dict[str, int]:
    guides = df.loc[df["__guide"] != UNASSIGNED_GUIDE, "__guide"]
    return {
        "tours": int(len(_runs(df))),
        "bookings": int(len(df)),
        "agencies": int(df["Agency"].nunique()),
        "guides": int(guides.nunique()),
        "reviews": int(df["__found"].sum()),
    }


def tour_booking_table(df: pd.DataFrame, multi_area: bool, area_order=None) -> pd.DataFrame:
    keys = ["__area", "__tour"] if multi_area else ["__tour"]
    rows = []
    for key, g in df.groupby(keys, dropna=False, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(keys, key))
        row["runs"] = int(len(_runs(g)))
        row["bookings"] = int(len(g))
        row["reviews"] = int(g["__found"].sum())
        rows.append(row)
    out = pd.DataFrame(rows, columns=keys + ["runs", "bookings", "reviews"])
    if out.empty:
        return out
    rank = {a: i for i, a in enumerate(area_order or [])}
    out["__arank"] = out["__area"].map(lambda a: rank.get(a, len(rank))) if multi_area else 0
    sort_cols = (["__arank", "__area"] if multi_area else []) + ["bookings", "__tour"]
    asc = ([True, True] if multi_area else []) + [False, True]
    return out.sort_values(sort_cols, ascending=asc).drop(columns="__arank").reset_index(drop=True)


def write_summary_sheet(ws, df, start, end, areas, kind):
    multi = len(areas) > 1
    tour_label = {"week": "이번 주 투어", "month": "이번 달 투어"}.get(kind, "기간 내 투어")
    labels = [tour_label, "예약", "에이전시", "가이드", "총 리뷰"]
    title = {"week": "지사 요약 (주간)", "month": "지사 요약 (월간)"}.get(kind, "지사 요약")
    _title_lines(ws, title, start, end, areas, 6)

    c0 = 2 if multi else 1  # KPI 시작 열
    row = 4
    blocks = [("전체", df)] + ([(a, df[df["__area"] == a]) for a in areas] if multi else [])
    for name, sub in blocks:
        k = summary_kpis(sub)
        if multi:
            ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=1)
            _put(ws, row, 1, name, bold=True, align="center", fill=HEADER_FILL)
        for i, ((key, unit, band), label) in enumerate(zip(KPI_SPEC, labels)):
            col = c0 + i
            band_fill = PatternFill("solid", start_color=band, end_color=band)
            _put(ws, row, col, None, fill=band_fill, border=False)
            _put(ws, row + 1, col, label, color="7F7F7F", align="center", border=False)
            _put(ws, row + 2, col, k[key], bold=True, size=24, align="center", border=False,
                 number_format=f'#,##0"{unit}"')
        ws.row_dimensions[row].height = 5
        ws.row_dimensions[row + 1].height = 18
        ws.row_dimensions[row + 2].height = 36
        row += 4

    row += 1
    _put(ws, row, 1, "투어별 예약 수", bold=True, size=12, border=False)
    row += 1
    table = tour_booking_table(df, multi, areas)
    headers = (["Area"] if multi else []) + ["투어 이름", "운행 횟수", "예약 수", "리뷰 수"]
    _header_row(ws, row, headers)
    row += 1
    if table.empty:
        _put(ws, row, 1, "선택 기간에 예약이 없습니다.", color="7F7F7F", border=False)
    for _, r in table.iterrows():
        vals = ([r["__area"]] if multi else []) + [r["__tour"], r["runs"], r["bookings"], r["reviews"]]
        for i, v in enumerate(vals):
            _put(ws, row, 1 + i, v, number_format=None if isinstance(v, str) else "#,##0")
        row += 1
    totals = summary_kpis(df)
    tot_vals = (["합계"] if multi else []) + (["" if multi else "합계"]) + [
        totals["tours"], totals["bookings"], totals["reviews"]]
    for i, v in enumerate(tot_vals):
        _put(ws, row, 1 + i, v, bold=True, fill=TOTAL_FILL, number_format="#,##0")

    widths = ([16] if multi else []) + [52, 16, 16, 16, 16, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    # KPI 칸이 좁은 표 열에 걸리면 숫자가 잘린다 → 투어 이름 열 외에는 최소 16
    for i in range(c0, c0 + 5):
        letter = get_column_letter(i)
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, 16)


# ----------------------------------------------------------------------
# Tab 2. 성과제
# ----------------------------------------------------------------------
def incentive_table(df: pd.DataFrame, multi_area: bool) -> tuple[pd.DataFrame, int]:
    """(표, 가이드 미지정 5점 리뷰 수).

    한 줄 = 가이드 + 투어 + 투어 날짜 (Area 가 여럿이면 Area 도).
      teams      그날 그 가이드 투어의 예약 건수 (미지원 에이전시 포함)
      people     총인원 (People 합)
      eligible   리뷰 수집 대상 팀 (지원 OTA · 수집 성공) = 리뷰율 분모
      reviews    리뷰 수 · five 5점 · low 3점 이하 · pay = max(five - low, 0)
    """
    unassigned_five = int((df["__found"] & (df["__guide"] == UNASSIGNED_GUIDE) & (df["__rating"] == 5)).sum())
    base = df[df["__guide"] != UNASSIGNED_GUIDE]
    keys = (["__area"] if multi_area else []) + ["__guide", "__tour", "Date"]
    cols = keys + ["teams", "people", "eligible", "reviews", "five", "low", "pay", "rate"]
    has_people = "People" in base.columns
    rows = []
    for key, g in base.groupby(keys, dropna=False, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        rev = g[g["__found"]]
        five = int((rev["__rating"] == 5).sum())
        if five < 1:
            continue
        low = int((rev["__rating"] <= 3).sum())
        eligible = int(g["Collection Status"].astype(str).eq("SUCCESS").sum()) if "Collection Status" in g else len(g)
        row = dict(zip(keys, key))
        row.update(
            teams=int(len(g)),
            people=int(pd.to_numeric(g["People"], errors="coerce").fillna(0).sum()) if has_people else None,
            eligible=eligible, reviews=int(len(rev)), five=five, low=low, pay=max(five - low, 0),
            rate=(len(rev) / eligible) if eligible else None,
        )
        rows.append(row)
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out.assign(rank=pd.Series(dtype=int)), unassigned_five
    out = out.sort_values(["five", "pay", "Date", "__guide"],
                          ascending=[False, False, True, True]).reset_index(drop=True)
    out["rank"] = out["five"].rank(method="min", ascending=False).astype(int)
    return out, unassigned_five


def _tour_date(ts) -> str:
    t = pd.Timestamp(ts)
    return f"{t:%Y-%m-%d} ({WEEKDAY_KR[t.weekday()]})" if pd.notna(t) else ""


def write_incentive_sheet(ws, df, start, end, areas, kind, short_names):
    multi = len(areas) > 1
    title = {"week": "성과제 (주간)", "month": "성과제 (월간)"}.get(kind, "성과제")
    _title_lines(ws, title, start, end, areas, 10)
    table, unassigned_five = incentive_table(df, multi)

    row = 4
    headers = ["순위"] + (["Area"] if multi else []) + [
        "가이드 이름", "투어명", "투어 날짜", "팀 (예약)", "인원", "5점 개수", "3점 이하 (제외)",
        "실제 지급 수량", "리뷰율"]
    _header_row(ws, row, headers)
    row += 1
    if table.empty:
        _put(ws, row, 1, "리뷰 없음 · 선택 기간에 5점 리뷰를 받은 가이드가 없습니다.",
             color="7F7F7F", border=False)
        row += 1
    for _, r in table.iterrows():
        c = 1
        _put(ws, row, c, int(r["rank"]), align="center"); c += 1
        if multi:
            _put(ws, row, c, r["__area"]); c += 1
        _put(ws, row, c, r["__guide"], bold=True); c += 1
        _put(ws, row, c, short_names.get(r["__tour"], r["__tour"])); c += 1
        _put(ws, row, c, _tour_date(r["Date"]), align="center"); c += 1
        _put(ws, row, c, int(r["teams"]), number_format='#,##0"팀"'); c += 1
        people = r["people"]
        _put(ws, row, c, int(people) if people is not None and pd.notna(people) else "-",
             number_format='#,##0"명"'); c += 1
        _put(ws, row, c, int(r["five"])); c += 1
        _put(ws, row, c, -int(r["low"]) if r["low"] else 0, color="A12A12"); c += 1
        _put(ws, row, c, int(r["pay"]), bold=True, fill=PAY_FILL); c += 1
        rate = r["rate"]
        _put(ws, row, c, float(rate) if rate is not None and pd.notna(rate) else "-",
             number_format="0.0%", align="right")
        row += 1
    if not table.empty:
        n_lead = 1 + (1 if multi else 0) + 3
        for c in range(1, n_lead + 1):
            _put(ws, row, c, "합계" if c == 1 else "", bold=True, fill=TOTAL_FILL, align="center" if c == 1 else None)
        c = n_lead + 1
        _put(ws, row, c, int(table["teams"].sum()), bold=True, fill=TOTAL_FILL, number_format='#,##0"팀"'); c += 1
        ppl = pd.to_numeric(table["people"], errors="coerce")
        _put(ws, row, c, int(ppl.sum()) if ppl.notna().any() else "-", bold=True, fill=TOTAL_FILL,
             number_format='#,##0"명"'); c += 1
        _put(ws, row, c, int(table["five"].sum()), bold=True, fill=TOTAL_FILL); c += 1
        low_sum = int(table["low"].sum())
        _put(ws, row, c, -low_sum if low_sum else 0, bold=True, fill=TOTAL_FILL, color="A12A12"); c += 1
        _put(ws, row, c, int(table["pay"].sum()), bold=True, fill=PAY_FILL); c += 1
        elig = int(table["eligible"].sum())
        _put(ws, row, c, (int(table["reviews"].sum()) / elig) if elig else "-", bold=True, fill=TOTAL_FILL,
             number_format="0.0%", align="right")
        row += 1

    row += 1
    notes = [
        "※ 5점 리뷰를 받은 가이드만 표시 · 실제 지급 = 5점 − 3점 이하",
        "※ 한 줄 = 가이드 + 투어 + 투어 날짜. 팀 · 인원은 그날 그 가이드 투어의 전체 예약(미지원 에이전시 포함)",
        "※ 리뷰율 = 리뷰 수 ÷ 리뷰 수집 대상 팀 (Klook · KKday · GYG · Trip.com · MRT 중 수집 성공한 예약)",
    ]
    if unassigned_five:
        notes.append(f"※ 가이드 미지정 5점 리뷰 {unassigned_five}개는 제외됨")
    for n in notes:
        _put(ws, row, 1, n, color="595959", border=False)
        row += 1

    widths = [8] + ([14] if multi else []) + [20, 30, 16, 11, 10, 11, 15, 15, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"


# ----------------------------------------------------------------------
# Tab 3. 투어별 리뷰 총정리
# ----------------------------------------------------------------------
def _agency_name(code) -> str:
    c = str(code or "").strip().upper()
    return CHANNEL_DISPLAY.get(c, c or "-")


def _date_kr(ts) -> str:
    t = pd.Timestamp(ts)
    return f"{t.strftime('%Y.%m.%d')} ({WEEKDAY_KR[t.weekday()]})"


def tour_review_groups(df: pd.DataFrame, multi_area: bool) -> list[dict]:
    rev = df[df["__found"]].copy()
    if rev.empty:
        return []
    rev["__agname"] = rev["Agency"].map(_agency_name)
    keys = (["__area"] if multi_area else []) + ["__tour", "Date", "__guide"]
    groups = []
    for key, g in rev.groupby(keys, dropna=False, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        info = dict(zip(keys, key))
        g = g.sort_values(["__rating", "__agname"], ascending=[False, True])
        items = []
        for _, r in g.iterrows():
            text = str(r.get("Review Text") or "").strip()
            if not text or text.lower() in {"nan", "<na>", "none"}:
                text = EMPTY_REVIEW
            items.append((_star(r["__rating"]), r["__agname"], text))
        info["items"] = items
        info["avg"] = float(g["__rating"].mean())
        groups.append(info)
    sort_key = lambda x: ((x.get("__area", ""),) if multi_area else ()) + (
        x["__tour"], pd.Timestamp(x["Date"]), x["__guide"])
    return sorted(groups, key=sort_key)


def review_text_chunks(group: dict) -> list[str]:
    """B열 텍스트. 32,767자를 넘으면 여러 조각으로 나눈다."""
    date_iso = pd.Timestamp(group["Date"]).strftime("%Y-%m-%d")
    head = f"[{group['__tour']} / {date_iso} / 가이드 {group['__guide']}]"
    lines = [f"{i}) ★{s} · {ag} — {t}" for i, (s, ag, t) in enumerate(group["items"], start=1)]
    limit = EXCEL_CELL_LIMIT - 40
    chunks, cur = [], head
    for line in lines:
        if len(line) > limit - len(head) - 1:
            line = line[: limit - len(head) - 2] + "…"
        if len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = head
        cur += "\n" + line
    chunks.append(cur)
    if len(chunks) > 1:
        n = len(chunks)
        chunks = [c.replace(head, f"{head} (이어서 {i}/{n})", 1) if i > 1 else c
                  for i, c in enumerate(chunks, start=1)]
    return chunks


def _wrapped_lines(text: str, width_chars: int) -> int:
    total = 0
    for line in text.split("\n"):
        w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in line)
        total += max(1, -(-w // width_chars))
    return total


def _info_value(group: dict, part: str):
    tour = group["__tour"]
    rest = (
        (f"Area {group['__area']}\n" if "__area" in group else "")
        + f"날짜 {_date_kr(group['Date'])}\n"
        + f"가이드 {group['__guide']}\n"
        + f"리뷰 {len(group['items'])}건 · 평균 ★ {group['avg']:.1f}"
        + (f"\n{part}" if part else "")
    )
    if CellRichText is not None:
        try:
            return CellRichText(
                TextBlock(InlineFont(rFont=FONT_NAME, b=True, sz=11), tour + "\n"),
                TextBlock(InlineFont(rFont=FONT_NAME, sz=11), rest),
            )
        except Exception:
            pass
    return tour + "\n" + rest


def write_tour_review_sheet(ws, df, start, end, areas, kind):
    multi = len(areas) > 1
    _title_lines(ws, "투어별 리뷰 총정리 (AI 분석용)", start, end, areas, 2)
    _put(ws, 3, 1, "오른쪽 B열 셀 하나를 복사해 AI에 붙여넣으면 됩니다. 첫 줄에 투어 / 날짜 / 가이드가 들어 있습니다.",
         color="595959", border=False)
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 100
    row = 5
    _header_row(ws, row, ["투어 정보", "리뷰 전체 (복붙용)"])
    row += 1
    groups = tour_review_groups(df, multi)
    if not groups:
        _put(ws, row, 1, "리뷰 없음 · 선택 기간에 수집된 리뷰가 없습니다.", color="7F7F7F", border=False)
        ws.freeze_panes = "A6"
        return
    for g in groups:
        chunks = review_text_chunks(g)
        for i, chunk in enumerate(chunks, start=1):
            part = f"(이어서 {i}/{len(chunks)})" if len(chunks) > 1 and i > 1 else ""
            a = ws.cell(row=row, column=1, value=_info_value(g, part))
            a.font = _font()
            a.fill = INFO_FILL
            a.alignment = Alignment(wrap_text=True, vertical="top")
            b = ws.cell(row=row, column=2, value=chunk)
            b.font = _font()
            b.alignment = Alignment(wrap_text=True, vertical="top")
            last = i == len(chunks)
            bottom = THICK if last else THIN
            for c in (a, b):
                c.border = Border(left=THIN, right=THIN, top=THIN, bottom=bottom)
            lines = max(_wrapped_lines(chunk, 105), 5 if multi else 4)
            ws.row_dimensions[row].height = min(409, lines * 15 + 4)
            row += 1
    ws.freeze_panes = "A6"


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------
def add_report_sheets(wb, master: pd.DataFrame, start=None, end=None, areas=None) -> None:
    """워크북 맨 앞에 새 시트 3개를 만들고 '지사 요약' 을 선택 상태로 둔다."""
    df = _prepare(master)
    if start is None:
        start = df["Date"].min()
    if end is None:
        end = df["Date"].max()
    if areas is None:
        areas = sorted(df["__area"].dropna().unique().tolist())
    areas = [str(a) for a in areas if str(a) in set(df["__area"])] or [str(a) for a in areas]
    kind = period_kind(start, end)
    short_names = load_short_names()

    for name in NEW_SHEETS:
        if name in wb.sheetnames:
            del wb[name]
    ws1 = wb.create_sheet(SHEET_SUMMARY, 0)
    ws2 = wb.create_sheet(SHEET_INCENTIVE, 1)
    ws3 = wb.create_sheet(SHEET_TOUR_REVIEWS, 2)
    write_summary_sheet(ws1, df, start, end, areas, kind)
    write_incentive_sheet(ws2, df, start, end, areas, kind, short_names)
    write_tour_review_sheet(ws3, df, start, end, areas, kind)

    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = False
    wb.active = 0
    ws1.sheet_view.tabSelected = True
