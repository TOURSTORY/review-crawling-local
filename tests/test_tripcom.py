# -*- coding: utf-8 -*-
"""Trip.com/Ctrip 수집기 시험 (가짜 브라우저).

실측(2026-11-25): vbooking 로그인이 풀리면 HTTP 200 + ResponseStatus.Ack=Failure,
'B端用户登录态获取失败' 만 온다. 예전 수집기는 이것을 '리뷰 0건 SUCCESS' 로 보고했다.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from collectors import tripcom as tpc
from collectors.base import CollectorContext

FAIL = []
tpc.RETRY_WAITS = (0, 0)


def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok:
        FAIL.append(n)


class Fake:
    def __init__(self, pages, cap=True):
        self.pages, self.calls = list(pages), 0
        self.cap = {"url": "/x/listOrderComments", "headers": {}, "body": "{}"} if cap else None

    def capture_request(self, *a, **k):
        return self.cap

    def fetch_page(self, js, cap, page, size):
        self.calls += 1
        return self.pages.pop(0) if self.pages else {"rows": []}


def ms(d):
    return int(pd.Timestamp(d).timestamp() * 1000)


def row(code, dep, com="2026-11-24", score=5):
    return {"code": code, "rating": score, "content": "good", "ctime": ms(com), "dtime": ms(dep)}


def run(fake):
    logs = []
    got = tpc.collect(CollectorContext(browser=fake, log=lambda m: logs.append(str(m))), "2026-11-16", "2026-11-22")
    return got, logs


LOGIN_ERR = {"error": "Trip.com 오류 응답: B端用户登录态获取失败, caused by: B端用户登录态获取失败",
             "ack": "Failure", "message": "B端用户登录态获取失败, caused by: B端用户登录态获取失败"}

print("[1] 로그인 풀림 → 0건 SUCCESS 가 아니라 로그인 안내 오류")
f = Fake([LOGIN_ERR])
try:
    run(f)
    ck("오류 발생", False, "조용히 통과")
except RuntimeError as e:
    ck("오류 발생 · 다시 로그인 안내", "다시 로그인" in str(e) and "vbooking" in str(e), str(e)[:70])
    ck("로그인 오류는 재시도하지 않음", f.calls == 1, f.calls)

print("\n[2] 다른 일시 오류는 재시도 후 계속")
f = Fake([{"error": "HTTP 502 · bad gateway"}, {"rows": [row("1", "2026-11-18")]}, {"rows": []}])
got, logs = run(f)
ck("재시도 후 수집", len(got) == 1 and f.calls == 3, f"{len(got)}건 · {f.calls}회")

print("\n[3] comments 없는 응답도 오류")
f = Fake([{"error": "응답에 comments 가 없습니다: keys=ResponseStatus"}] * 3)
try:
    run(f)
    ck("오류 발생", False)
except RuntimeError as e:
    ck("오류 발생", "comments" in str(e), str(e)[:60])

print("\n[4] 출발일 필터 · 60일 전 작성 리뷰에서 중단")
f = Fake([
    {"rows": [row("10", "2026-11-17"), row("11", "2026-11-25"), row("12", "2026-11-22", score=2)]},
    {"rows": [row("13", "2026-11-16", com="2026-11-01"), row("14", "2026-09-01", com="2026-09-01")]},
    {"rows": [row("15", "2026-11-18")]},   # 여기까지 오면 안 됨
])
got, logs = run(f)
ck("기간 내 3건 (11-25 제외)", sorted(got) == ["10", "12", "13"], sorted(got))
ck("오래된 작성일에서 중단", f.calls == 2, f.calls)
ck("2점도 수집", got["12"]["rating"] == "2")

print("\n[5] 캡처 실패 안내")
try:
    run(Fake([], cap=False))
    ck("캡처 실패 → 오류", False)
except RuntimeError as e:
    ck("캡처 실패 → 로그인 확인 안내", "로그인" in str(e))

print("\n" + ("전부 통과" if not FAIL else f"실패 {len(FAIL)}건"))
sys.exit(1 if FAIL else 0)
