"""주단위(월~일) / 월단위(1일~말일) 기간 목록 – ReviewCrawler_v25 의 PFP · Monthly 방식."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

WEEKDAY_KR = "월화수목금토일"
MODE_LABEL = {"week": "주간", "month": "월간", "range": "기간"}


@dataclass(frozen=True)
class Period:
    mode: str              # week / month
    start: pd.Timestamp
    end: pd.Timestamp
    bookings: int
    partial: bool          # 시트에 이 기간 일부 날짜만 있음

    @property
    def label(self) -> str:
        s, e = self.start, self.end
        if self.mode == "week":
            text = (f"{s:%Y-%m-%d} ({WEEKDAY_KR[s.weekday()]}) ~ "
                    f"{e:%Y-%m-%d} ({WEEKDAY_KR[e.weekday()]})")
        else:
            text = f"{s:%Y년 %m월}  ({s:%Y-%m-%d} ~ {e:%Y-%m-%d})"
        text += f"  ·  예약 {self.bookings:,}건"
        if self.partial:
            text += "  ·  시트에 일부 날짜만 있음"
        return text


def list_periods(dates, mode: str, sheet_min=None, sheet_max=None) -> list[Period]:
    """예약이 있는 주/달 목록. 최신이 먼저."""
    d = pd.to_datetime(pd.Series(list(dates)), errors="coerce").dropna().dt.normalize()
    if d.empty:
        return []
    sheet_min = pd.Timestamp(sheet_min).normalize() if sheet_min is not None else d.min()
    sheet_max = pd.Timestamp(sheet_max).normalize() if sheet_max is not None else d.max()
    if mode == "week":
        starts = d - pd.to_timedelta(d.dt.weekday, unit="D")
    elif mode == "month":
        starts = d.dt.to_period("M").dt.to_timestamp()
    else:
        raise ValueError(mode)
    counts = starts.value_counts()
    out = []
    for s in sorted(counts.index, reverse=True):
        s = pd.Timestamp(s).normalize()
        e = s + pd.Timedelta(days=6) if mode == "week" else (s + pd.offsets.MonthEnd(0)).normalize()
        out.append(Period(mode, s, e, int(counts[s]), bool(s < sheet_min or e > sheet_max)))
    return out


def period_kind(start, end) -> str:
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if (e - s).days == 6 and s.weekday() == 0:
        return "week"
    if s.day == 1 and (s.year, s.month) == (e.year, e.month) and (e + pd.Timedelta(days=1)).day == 1:
        return "month"
    return "range"
