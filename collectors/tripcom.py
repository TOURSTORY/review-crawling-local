from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd

from collectors.base import CollectorContext
from collectors.config import CHANNEL_META
from core.utils import format_rating, norm_code, parse_any_ms, to_epoch_ms

# ⚠️ 예전에는 응답에 comments 가 없으면 빈 목록 = '리뷰 끝' 으로 보고 0건을 SUCCESS 로 냈다.
#    실측(2026-11-25): vbooking 로그인이 풀리면 Trip.com 은 HTTP 200 으로
#    {"ResponseStatus": {"Ack": "Failure", "Errors": [{"Message": "B端用户登录态获取失败 ..."}]}}
#    만 돌려준다. 주간 예약 300건에 리뷰 0건으로 보고서가 조용히 틀렸다.
#    이제 Ack 가 Failure 이거나 comments 가 없으면 반드시 오류로 멈춘다.
LOGIN_HINTS = ("登录", "login", "Login", "未登录", "auth")
PAGE_SIZE = 50
MAX_PAGES = 3000
RETRY_WAITS = (1, 3)

JS = r"""
var cap=P[0], page=P[1], size=P[2];
var body={sceneInfo:{bizScene:'ACTIVITY'}, paging:{pageNo:page, pageSize:size},
  sorting:{orderBy:'COMMENT_TIME', desc:true}};
try{ var b=JSON.parse(cap.body); if(b&&b.sceneInfo){ body.sceneInfo=b.sceneInfo; } }catch(e){}
var res, txt='';
try{
  res=await fetch(cap.url,{method:'POST',credentials:'include',
    headers:Object.assign({}, cap.headers||{}, {'Content-Type':'application/json'}),
    body:JSON.stringify(body)});
  txt=await res.text();
}catch(e){ done({error:'네트워크 오류: '+String(e)}); return; }
if(!res.ok){ done({error:'HTTP '+res.status+' · '+txt.slice(0,200)}); return; }
var j=null; try{ j=JSON.parse(txt); }catch(e){ done({error:'응답을 JSON 으로 읽지 못했습니다 · '+txt.slice(0,200)}); return; }
var rs=(j&&j.ResponseStatus)||{};
if(String(rs.Ack||'').toLowerCase()==='failure'){
  var msgs=(rs.Errors||[]).map(function(e){return e.Message||e.ErrorCode||'';}).join(' / ');
  done({error:'Trip.com 오류 응답: '+(msgs||'(메시지 없음)'), ack:'Failure', message:msgs}); return;
}
if(!Array.isArray(j.comments)){
  done({error:'응답에 comments 가 없습니다: keys='+Object.keys(j||{}).join(',')}); return;
}
done({rows:j.comments.map(function(x){return {code:String(x.orderId), rating:x.score,
  content:x.content||'', ctime:x.commentTime,
  dtime:(x.orderInfo&&x.orderInfo.departureTime)||null};}),
  total:(j.paging&&(j.paging.totalCount||j.paging.total))||j.totalCount||null});
"""


def _is_login_error(message: str) -> bool:
    return any(h in str(message or "") for h in LOGIN_HINTS)


def collect(ctx: CollectorContext, dfrom: str, dto: str) -> dict[str, dict]:
    """Trip.com/Ctrip: 작성일 순 페이지네이션 + 출발일(departureTime) 로 기간 필터."""
    cap = ctx.browser.capture_request(CHANNEL_META["TPC"]["page"], "listOrderComments", wait=10)
    if not cap:
        raise RuntimeError(
            "Trip.com/Ctrip 요청을 잡지 못했습니다. 해당 지역 Chrome 에서 vbooking.ctrip.com "
            "리뷰 페이지에 로그인되어 있는지 확인하세요."
        )

    lo = to_epoch_ms(pd.Timestamp(dfrom))
    hi = to_epoch_ms(pd.Timestamp(dto) + timedelta(days=1)) - 1
    # 작성일 순 정렬이라 출발일이 기간 안인 리뷰가 뒤에 있을 수 있다. 작성일이 시작일 60일 전보다
    # 오래된 페이지가 나오면 멈춘다.
    stop_ms = to_epoch_ms(pd.Timestamp(dfrom) - timedelta(days=60))

    reviews: dict[str, dict] = {}
    page, rows_seen, total = 1, 0, None
    while page <= MAX_PAGES:
        r = None
        for wait in RETRY_WAITS + (None,):
            r = ctx.browser.fetch_page(JS, cap, page, PAGE_SIZE)
            if r and not r.get("error"):
                break
            # 로그인 오류는 다시 해도 같으므로 바로 멈춘다.
            if wait is None or (r and _is_login_error(r.get("message") or r.get("error"))):
                break
            ctx.log(f"[TPC] p{page} 응답 오류 → {wait}초 후 다시 시도: {(r or {}).get('error', '응답 없음')}"[:200])
            time.sleep(wait)
        if not r or r.get("error"):
            err = r.get("error") if r else "응답 없음"
            if r and _is_login_error(r.get("message") or err):
                raise RuntimeError(
                    "Trip.com/Ctrip 로그인이 풀렸습니다 (B端用户登录态获取失败 = 판매자 로그인 정보 없음). "
                    "해당 지역 Chrome 에서 vbooking.ctrip.com 에 다시 로그인한 뒤 수집하세요. "
                    f"[p{page}: {err}]"
                )
            raise RuntimeError(f"TPC p{page}: {err}")

        rows = r.get("rows") or []
        if total is None:
            total = r.get("total")
        if not rows:
            if page == 1:
                ctx.log(f"[TPC] 1페이지 0건 (서버 total={total}) → 계정/권한 확인 필요")
            break
        rows_seen += len(rows)
        oldest_ok = True
        for x in rows:
            ct = parse_any_ms(x.get("ctime"))
            dt = parse_any_ms(x.get("dtime"))
            if dt is not None and lo <= dt <= hi:
                try:
                    rating = float(x.get("rating"))
                    if 1 <= rating <= 5:
                        code = norm_code(x.get("code"))
                        if code and code != "0":
                            rd = pd.Timestamp(ct, unit="ms").strftime("%Y-%m-%d") if ct else ""
                            reviews[code] = {
                                "rating": format_rating(x.get("rating")),
                                "content": (x.get("content") or "").strip(),
                                "review_date": rd,
                            }
                except (ValueError, TypeError):
                    pass
            if ct is not None and ct < stop_ms:
                oldest_ok = False
        ctx.log(f"[TPC] p{page}: {len(rows)} rows · 기간 내 {len(reviews)} reviews"
                + (f" · 서버 total {total}" if total else ""))
        if not oldest_ok:
            break
        try:
            if total and rows_seen >= int(total):
                break
        except (TypeError, ValueError):
            pass
        page += 1
        time.sleep(0.12)
    return reviews
