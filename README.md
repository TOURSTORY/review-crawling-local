# TOURSTORY Review Crawler v2.0

ReviewCrawler v25 의 **주단위 / 월단위 · 지사 선택** 방식과 Review Analyzer v1.3 의
**지역별 Chrome 계정 · 5개 OTA 수집기 · 분석 화면** 을 합친 새 버전입니다.

## 처음 1회

1. `INSTALL.cmd` 실행 (Python 패키지 설치). `START.cmd` 를 바로 눌러도 없으면 설치를 물어봅니다.
2. `START.cmd` 실행 → **① 지역별 Chrome 연결** 화면
3. 옆 폴더에 v1.3 이 있으면 노란 안내가 뜹니다 → **[기존 로그인 그대로 사용]**
   - v1.3 의 `Chrome_debug*` 로그인 폴더를 복사 없이 연결합니다. 다시 로그인할 필요가 없습니다.
   - 이 경우 v1.3 폴더를 지우지 마세요.
   - 새로 로그인하려면 [새로 로그인할게요] → 각 지역 카드에서 Chrome 을 열고 로그인합니다
     (로그인 정보는 `chrome_profiles/<지역>` 에 저장).
4. 지역 카드마다 **[Chrome 열기 · OTA 로그인]** → 로그인 → **[로그인 확인]**

## 매주 / 매월 사용

1. **② 리뷰 수집**
   1. 예약 Excel 선택
   2. 보고 단위: **주단위(월~일)** 또는 **월단위(1일~말일)** → 목록에서 주/달 선택 (기본: 최신 주)
   3. 지사: 국가(한국/일본/호주/영국) 체크 또는 Area 개별 선택
   4. OTA 선택
   5. Chrome 연결 확인 표에서 어떤 지역 Chrome 으로 수집하는지 확인 (`⚠ 미설정` 은 수집 안 함)
   6. 결과 Excel: **통합 1개** / **국가별로 나눠서** / **지역(Area)별로 나눠서** (+ 통합 파일도 함께 저장)
      - 수집은 한 번만 하고, 결과를 국가/지역별 Excel 로 나눕니다. 각 파일의 지표·성과제·리뷰 총정리는 그 범위로 다시 계산됩니다.
      - 나눈 파일은 `... (국가별)` / `... (지역별)` 하위 폴더에 `Korea.xlsx`, `Korea-Seoul.xlsx` 처럼 저장됩니다.
   7. **[리뷰 수집 시작]** – 꺼진 지역 Chrome 은 자동으로 켜집니다
2. **③ 결과 · 보고서**
   - 결과 Excel: `Review Crawler 주간 <시작>_<종료> <국가>.xlsx` (예약 Excel 과 같은 폴더, 변경 가능)
     - 맨 앞 3개 시트: `지사 요약` · `성과제` · `투어별 리뷰 총정리` (AI 붙여넣기용)
     - 그 뒤: Overall / Tour·Area·Channel Metrics / Unsupported / Collection Status / Master
   - **지사 보고 텍스트**: v25 의 전체 Copy / 지사 Copy (메신저에 붙여넣기)
   - **성과제**: 5점 개수 · 3점 이하 · 실제 지급 (= 5점 − 3점 이하)
   - **투어별 분석**: BAD/GOOD/별점 필터, 더블클릭 → 원본 리뷰 · OpenAI AI 분석
   - **GPT 분석용 Excel**: ChatGPT 에 올리고 "분석해줘"
   - **수집 상태**: OTA × 지역 Chrome 별 성공/실패

## 지역별 Chrome

| 국가 | Klook | KKday | GetYourGuide | Trip.com | MyRealTrip |
|---|---|---|---|---|---|
| 한국 | KR | KR | KR | KR | KR |
| 일본 | JP | 미설정 | JP | KR | KR |
| 호주 | AU | 미설정 | AU | AU | 미설정 |
| 영국 | UK | 미설정 | UK | 미설정 | 미설정 |

- 각 지역 Chrome 은 별도 폴더 + 별도 port (KR 9222 · JP 9223 · AU 9224 · UK 9225) 라서 동시에 켜져도 섞이지 않습니다.
- 카드별로 **열기 / 로그인 확인 / 닫기** 를 따로 할 수 있습니다.
- 계정이 더 나뉘면: `Chrome 계정 추가 · 수정` 탭에서 계정 추가 → `OTA 연결표` 에서 해당 칸만 변경.
- 특정 Area 만 다른 계정: `Area 예외` 탭.
- 로그인 확인은 리뷰 페이지가 로그인 화면으로 넘어가는지 보는 추정입니다. `확인 불가` 면 Chrome 화면을 직접 보세요.

## 구성

```
START.cmd / INSTALL.cmd / main.py
collectors/   Klook · KKday · GYG · Trip.com · MRT 수집기 (v1.3 그대로)
core/         예약 읽기 · 범위 · 매칭 · 지표 · 파이프라인 · 지역 Chrome 관리 · 주/월 기간 · 보고 텍스트
export/       결과 Excel · 주간/월간 시트 3개 · GPT 분석용 Excel
analysis/     OpenAI 리뷰 분석 (투어 상세)
ui/           화면 (지역별 Chrome · 리뷰 수집 · 결과 · 투어 상세)
data/         browser_routing.json (설정, 첫 실행 때 생성) · tour_short_names.csv (선택)
tests/        python tests/<파일>.py
```

선택: `data/tour_short_names.csv` (열: 투어 이름, 약칭) 를 두면 성과제 '투어명' 에 약칭이 나옵니다.
