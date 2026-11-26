"""메신저에 바로 붙여넣는 텍스트 보고서 (ReviewCrawler_v25 의 '전체 Copy' / '지사 Copy').

지사 → 날짜 → 가이드/투어 순서로 예약별 리뷰 결과를 정리한다.
  ✓ 좋은 리뷰(4~5점)   ▲ 낮은 평점(1~3점)   ✗ 리뷰 없음   · 수집 제외(미지원/오류)
"""
from __future__ import annotations

import pandas as pd

from collectors.config import CHANNEL_DISPLAY, SUPPORTED_CHANNELS

LINE = "=" * 60
WEEKDAY_KR = "월화수목금토일"


def _people(df: pd.DataFrame) -> int:
    if "People" not in df.columns:
        return 0
    return int(pd.to_numeric(df["People"], errors="coerce").fillna(0).sum())


def _team_text(df: pd.DataFrame) -> str:
    p = _people(df)
    return f"{len(df):,}팀" + (f" {p:,}명" if p else "")


def _rating(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df["Rating"], errors="coerce")


def _summary_block(df: pd.DataFrame, title: str) -> list[str]:
    found = df["Review Found"].fillna(False).astype(bool)
    eligible = df[df["Collection Status"].astype(str).eq("SUCCESS")]
    r = _rating(df[found])
    good = int((r >= 4).sum())
    bad = int((r <= 3).sum())
    lines = [LINE, f"📈 {title}", LINE]
    lines.append(f"👥 총 예약: {_team_text(df)}")
    lines.append(f"   └ 리뷰 조회대상(L/KK/GG/TPC/MRT, 수집 성공): {len(eligible):,}팀")
    rate = f"{good / len(eligible) * 100:.1f}%" if len(eligible) else "-"
    lines.append(f"✓ 좋은리뷰(4-5점): {good:,}팀  ({good:,}/{len(eligible):,} · {rate})")
    lines.append(f"▲ 낮은평점(1-3점): {bad:,}팀")
    lines.append(f"⭐ 평균 별점: {r.mean():.2f}점" if len(r) else "⭐ 평균 별점: N/A")
    lines.append("")
    lines.append("[채널별]")
    for ch in SUPPORTED_CHANNELS:
        sub = df[df["Agency"].astype(str).str.upper().eq(ch)]
        if sub.empty:
            continue
        rr = _rating(sub[sub["Review Found"].fillna(False).astype(bool)])
        avg = f" · 평균 {rr.mean():.2f}" if len(rr) else ""
        lines.append(f"  {CHANNEL_DISPLAY.get(ch, ch):<15} 리뷰 {len(rr):>3} / 예약 {len(sub):>3}{avg}")
    others = df[~df["Agency"].astype(str).str.upper().isin(SUPPORTED_CHANNELS)]
    if not others.empty:
        parts = [f"{a} {n}" for a, n in others.groupby("Agency").size().sort_values(ascending=False).items()]
        lines.append(f"  조회 제외 에이전시: {', '.join(parts)}  (개별 확인 필요)")
    return lines


def _mark(row) -> str:
    status = str(row.get("Collection Status", ""))
    if status != "SUCCESS":
        return "·"
    if not bool(row.get("Review Found")):
        return "✗"
    try:
        return "✓" if float(row.get("Rating")) >= 4 else "▲"
    except (TypeError, ValueError):
        return "✗"


def _area_block(df: pd.DataFrame, area: str) -> list[str]:
    sub = df[df["Area"].astype(str).eq(area)]
    found = sub["Review Found"].fillna(False).astype(bool)
    r = _rating(sub[found])
    good = int((r >= 4).sum())
    lines = ["", "#" * 60, f"🏢 [지사: {area}]  예약 {_team_text(sub)} · 리뷰 {int(found.sum())} · 좋은리뷰 {good}"
             + (f" · 평균 {r.mean():.2f}" if len(r) else ""), "#" * 60]
    sub = sub.copy()
    sub["__d"] = pd.to_datetime(sub["Date"], errors="coerce").dt.normalize()
    sub["__g"] = sub.get("Main Guide", pd.Series("", index=sub.index)).fillna("").astype(str).str.strip().replace("", "(미지정)")
    for day, dg in sub.groupby("__d", sort=True):
        lines.append(f"\n  ── {day:%Y-%m-%d} ({WEEKDAY_KR[day.weekday()]}) ──")
        for (guide, tour), tg in dg.groupby(["__g", "Product Normalized"], sort=True):
            tf = tg["Review Found"].fillna(False).astype(bool)
            tr = _rating(tg[tf])
            tgood = int((tr >= 4).sum())
            lines.append(f"  • {guide} / {tour}  ▶ {_team_text(tg)} · 리뷰 {int(tf.sum())} · 좋은리뷰 {tgood}"
                         + (f" · 평균 {tr.mean():.1f}" if len(tr) else ""))
            for _, row in tg.sort_values(["Agency", "Agency Code"]).iterrows():
                mark = _mark(row)
                star = ""
                if mark in ("✓", "▲"):
                    star = f" ★{float(row['Rating']):g}"
                ag = CHANNEL_DISPLAY.get(str(row["Agency"]).upper(), str(row["Agency"]))
                lines.append(f"      {mark} [{ag}] {row['Agency Code']}{star}")
    return lines


def build_report_text(master: pd.DataFrame, start, end, areas) -> tuple[str, dict[str, str]]:
    """(전체 텍스트, {지사: 지사 텍스트})."""
    if master is None or master.empty:
        return "선택 조건에 예약이 없습니다.", {}
    period = f"{pd.Timestamp(start):%Y-%m-%d} ~ {pd.Timestamp(end):%Y-%m-%d}"
    present = [a for a in areas if a in set(master["Area"].astype(str))] or sorted(master["Area"].astype(str).unique())
    full = _summary_block(master, f"전체 요약  [{period} · {', '.join(present)}]")
    per_area: dict[str, str] = {}
    for area in present:
        sub = master[master["Area"].astype(str).eq(area)]
        block = _area_block(master, area)
        full += block
        per_area[area] = "\n".join(_summary_block(sub, f"{area} 요약  [{period}]") + block)
    full += ["", "✓ 좋은리뷰(4-5)  ▲ 낮은평점(1-3)  ✗ 리뷰 없음  · 수집 제외(미지원/오류)"]
    return "\n".join(full), per_area
