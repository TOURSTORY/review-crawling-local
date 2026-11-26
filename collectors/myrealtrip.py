from __future__ import annotations

import re
import time

from collectors.base import CollectorContext
from collectors.config import CHANNEL_META
from core.utils import format_rating, norm_code

# ⚠️ 예전에는 api3-backoffice.myrealtrip.com 을 고정으로 불렀다. 이 주소가 없어져서
#    (DNS 조회 실패) 브라우저가 'TypeError: Failed to fetch' 로 첫 페이지부터 실패했다.
#    이제는 다른 채널처럼 로그인된 리뷰 페이지가 실제로 보내는 요청 주소를 캡처해서 쓰고,
#    캡처하지 못하면 현재 주소(api3-s)로 시도한다. (ReviewCrawler v25 와 같은 방식)
DEFAULT_URL = "https://api3-s.myrealtrip.com/review/partner/reviews/search"
PAGE_SIZE = 50
MAX_PAGES = 3000
RETRY_WAITS = (1, 3, 6)   # 일시 오류 시 같은 페이지 재시도 간격(초)

FETCH_JS = r"""
var cap=P[0], page=P[1], size=P[2];
var method=(cap.method||'POST').toUpperCase();
var hdr={};
var ch=cap.headers||{};
for(var k in ch){ hdr[k]=ch[k]; }
function hget(name){ for(var k in hdr){ if(k.toLowerCase()===name) return hdr[k]; } return null; }
// 토큰: 캡처된 헤더 → localStorage('accessToken') → localStorage 의 *token* 키
if(!hget('partner-access-token')){
  var tok=null;
  try{ tok=localStorage.getItem('accessToken'); }catch(e){}
  if(!tok){
    try{ for(var i=0;i<localStorage.length;i++){ var key=localStorage.key(i);
           if(/token/i.test(key)){ tok=localStorage.getItem(key); break; } } }catch(e){}
  }
  if(tok){ hdr['partner-access-token']=tok; }
}
var tokState=hget('partner-access-token') ? '있음' : '없음';
var url=cap.url, opt={method:method, credentials:'include', headers:hdr};
if(method==='GET'){
  var u=new URL(url, location.origin);
  u.searchParams.set('page', String(page));
  u.searchParams.set('pageSize', String(size));
  url=u.toString();
}else{
  // 캡처된 본문에는 화면 필터(탭/상품)가 섞일 수 있어 쓰지 않는다. 전체 리뷰 = {page, pageSize}.
  if(!hget('content-type')){ hdr['Content-Type']='application/json'; }
  opt.body=JSON.stringify({page:page, pageSize:size});
}
var res;
try{ res=await fetch(url, opt); }
catch(e){
  done({error:'네트워크/CORS 차단 ('+String(e)+') · url='+url+' · 토큰='+tokState+' · 현재 탭='+location.href});
  return;
}
if(!res.ok){
  var t=''; try{ t=(await res.text()).slice(0,200); }catch(e){}
  done({error:'HTTP '+res.status+' · 토큰='+tokState+' · '+t});
  return;
}
var j; try{ j=await res.json(); }catch(e){ done({error:'응답을 JSON 으로 읽지 못했습니다: '+String(e)}); return; }
var list=null;
if(Array.isArray(j.data)) list=j.data;
else if(j.data && Array.isArray(j.data.content)) list=j.data.content;
else if(j.data && Array.isArray(j.data.list)) list=j.data.list;
if(list===null){
  var why=''; try{ why=JSON.stringify(j.result||j.meta||{}).slice(0,200); }catch(e){}
  done({error:'리뷰 목록이 없는 응답: keys='+Object.keys(j||{}).join(',')+' · '+why}); return;
}
done({rows:list.map(function(x){return {code:x.reservationNo, rating:x.score, content:x.comment||'',
      rdate:x.createdAt, tdate:x.travelStartDate};}),
      total:(j.meta&&j.meta.totalCount)||null});
"""


def _prepare(ctx: CollectorContext) -> dict:
    """리뷰 페이지가 보내는 실제 요청을 캡처한다. 실패하면 기본 주소. 항상 MRT 탭에서 끝난다."""
    cap = None
    try:
        cap = ctx.browser.capture_request(CHANNEL_META["MRT"]["page"], CHANNEL_META["MRT"]["endpoint"], wait=12)
    except Exception as exc:
        ctx.log(f"[MRT] 요청 캡처 중 오류: {exc}")

    driver = ctx.browser.driver
    current = ""
    try:
        current = driver.current_url or ""
    except Exception:
        pass
    if "myrealtrip.com" not in current:
        driver.get(CHANNEL_META["MRT"]["page"])
        time.sleep(3)
        current = driver.current_url or ""
    if re.search(r"login|signin|auth", current, flags=re.IGNORECASE):
        raise RuntimeError(
            "MyRealTrip 로그인 페이지로 이동했습니다. 해당 지역 Chrome 에서 "
            f"MyRealTrip 파트너센터에 다시 로그인하세요. (현재 주소: {current})"
        )

    if cap and cap.get("url"):
        ctx.log(f"[MRT] 요청 캡처: {cap.get('method', 'POST')} {cap['url']}")
        return cap
    ctx.log(f"[MRT] 요청을 캡처하지 못해 기본 주소로 시도합니다: {DEFAULT_URL}")
    return {"url": DEFAULT_URL, "method": "POST", "headers": {}, "body": None}


def collect(ctx: CollectorContext, dfrom: str, dto: str) -> dict[str, dict]:
    """MyRealTrip: 전체 리뷰 페이지네이션 + 투어일(travelStartDate) 로 기간 필터."""
    if ctx.browser.driver is None:
        raise RuntimeError("Chrome is not connected")

    cap = _prepare(ctx)
    reviews: dict[str, dict] = {}
    page, rows_seen, total = 1, 0, None
    while page <= MAX_PAGES:
        # 30페이지쯤 연달아 요청하면 가끔 한 페이지가 빈 응답으로 온다 (실측 2026-11-25, p23).
        # 바로 다시 요청하면 정상이므로 같은 페이지를 몇 번 더 시도한 뒤에만 실패로 본다.
        r = None
        for attempt, wait in enumerate(RETRY_WAITS + (None,)):
            r = ctx.browser.fetch_page(FETCH_JS, cap, page, PAGE_SIZE)
            if r and not r.get("error"):
                break
            if wait is None:
                break
            ctx.log(f"[MRT] p{page} 응답 오류 → {wait}초 후 다시 시도 ({attempt + 1}/{len(RETRY_WAITS)}): "
                    f"{(r or {}).get('error', '응답 없음')}"[:200])
            time.sleep(wait)
        if not r or r.get("error"):
            raise RuntimeError(f"MRT p{page}: {r.get('error') if r else '응답 없음'}")
        rows = r.get("rows") or []
        if total is None:
            total = r.get("total")
        if not rows:
            if page == 1:
                ctx.log(f"[MRT] 1페이지 0건 (서버 total={total}) → 로그인 계정/권한 확인 필요")
            break
        rows_seen += len(rows)
        for x in rows:
            tdate = (x.get("tdate") or "")[:10]
            if not tdate or not (dfrom <= tdate <= dto):
                continue
            try:
                rating = float(x.get("rating"))
                if rating < 1 or rating > 5:
                    continue
            except (ValueError, TypeError):
                continue
            code = norm_code(x.get("code"))
            if not code:
                continue
            reviews[code] = {
                "rating": format_rating(x.get("rating")),
                "content": (x.get("content") or "").strip(),
                "review_date": (x.get("rdate") or "")[:10],
            }
        ctx.log(f"[MRT] p{page}: {len(rows)} rows · 기간 내 {len(reviews)} reviews"
                + (f" · 서버 total {total}" if total else ""))
        if len(rows) < PAGE_SIZE or (total and rows_seen >= int(total)):
            break
        page += 1
        time.sleep(0.15)
    return reviews
