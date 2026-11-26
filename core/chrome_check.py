"""지역별 Chrome 의 OTA 로그인 상태 확인.

각 OTA 리뷰 페이지를 새 탭에서 열어 보고, 로그인 페이지로 튕기면 '로그인 필요' 로 본다.
URL 로 판단하는 추정이므로 '확인 불가' 가 나오면 Chrome 화면을 직접 확인한다.
사용자가 쓰던 탭은 건드리지 않고, 확인용 탭은 끝나면 닫는다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from collectors.config import CHANNEL_DISPLAY, CHANNEL_META
from core.browser_profiles import LOGIN_URL_HINTS, BrowserProfileManager

OK = "OK"
LOGIN_REQUIRED = "LOGIN"
UNKNOWN = "UNKNOWN"
NOT_RUNNING = "NOT_RUNNING"


@dataclass
class LoginState:
    channel: str
    status: str
    url: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        return {
            OK: "로그인됨",
            LOGIN_REQUIRED: "로그인 필요",
            UNKNOWN: "확인 불가",
            NOT_RUNNING: "Chrome 꺼짐",
        }.get(self.status, self.status)


def classify_url(url: str, page: str) -> str:
    low = str(url or "").lower()
    if not low or low.startswith(("about:", "chrome-error:", "data:")):
        return UNKNOWN
    if any(h in low for h in LOGIN_URL_HINTS):
        return LOGIN_REQUIRED
    page_host = page.split("/")[2].lower() if "://" in page else ""
    if page_host and page_host in low:
        return OK
    return UNKNOWN


# Trip.com(vbooking) 은 로그인이 풀려도 로그인 화면으로 넘어가지 않고 리뷰 페이지를 그대로 연다.
# 주소만 봐서는 '로그인됨' 으로 잘못 나오므로, 리뷰 API 에 1건만 요청해 실제 로그인 상태를 본다.
# (실측 2026-11-25: Ack=Failure · 'B端用户登录态获取失败')
TPC_API_PATH = "/tour/comment_manage/restapi/geteway/18717/listOrderComments"
TPC_CHECK_JS = r"""
var done=arguments[arguments.length-1];
fetch(arguments[0], {method:'POST', credentials:'include',
  headers:{'Content-Type':'application/json','x-tour-auth-from':'vbkComment'},
  body:JSON.stringify({sceneInfo:{bizScene:'ACTIVITY'}, paging:{pageNo:1,pageSize:1},
                       sorting:{orderBy:'COMMENT_TIME',desc:true}})})
 .then(function(r){ return r.text().then(function(t){ done({status:r.status, text:t.slice(0,600)}); }); })
 .catch(function(e){ done({status:0, text:String(e)}); });
"""


def tpc_api_status(driver) -> tuple[str, str]:
    """(상태, 메모). 확인할 수 없으면 UNKNOWN."""
    try:
        r = driver.execute_async_script(TPC_CHECK_JS, TPC_API_PATH) or {}
    except Exception as exc:
        return UNKNOWN, str(exc)[:120]
    text = str(r.get("text") or "")
    if r.get("status") != 200:
        return UNKNOWN, f"API HTTP {r.get('status')}"
    if '"comments"' in text and '"Success"' in text:
        return OK, ""
    if "登录" in text or "login" in text.lower():
        return LOGIN_REQUIRED, "Trip.com 판매자 로그인 정보 없음 (B端用户登录态获取失败)"
    return UNKNOWN, text[:120]


def check_profile_logins(manager: BrowserProfileManager, key: str, channels: list[str],
                         wait: float = 6.0, log=lambda m: None) -> list[LoginState]:
    if not manager.is_running(key):
        return [LoginState(ch, NOT_RUNNING) for ch in channels]

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_experimental_option("debuggerAddress", manager.debug_address(key))
    driver = webdriver.Chrome(options=opts)
    out: list[LoginState] = []
    original = None
    try:
        try:
            original = driver.current_window_handle
        except Exception:
            original = None
        for ch in channels:
            page = CHANNEL_META.get(ch, {}).get("page")
            if not page:
                continue
            log(f"[{key}] {CHANNEL_DISPLAY.get(ch, ch)} 로그인 확인 중...")
            try:
                driver.switch_to.new_window("tab")
                driver.get(page)
                status, url = UNKNOWN, ""
                deadline = time.time() + wait
                while time.time() < deadline:
                    time.sleep(0.8)
                    url = driver.current_url
                    status = classify_url(url, page)
                    if status == LOGIN_REQUIRED:
                        break
                note = ""
                if ch == "TPC" and status != LOGIN_REQUIRED:
                    status, note = tpc_api_status(driver)
                out.append(LoginState(ch, status, url, note))
            except Exception as exc:
                out.append(LoginState(ch, UNKNOWN, note=str(exc)[:120]))
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
                try:
                    handles = driver.window_handles
                    target = original if original in handles else (handles[0] if handles else None)
                    if target:
                        driver.switch_to.window(target)
                except Exception:
                    pass
    finally:
        # 붙어 있던 Chrome 은 끄지 않는다.
        try:
            driver.service.stop()
        except Exception:
            pass
    return out


def open_login_pages(manager: BrowserProfileManager, key: str, channels: list[str]) -> bool:
    """Chrome 을 켜고 해당 OTA 페이지들을 탭으로 연다. 이미 켜져 있으면 새 탭으로 연다."""
    urls = [CHANNEL_META[c]["page"] for c in channels if c in CHANNEL_META]
    if not manager.is_running(key):
        manager.ensure_profile(key, urls=urls or None)
        return True
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_experimental_option("debuggerAddress", manager.debug_address(key))
    driver = webdriver.Chrome(options=opts)
    try:
        for u in urls:
            driver.switch_to.new_window("tab")
            driver.get(u)
    finally:
        try:
            driver.service.stop()
        except Exception:
            pass
    return False
