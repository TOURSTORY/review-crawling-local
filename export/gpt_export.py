"""GPT(ChatGPT) 업로드용 분석 Excel – 선택한 투어의 KPI · 원본 리뷰 · 분석 프롬프트를 한 파일로.

v1.3 Review Analyzer 의 "AI 분석용 Excel 추출" 과 같은 내용이다.
"""
from __future__ import annotations

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from collectors.config import CHANNEL_DISPLAY, SUPPORTED_CHANNELS
from core.metrics import build_area_metrics, build_channel_metrics, build_overall_metrics


def _style_ai_export_sheet(ws):
    header_fill = PatternFill(start_color="DCE8F7", end_color="DCE8F7", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="172033")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions

    for col_cells in ws.columns:
        letter = get_column_letter(col_cells[0].column)
        header = str(col_cells[0].value or "")
        if header in ("Review Text", "Instruction", "Prompt"):
            width = 90
        elif header in ("Tour", "Product Original", "Guide"):
            width = 30
        else:
            max_len = max((len(str(c.value)) if c.value is not None else 0 for c in col_cells), default=8)
            width = min(max(max_len + 2, 10), 24)
        ws.column_dimensions[letter].width = width
        for cell in col_cells[1:]:
            cell.alignment = Alignment(vertical="top", wrap_text=(header in ("Review Text", "Instruction", "Prompt")))


def save_gpt_workbook(path: str, result, selected_tours, manager) -> dict:
    """선택 투어 [(Area, Tour), ...] 를 GPT 분석용 Excel 로 저장하고 건수를 돌려준다."""
    selected = set(selected_tours)

    # Selected booking scope. Keep all bookings so GPT can understand the
    # denominator and collection/data-quality context, not only review rows.
    master = result.master.copy()
    master["__key"] = list(zip(master["Area"].astype(str), master["Product Normalized"].astype(str)))
    selected_master = master[master["__key"].isin(selected)].drop(columns=["__key"]).copy()

    # Deterministic summaries calculated by the same Analyzer metrics engine.
    overall = build_overall_metrics(selected_master)
    tour_summary = result.tours.copy()
    tour_summary["__key"] = list(zip(tour_summary["Area"].astype(str), tour_summary["Tour"].astype(str)))
    tour_summary = (
        tour_summary[tour_summary["__key"].isin(selected)]
        .drop(columns=["__key"])
        .sort_values(["Area", "Tour"])
        .reset_index(drop=True)
    )
    area_summary = build_area_metrics(selected_master)
    channel_summary = build_channel_metrics(selected_master)

    review_rows = selected_master[selected_master["Review Found"].eq(True)].copy()

    def col(df, name, default=""):
        if name in df.columns:
            return df[name]
        return pd.Series([default] * len(df), index=df.index)

    tour_date = pd.to_datetime(col(review_rows, "Date", pd.NaT), errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    agency_series = col(review_rows, "Agency", "").astype(str)
    route_profiles = [
        manager.route_profile(area, agency) or "미설정"
        for area, agency in zip(col(review_rows, "Area", ""), agency_series)
    ]
    reviews_out = pd.DataFrame({
        "Tour Date": tour_date,
        "Review Date": col(review_rows, "Review Date", ""),
        "Area": col(review_rows, "Area", ""),
        "Tour": col(review_rows, "Product Normalized", ""),
        "Product Original": col(review_rows, "Product", ""),
        "Agency": agency_series,
        "Agency Name": agency_series.map(lambda x: CHANNEL_DISPLAY.get(x, x)),
        "Agency Code": col(review_rows, "Agency Code", ""),
        "Booking Key": col(review_rows, "Booking Key", ""),
        "Chrome Profile": route_profiles,
        "Rating": pd.to_numeric(col(review_rows, "Rating", ""), errors="coerce"),
        "Review Group": col(review_rows, "Review Group", ""),
        "Review Text": col(review_rows, "Review Text", ""),
        "Main Guide": col(review_rows, "Main Guide", ""),
        "Guides": col(review_rows, "Guides", ""),
        "People": col(review_rows, "People", ""),
        "Nationality": col(review_rows, "Nationality", ""),
        "Language": col(review_rows, "Language", ""),
    }).sort_values(["Area", "Tour", "Rating", "Tour Date"], ascending=[True, True, True, False]).reset_index(drop=True)
    reviews_out.insert(0, "Review ID", [f"R{i:06d}" for i in range(1, len(reviews_out) + 1)])

    # A compact booking-level sheet helps independently validate denominators,
    # collection errors, unsupported agencies and no-review rows.
    booking_date = pd.to_datetime(col(selected_master, "Date", pd.NaT), errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    booking_agencies = col(selected_master, "Agency", "").astype(str)
    booking_profiles = [
        manager.route_profile(area, agency) or "미설정"
        if str(agency).strip().upper() in SUPPORTED_CHANNELS else "-"
        for area, agency in zip(col(selected_master, "Area", ""), booking_agencies)
    ]
    bookings_out = pd.DataFrame({
        "Tour Date": booking_date,
        "Area": col(selected_master, "Area", ""),
        "Tour": col(selected_master, "Product Normalized", ""),
        "Product Original": col(selected_master, "Product", ""),
        "Agency": booking_agencies,
        "Agency Code": col(selected_master, "Agency Code", ""),
        "Booking Key": col(selected_master, "Booking Key", ""),
        "Chrome Profile": booking_profiles,
        "People": col(selected_master, "People", ""),
        "Main Guide": col(selected_master, "Main Guide", ""),
        "Guides": col(selected_master, "Guides", ""),
        "Nationality": col(selected_master, "Nationality", ""),
        "Language": col(selected_master, "Language", ""),
        "Collection Eligible": col(selected_master, "Collection Eligible", False),
        "Collection Status": col(selected_master, "Collection Status", ""),
        "Review Found": col(selected_master, "Review Found", False),
        "Rating": pd.to_numeric(col(selected_master, "Rating", ""), errors="coerce"),
        "Review Group": col(selected_master, "Review Group", ""),
    }).sort_values(["Area", "Tour", "Tour Date", "Agency"]).reset_index(drop=True)

    # Collection status is included because collection errors must NOT be
    # interpreted as customers who did not review.
    status_rows = []
    for ch, info in (result.collection_status or {}).items():
        profiles = info.get("profiles") or {}
        if profiles:
            for profile, pinfo in profiles.items():
                status_rows.append({
                    "Agency": ch,
                    "Agency Name": CHANNEL_DISPLAY.get(ch, ch),
                    "Chrome Profile": profile,
                    "Area": ", ".join(pinfo.get("areas") or []),
                    "Status": pinfo.get("status", ""),
                    "Collected Reviews": pinfo.get("count", 0),
                    "Error": pinfo.get("error", ""),
                })
        else:
            status_rows.append({
                "Agency": ch,
                "Agency Name": CHANNEL_DISPLAY.get(ch, ch),
                "Chrome Profile": "",
                "Area": "",
                "Status": info.get("status", ""),
                "Collected Reviews": info.get("count", 0),
                "Error": info.get("error", ""),
            })
    collection_df = pd.DataFrame(status_rows)

    selected_areas = sorted(selected_master["Area"].dropna().astype(str).unique().tolist())
    selected_tour_names = sorted(selected_master["Product Normalized"].dropna().astype(str).unique().tolist())
    date_min = pd.to_datetime(selected_master["Date"], errors="coerce").min()
    date_max = pd.to_datetime(selected_master["Date"], errors="coerce").max()
    date_text = ""
    if pd.notna(date_min) and pd.notna(date_max):
        date_text = f"{date_min.strftime('%Y-%m-%d')} ~ {date_max.strftime('%Y-%m-%d')}"

    overall_row = overall.iloc[0].to_dict() if not overall.empty else {}
    scope_snapshot = (
        f"기간 {date_text} | Area {', '.join(selected_areas)} | 투어 {len(selected_tour_names)}개 | "
        f"Total Booking {int(overall_row.get('Total Booking', 0)):,} | "
        f"Eligible {int(overall_row.get('Eligible', 0)):,} | "
        f"Valid Review Scope {int(overall_row.get('Valid Review Scope', 0)):,} | "
        f"Reviews {int(overall_row.get('Reviews', 0)):,} | "
        f"GOOD {int(overall_row.get('Good', 0)):,} | BAD {int(overall_row.get('Bad', 0)):,}"
    )

    prompt = """당신은 TOURSTORY 여행상품 운영팀의 리뷰 분석가다. 이 Excel 파일 하나만 근거로 리뷰를 심층 분석해라.

[가장 중요한 원칙]
1) 숫자 집계는 이 파일의 Overall / Tour Summary / Area Summary / Channel Summary를 우선 사용하고, 필요하면 Bookings와 Reviews로 검증한다.
2) BAD = 1~3점, GOOD = 4~5점이다. 4점은 GOOD에 포함하지만, 명시적인 아쉬움/개선 제안은 '4점 개선 포인트'에도 별도로 포함한다.
3) Review Rate = Reviews / Valid Review Scope. Valid Review Scope는 리뷰 수집 가능한 예약에서 Collection Error를 제외한 예약 수다.
4) Overall Coverage = Reviews / Total Booking이다.
5) Unsupported, NOT_SELECTED, COLLECTION_ERROR를 '리뷰를 안 쓴 고객' 또는 부정 반응으로 해석하지 마라.
6) 한 Booking이 여러 명이어도 리뷰율의 분모는 People이 아니라 Booking 건수다.
7) 리뷰 내용은 언어가 달라도 의미가 같으면 하나의 한국어 Theme으로 통합한다. 한국어/영어/중국어/일본어 등 언어 자체로 Theme을 쪼개지 마라.
8) 단어 빈도가 아니라 문맥/의미를 기준으로 분석한다. 한 리뷰에 서로 다른 이슈/강점이 있으면 복수 Theme으로 분류한다.
9) 리뷰에 적혀 있지 않은 사실은 추정하지 않는다. 고객의 인식/주장과 실제로 확인된 사실을 구분해서 표현한다.
10) 특정 가이드/직원을 평가할 때 표본이 너무 적으면 단정하지 말고 '소수 사례'라고 명시한다.
11) 원본 리뷰 근거를 제시할 때는 Reviews 시트의 Review ID(R000001 형태)를 반드시 함께 표시한다. 짧은 핵심 문구만 인용하고 전체 리뷰를 불필요하게 복사하지 않는다.
12) 안전, 사고, 위험운전, 고객 분실/이탈, 핵심 포함사항 미제공, 상품 설명과 실제 제공의 중대한 불일치는 빈도가 1건이어도 별도 Risk Signal로 표시한다.
13) 날짜 범위가 충분하면 월별/기간별 변화도 확인하되, 표본이 작은 기간의 비율은 과대해석하지 않는다.
14) Nationality/Language는 고객 속성일 뿐 원인으로 단정하지 않는다. 명확한 서비스 언어/커뮤니케이션 이슈가 리뷰에 적혀 있을 때만 관련성을 언급한다.

[분류 기준]
기본 Category는 GUIDE, ITINERARY, VEHICLE, ATTRACTION, MEETING_POINT, TIME, LANGUAGE, TICKET, FOOD, WEATHER, CUSTOMER_SERVICE, COMMUNICATION, PRODUCT_DESCRIPTION, OTHER를 사용하되 필요한 경우 의미가 명확한 하위 Theme을 한국어로 만든다.
예: GUIDE > 가이드 설명 부족 / TIME > 체류시간 부족 / VEHICLE > 에어컨 문제 / FOOD > 식당 선택권 부족.

[반드시 수행할 분석]
A. Executive Summary
- 전체 성과를 5~10줄로 요약한다.
- Total Booking, Eligible, Valid Review Scope, Reviews, Review Rate, Overall Coverage, GOOD/BAD, 5~1점 분포를 핵심 수치로 제시한다.
- 무엇이 잘 되고 있고 무엇이 가장 위험한지 먼저 말한다.

B. Area / Tour 성과 비교
- Area별, 투어별 Review Rate / Good Rate / Bad Rate / Reviews / BAD 건수를 비교한다.
- BAD Rate만 보고 작은 표본을 과대평가하지 말고 Reviews 수를 함께 고려한다.
- 최소 '주의 필요 투어', '안정적인 투어', '리뷰 확보가 필요한 투어'를 구분한다.

C. BAD 1~3점 심층 분석
- 투어별로 Category → Issue Theme → 관련 리뷰 수 → 해당 투어 BAD 중 비율 → 별점 분포 → 영향받은 OTA를 정리한다.
- 같은 의미는 반드시 통합한다.
- 각 주요 Theme마다 근거가 되는 원본 리뷰의 Review ID / Agency / Agency Code / Rating / Review Date를 2~5개 연결한다.
- 원본 리뷰는 필요 이상 길게 그대로 복사하지 말고 핵심 근거를 요약하되, 어떤 행을 근거로 했는지 식별 가능하게 한다.
- 반복 이슈와 단발성 이슈를 구분한다.

D. GOOD 4~5점 강점 분석
- Category → Positive Point → 리뷰 수 → GOOD 중 비율 → 주요 투어 순으로 정리한다.
- 가이드 친절, 설명력, 사진, 일정 구성, 관광지, 차량 편안함 등 실제 리뷰에서 반복되는 강점을 의미 기반으로 통합한다.
- '좋았다', '추천한다' 같은 일반적인 칭찬과 구체적인 강점을 구분한다.

E. 4점 개선 포인트
- 4점 리뷰만 별도로 읽고 '대체로 만족했지만 개선하면 5점이 될 요소'를 추출한다.
- Theme별 건수와 해당 투어, 대표 근거를 보여준다.
- 1~3점 문제와 겹치는 Theme이면 'BAD에서도 반복'이라고 표시한다.

F. Guide / 운영자 Signal
- Main Guide 기준으로 충분한 리뷰 표본이 있는 경우에만 반복 강점/반복 문제를 요약한다.
- 가이드별 Booking 수, Review 수, BAD 수를 함께 보며 단순 BAD 건수만으로 순위를 만들지 않는다.
- 이름이 비어 있거나 여러 Guides가 혼재한 경우는 데이터 한계를 명시한다.

G. Cross-tour / 운영 공통 문제
- 여러 투어에서 반복되는 문제를 찾아 투어별 건수를 비교한다.
- 예: 설명 부족, 식사 방식, 픽업/집합, 체류시간, 차량 냉방, 지연, 상품페이지와 실제 운영 차이.
- 특정 투어만의 문제인지 전사 공통 운영 문제인지 구분한다.

H. OTA / Channel 차이
- 채널별 Review Rate / Bad Rate / 별점 분포를 비교한다.
- 특정 OTA에서 같은 불만 Theme이 유독 반복되는지 확인한다.
- 표본이 적으면 그 점을 함께 표시한다.

I. 운영 액션 플랜
- 개선 과제를 P0 / P1 / P2로 나눈다.
  P0 = 즉시 수정이 필요한 상품/안전/핵심 판매포인트 불일치
  P1 = 반복 운영 문제로 단기간 개선 필요
  P2 = 중장기 개선/상품페이지/교육 최적화
- 각 액션에 '왜 필요한지 / 대상 투어 / 근거 Theme / 기대 효과'를 적는다.
- 가능한 경우 SOP, 가이드 브리핑, 일정 순서, 차량 점검, 식사 안내, 상품페이지 문구 등 구체적인 실행안을 제안한다.

J. 데이터 품질 / 해석 주의
- Collection Status를 확인해 실패/부분 실패 채널이 있으면 명시한다.
- 리뷰가 적은 투어는 결론의 신뢰도가 낮다고 표시한다.
- 리뷰가 없는 예약을 부정 평가로 취급하지 않는다.

[최종 출력 형식]
1. 한눈에 보는 결론
2. 핵심 KPI 표
3. 우선주의 Area/투어 Scorecard
4. BAD 핵심 이슈 표 (Review ID 근거 포함)
5. GOOD 핵심 강점 표 (Review ID 근거 포함)
6. 4점 개선 포인트 표
7. 투어별 상세 코멘트
8. Guide/운영자 Signal (표본 충분할 때만)
9. OTA별 차이
10. Cross-tour 반복 문제 / Risk Signal
11. P0/P1/P2 액션 플랜
12. 데이터 품질 및 주의사항

최종 답변은 한국어로 작성하고, 숫자는 가능한 한 건수와 비율을 함께 표시해라. 사용자가 이후 특정 Tour/Theme/가이드/원본 리뷰를 물으면 Reviews 시트의 원본 행을 다시 확인하여 답해라."""

    readme_rows = [
        ("사용 방법", "이 파일을 ChatGPT에 업로드한 뒤 '분석해줘'라고만 입력하세요. 아래 GPT 분석 지시를 그대로 따라 분석할 수 있도록 필요한 지표·예약·원본 리뷰를 모두 포함했습니다."),
        ("분석 Scope", scope_snapshot),
        ("선택 Area", ", ".join(selected_areas)),
        ("선택 Tour", " / ".join(selected_tour_names)),
        ("데이터 기준", "Tour Date는 예약 시트 Date가 기준입니다. 리뷰 작성일이 아니라 실제 투어 참가일 기준 Scope입니다."),
        ("Review 정의", "GOOD = 4~5점 / BAD = 1~3점"),
        ("Review Rate", "Reviews ÷ Valid Review Scope. Valid Review Scope = 수집 가능 예약 - Collection Error."),
        ("Overall Coverage", "Reviews ÷ Total Booking."),
        ("중요", "Unsupported / NOT_SELECTED / COLLECTION_ERROR는 No Review로 단정하지 않으며 부정 평가로 해석하지 않습니다."),
        ("GPT 분석 지시", prompt),
    ]
    readme = pd.DataFrame(readme_rows, columns=["Section", "Content"])

    rules = pd.DataFrame([
        ("Source of Truth", "Tour Date", "예약 시트 Date. 분석 기간 및 투어 운영기간의 기준."),
        ("Metric", "Total Booking", "선택 Scope의 전체 예약 건수. People이 아니라 Booking row 기준."),
        ("Metric", "Eligible", "지원 OTA(L/KK/GG/TPC/MRT) 예약 건수."),
        ("Metric", "Valid Review Scope", "Collection Error를 제외한 실제 리뷰 수집 가능 예약 건수."),
        ("Metric", "Reviews", "Agency + Agency Code가 예약과 매칭된 리뷰 건수."),
        ("Metric", "Review Rate", "Reviews / Valid Review Scope."),
        ("Metric", "Overall Coverage", "Reviews / Total Booking."),
        ("Rating", "GOOD", "4~5점."),
        ("Rating", "BAD", "1~3점."),
        ("4 Star", "Improvement", "GOOD에 포함하되, 명시적인 아쉬움/개선 의견은 별도 분석."),
        ("Semantic", "Multilingual", "언어가 달라도 의미가 같으면 동일한 한국어 Theme으로 통합."),
        ("Semantic", "Multi-label", "한 리뷰에 여러 이슈/강점이 있으면 여러 Theme에 포함 가능."),
        ("Evidence", "Review ID", "Reviews 시트의 R000001 형식 ID. 분석 결과의 근거를 추적할 때 이 ID를 사용."),
        ("Evidence", "Original Review", "Reviews 시트의 Review ID + Agency + Agency Code + Review Text를 근거로 사용."),
        ("Routing", "Chrome Profile", "Area + OTA에 연결된 로그인 계정 Profile. 수집 계정 검증용이며 리뷰 품질 지표 자체는 아님."),
    ], columns=["Type", "Item", "Definition"])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Keep this sheet FIRST so an uploaded workbook immediately exposes
        # its own instructions to GPT/analysts.
        readme.to_excel(writer, sheet_name="GPT_READ_ME_FIRST", index=False)
        overall.to_excel(writer, sheet_name="Overall", index=False)
        area_summary.to_excel(writer, sheet_name="Area Summary", index=False)
        tour_summary.to_excel(writer, sheet_name="Tour Summary", index=False)
        channel_summary.to_excel(writer, sheet_name="Channel Summary", index=False)
        reviews_out.to_excel(writer, sheet_name="Reviews", index=False)
        bookings_out.to_excel(writer, sheet_name="Bookings", index=False)
        collection_df.to_excel(writer, sheet_name="Collection Status", index=False)
        rules.to_excel(writer, sheet_name="Analysis Rules", index=False)

        for ws in writer.book.worksheets:
            _style_ai_export_sheet(ws)

        # Read-me sheet is intentionally wide and wrapped for a one-file workflow.
        ws = writer.book["GPT_READ_ME_FIRST"]
        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 120
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        # Make the full prompt readable without destroying sheet height.
        ws.row_dimensions[11].height = 240

        # Review text is the primary semantic evidence. Locate by header so
        # future column additions do not break formatting.
        rws = writer.book["Reviews"]
        review_col = None
        for cell in rws[1]:
            if str(cell.value or "") == "Review Text":
                review_col = cell.column
                break
        if review_col:
            letter = get_column_letter(review_col)
            for cell in rws[letter][1:]:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            rws.column_dimensions[letter].width = 95
    return {"tours": len(selected), "bookings": len(selected_master), "reviews": len(reviews_out)}
