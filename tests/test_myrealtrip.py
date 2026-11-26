# -*- coding: utf-8 -*-
"""MyRealTrip 수집기 시험 (가짜 브라우저).

실측(2026-11-25): 예전 고정 주소 api3-backoffice.myrealtrip.com 이 DNS 에서 사라져
'MRT p1: TypeError: Failed to fetch' 로 전부 실패했다. 이제는 리뷰 페이지가 실제로 쓰는
주소를 캡처하고, 못 하면 api3-s 로 시도한다.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors import myrealtrip as mrt
from collectors.base import CollectorContext

FAIL = []
mrt.RETRY_WAITS = (0, 0, 0)   # 시험에서는 기다리지 않는다


def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok:
        FAIL.append(n)


class Driver:
    def __init__(self, url):
        self.current_url = url

    def get(self, url):
        self.current_url = url


class Fake:
    def __init__(self, cap, pages, url="https://partner.myrealtrip.com/reviews/touractivity"):
        self.cap, self.pages, self.calls = cap, list(pages), []
        self.driver = Driver(url)

    def capture_request(self, *a, **k):
        return self.cap

    def fetch_page(self, js, cap, page, size):
        self.calls.append((cap["url"], page, size))
        return self.pages.pop(0) if self.pages else {"rows": []}


def rows(n, start=0, tdate="2026-11-18", score=5):
    return [{"code": f"MRT{start + i:05d}", "rating": score, "content": "좋아요", "rdate": "2026-11-20T10:00:00",
             "tdate": tdate} for i in range(n)]


def run(fake):
    logs = []
    got = mrt.collect(CollectorContext(browser=fake, log=lambda m: logs.append(str(m))), "2026-11-16", "2026-11-22")
    return got, logs


CAP = {"url": "https://api3-s.myrealtrip.com/review/partner/reviews/search", "method": "POST",
       "headers": {"partner-access-token": "t"}, "body": "{}"}

print("[1] 캡처한 주소로 요청 · 페이지 · 투어일 필터")
f = Fake(CAP, [{"rows": rows(50, 0) , "total": 120},
               {"rows": rows(30, 50, "2026-11-10") + rows(20, 80, "2026-11-22"), "total": 120},
               {"rows": rows(20, 100, "2026-11-23"), "total": 120}])
got, logs = run(f)
ck("캡처 주소 사용", all(c[0] == CAP["url"] for c in f.calls))
ck("total 까지 3페이지", len(f.calls) == 3, len(f.calls))
ck("기간 내 70건 (11-10, 11-23 제외)", len(got) == 70, len(got))
ck("리뷰 형식", got["MRT00000"] == {"rating": "5", "content": "좋아요", "review_date": "2026-11-20"}, got["MRT00000"])

print("\n[2] 캡처 실패 → api3-s 기본 주소")
f = Fake(None, [{"rows": rows(3)}])
got, logs = run(f)
ck("기본 주소로 시도", f.calls[0][0] == mrt.DEFAULT_URL and "backoffice" not in mrt.DEFAULT_URL, f.calls[0][0])
ck("안내 로그", any("기본 주소" in m for m in logs))
ck("3건 수집", len(got) == 3)

print("\n[3] 로그인 페이지로 튕기면 알아듣게 실패")
f = Fake(CAP, [], url="https://partner.myrealtrip.com/login?redirect=/reviews")
try:
    run(f)
    ck("로그인 안내 오류", False)
except RuntimeError as e:
    ck("로그인 안내 오류", "다시 로그인" in str(e), str(e)[:60])

print("\n[4] 네트워크 오류는 오류로 멈춤 (0건 SUCCESS 금지)")
f = Fake(CAP, [{"error": "네트워크/CORS 차단 (TypeError: Failed to fetch)"}] * 4)
try:
    run(f)
    ck("오류로 중단", False)
except RuntimeError as e:
    ck("오류로 중단", "Failed to fetch" in str(e), str(e)[:70])

print("\n[4b] 한 페이지만 일시 오류면 다시 시도해서 계속")
BAD = {"error": "리뷰 목록이 없는 응답: keys=data,meta,result"}
f = Fake(CAP, [{"rows": rows(50, 0), "total": 80}, BAD, BAD, {"rows": rows(30, 50), "total": 80}])
got, logs = run(f)
ck("재시도 후 전부 수집", len(got) == 80, len(got))
ck("재시도 로그", sum("다시 시도" in m for m in logs) == 2)
f = Fake(CAP, [{"rows": rows(50, 0), "total": 80}, BAD, BAD, BAD, BAD])
try:
    run(f)
    ck("계속 실패하면 오류", False)
except RuntimeError as e:
    ck("계속 실패하면 오류", "p2" in str(e) and len(f.calls) == 5, f"calls {len(f.calls)}")

print("\n[5] 1페이지 0건이면 권한 확인 안내")
f = Fake(CAP, [{"rows": [], "total": 0}])
got, logs = run(f)
ck("0건 안내", any("1페이지 0건" in m for m in logs))

print("\n" + ("전부 통과" if not FAIL else f"실패 {len(FAIL)}건"))
sys.exit(1 if FAIL else 0)
