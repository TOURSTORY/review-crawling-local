# -*- coding: utf-8 -*-
"""리뷰 수집기 시험 (실제 OTA 접속 없이 가짜 브라우저로).

실측(2026-09-24)으로 확인한 두 가지를 시험으로 고정한다.

  KKday  투어 날짜 범위가 33일 이상이면 result=false,
         message='Input parameter error'. 32일까지는 정상.
         → 기간을 31일 이하로 잘라 여러 번 요청해야 한다.

  GG     요청 헤더를 배열로 넘기는 경로가 있어 authorization 이 캡처되지
         않았고, 재생 요청이 전부 HTTP 401 이었다. 그런데 수집기가 상태
         코드를 보지 않아 '데이터 끝' 으로 처리하고 0건을 SUCCESS 로
         보고했다. 이 시험은 오류를 반드시 오류로 멈추는지 본다.
"""
import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collectors import getyourguide as ggc, kkday as kk
from collectors.base import CollectorContext

FAIL=[]
def ck(n, ok, d=""):
    print(f"  {'OK  ' if ok else '★FAIL'} {n}" + (f"   [{d}]" if d else ""))
    if not ok: FAIL.append(n)

CAP={"begGoDate":"","endGoDate":"","begRecDate":"2026-08-24","endRecDate":"2026-09-24",
     "currentPage":1,"pageSize":10,"recScores":[1,2,3,4,5]}

class Fake:
    """실제 KKday 규칙을 흉내: 기간 33일 이상이면 Input parameter error."""
    def __init__(self, max_span=32, per_day=2):
        self.max_span=max_span; self.per_day=per_day; self.calls=[]
    def capture_request(self,*a,**k):
        return {"url":"https://x","headers":{},"body":json.dumps(CAP)}
    def fetch_page(self, js, cap, page, size, sd, ed):
        from datetime import date
        self.calls.append((sd,ed,page,size))
        span=(date.fromisoformat(ed)-date.fromisoformat(sd)).days+1
        if span > self.max_span:
            return {"error":"API result=false | code= | message=Input parameter error",
                    "message":"Input parameter error","sent":{"begGoDate":sd,"endGoDate":ed}}
        total=span*self.per_day
        start=(page-1)*size
        rows=[{"id":f"{sd}-{i}","code":f"C{sd}{i:04d}","rating":5,"title":"t","desc":"d",
               "rdate":sd} for i in range(start, min(start+size, total))]
        return {"rows":rows,"total":total}

def run(fake, a, b):
    logs=[]
    got=kk.collect(CollectorContext(browser=fake, log=lambda m: logs.append(str(m))), a, b)
    return got, logs

print("="*66); print("KKday 기간 분할"); print("="*66)
print("\n[1] 분기(92일) 수집 — 예전에는 p1 에서 Input parameter error")
f=Fake(); got,logs=run(f,"2026-07-01","2026-09-30")
ck("오류 없이 수집 완료", len(got)==92*2, f"{len(got)}건 (기대 184)")
ck("구간을 나눴다고 알림", any("구간으로 나눠" in m for m in logs),
   [m for m in logs if "구간으로 나눠" in m][:1])
spans={(a,b) for a,b,_,_ in f.calls}
ck("모든 구간이 31일 이하", all((__import__('datetime').date.fromisoformat(b)-__import__('datetime').date.fromisoformat(a)).days+1<=31 for a,b in spans),
   f"{len(spans)}개 구간")
ck("구간이 끊김 없이 이어짐", sorted(spans)[0][0]=="2026-07-01" and sorted(spans)[-1][1]=="2026-09-30",
   str(sorted(spans)))
ck("합계 로그", any("합계: 예약코드" in m for m in logs), [m for m in logs if "합계" in m][:1])

print("\n[2] 31일 이하면 나누지 않음")
f=Fake(); got,logs=run(f,"2026-08-01","2026-08-31")
ck("한 구간으로 처리", len({(a,b) for a,b,_,_ in f.calls})==1, f"{len(got)}건")
ck("분할 안내 없음", not any("구간으로 나눠" in m for m in logs))

print("\n[3] KKday 상한이 더 줄어도 스스로 더 쪼개는가 (상한 10일 가정)")
f=Fake(max_span=10); got,logs=run(f,"2026-08-01","2026-08-31")
ck("자동으로 더 쪼개 수집", len(got)==31*2, f"{len(got)}건 (기대 62)")
ck("쪼갠 사실을 알림", any("더 쪼갭니다" in m for m in logs),
   [m for m in logs if "쪼갭니다" in m][:1])

print("\n[4] 페이징이 total 까지 도는가")
f=Fake(max_span=32, per_day=5); got,logs=run(f,"2026-08-01","2026-08-31")
ck("31일×5 = 155건 전부", len(got)==155, f"{len(got)}건")

print("\n[5] 시작>끝 역전도 처리")
f=Fake(); got,logs=run(f,"2026-08-31","2026-08-01")
ck("역전 입력도 수집", len(got)==31*2, f"{len(got)}건")

class GGFake:
    """capture_request / fetch_page 만 흉내 낸다. JS 는 실행하지 않고
    파이썬 쪽 제어 흐름(오류 처리·페이지 종료 조건)만 검증한다."""
    def __init__(self, cap_body, responses):
        self.cap_body = cap_body
        self.responses = list(responses)
        self.calls = []

    def capture_request(self, *a, **k):
        if self.cap_body is None:
            return None
        return {"url": "https://x/api", "headers": {}, "body": json.dumps(self.cap_body)}

    def fetch_page(self, js, cap, *args):
        self.calls.append(args)
        return self.responses.pop(0) if self.responses else {"rows": []}


def ctx_of(browser, logs):
    return CollectorContext(browser=browser, log=lambda m: logs.append(str(m)))


print("=" * 66)
print("GetYourGuide")
print("=" * 66)
GG_CAP = {"operationName": "Reviews_ReviewSearch",
          "variables": {"input": {"limit": 10, "offset": 0}}}

print("\n[1] 401 을 오류로 멈추는가 (예전에는 0건 SUCCESS)")
logs = []
b = GGFake(GG_CAP, [{"error": "HTTP 401 · Unauthorized", "status": 401}])
try:
    ggc.collect(ctx_of(b, logs), "2026-08-01", "2026-08-31")
    ck("401 → 오류 발생", False, "조용히 통과했다")
except RuntimeError as e:
    ck("401 → 오류 발생", "401" in str(e), str(e)[:90])
    ck("오류에 offset/limit/기간 포함", all(x in str(e) for x in ("offset=", "limit=", "travelDate")),
       str(e)[:110])

print("\n[2] GraphQL 오류도 멈추는가")
b = GGFake(GG_CAP, [{"error": "GraphQL 오류 · [{\"message\":\"forbidden\"}]", "status": 200}])
try:
    ggc.collect(ctx_of(b, []), "2026-08-01", "2026-08-31")
    ck("GraphQL errors → 오류 발생", False)
except RuntimeError as e:
    ck("GraphQL errors → 오류 발생", "GraphQL" in str(e), str(e)[:80])

print("\n[3] 서버가 요청보다 적게 줘도 다음 페이지를 계속 보는가")
def rows(n, start=0):
    return [{"code": f"B{start+i:05d}", "rating": 5, "content": "good", "rdate": "2026-08-10"}
            for i in range(n)]
logs = []
b = GGFake(GG_CAP, [
    {"rows": rows(25, 0)},      # 50 을 요청했는데 25만 옴 (예전 코드는 여기서 끝냄)
    {"rows": rows(25, 25)},
    {"rows": rows(7, 50)},
    {"rows": []},
])
got = ggc.collect(ctx_of(b, logs), "2026-08-01", "2026-08-31")
ck("짧은 페이지에서 멈추지 않음", len(got) == 57, f"{len(got)}건 · 호출 {len(b.calls)}회")

print("\n[4] 같은 데이터만 반복되면 멈추는가 (무한 루프 방지)")
logs = []
b = GGFake(GG_CAP, [{"rows": rows(10, 0)} for _ in range(30)])
got = ggc.collect(ctx_of(b, logs), "2026-08-01", "2026-08-31")
ck("중복만 오면 중단", len(b.calls) <= 4, f"호출 {len(b.calls)}회 · {len(got)}건")

print("\n[5] 서버 total 과 다르면 경고하는가")
logs = []
b = GGFake(GG_CAP, [{"rows": rows(10, 0), "total": 99}, {"rows": []}])
ggc.collect(ctx_of(b, logs), "2026-08-01", "2026-08-31")
ck("total 미달 경고", any("total 99" in m and "적게" in m for m in logs),
   [m for m in logs if "total" in m][:1])

print("\n[6] 별점 범위 밖·빈 코드는 제외하고 그 차이를 알리는가")
logs = []
b = GGFake(GG_CAP, [{"rows": [
    {"code": "A1", "rating": 5, "content": "", "rdate": ""},
    {"code": "A2", "rating": 9, "content": "", "rdate": ""},   # 범위 밖
    {"code": "", "rating": 4, "content": "", "rdate": ""},      # 코드 없음
]}, {"rows": []}])
got = ggc.collect(ctx_of(b, logs), "2026-08-01", "2026-08-31")
ck("유효한 1건만 수집", len(got) == 1, f"{len(got)}건")
ck("행 수와 예약코드 수 차이를 알림", any("예약코드" in m and "행" in m for m in logs),
   [m for m in logs if "참고" in m][:1])

print("\n[7] 캡처 실패 시 안내가 사람이 읽을 수 있는가")
try:
    ggc.collect(ctx_of(GGFake(None, []), []), "2026-08-01", "2026-08-31")
    ck("캡처 실패 → 오류", False)
except RuntimeError as e:
    ck("캡처 실패 → 로그인 확인 안내", "로그인" in str(e), str(e)[:70])

print("\n"+"="*66)
print(f"실패 {len(FAIL)}건" if FAIL else "전부 통과")
for x in FAIL: print("  -",x)
sys.exit(1 if FAIL else 0)
