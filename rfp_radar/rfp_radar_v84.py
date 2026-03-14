# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║  RFP Radar v8.4                                                      ║
║  공공기관 마케팅 용역 입찰 추천 시스템 (통합 크롤링)                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  버전: v8.4 (2026-03-14)                                             ║
║  개발: WKMG (WK Marketing Group)                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  v8.4 변경사항 (이세민 컨설턴트 의견 반영):                            ║
║  ★ WKMG 입찰 자격 사전 검증 모듈 추가                                  ║
║     1. 수의계약 제외 (cntrctCnclsMthdNm / sucsfbidMthdNm)             ║
║     2. 지역제한 API (getBidPblancListInfoPrtcptPsblRgn)               ║
║        → 서울 미포함 시 제외                                           ║
║     3. 업종제한 API (getBidPblancListInfoLicenseLimit)                 ║
║        → 허용업종이 {1169, 4440, 9999} 외 AND 조건이면 제외             ║
║     4. 직접생산확인증명서 조건 제외                                      ║
║  ★ 예산 필드 개선: asignBdgtAmt 우선 / presmptPrce 보조               ║
║  (자격 검증은 키워드 매칭 후보에만 선택 실행 — API 비용 절약)            ║
╠══════════════════════════════════════════════════════════════════════╣
║  v8.3 이하 내용은 rfp_radar_v83.py 참조                              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import requests, json, os, sys, hashlib, time, re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import urllib3, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding='utf-8')

VERSION = "8.4"

# ─── v83 전체를 상속받고 변경 부분만 오버라이드 ───────────────────────────────
# v83 파일이 같은 디렉토리에 있어야 함
import importlib.util, os as _os
_v83_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "rfp_radar_v83.py")
_spec = importlib.util.spec_from_file_location("rfp_radar_v83", _v83_path)
_v83 = importlib.util.module_from_spec(_spec)

# v83 실행 전 VERSION 값만 패치 (헤더 출력 방지 불가하므로 그냥 로드)
import sys as _sys
_sys.modules["rfp_radar_v83"] = _v83
_spec.loader.exec_module(_v83)

# v83의 모든 심볼을 이 모듈로 가져오기
from rfp_radar_v83 import *

# VERSION 덮어쓰기
VERSION = "8.4"

# ─── WKMG 허용 업종 코드 (이세민 컨설턴트 확인) ───────────────────────────────
# 이 세 코드 중 하나라도 허용업종에 포함되면 입찰 가능
WKMG_ALLOWED_INDUSTRY_CODES = {"1169", "4440", "9999"}
# 1169: 학술·연구용역 / 4440: 산업디자인전문(시각디자인) / 9999: 기타자유업종

# ─── 자격 검증 API 엔드포인트 ────────────────────────────────────────────────
G2B_ELIGIBILITY_APIS = {
    "region":  "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoPrtcptPsblRgn",
    "license": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoLicenseLimit",
}


# =============================================================================
# ★ v8.4 핵심 추가: WKMG 입찰 자격 사전 검증
# =============================================================================

def check_voluntary_contract(item: dict) -> str | None:
    """
    수의계약 여부 확인 — API 응답 필드에서 직접 확인.
    나라장터 API 응답에 cntrctCnclsMthdNm(계약체결방법명), sucsfbidMthdNm(낙찰방법명) 포함.
    '수의' 단어 포함 시 제외 사유 반환.
    """
    contract_method = str(item.get("cntrctCnclsMthdNm", "") or "")
    bid_method      = str(item.get("sucsfbidMthdNm",    "") or "")
    combined = contract_method + bid_method

    if "수의" in combined:
        return f"수의계약({contract_method.strip() or bid_method.strip()})"
    return None


def check_direct_production_cert(item: dict) -> str | None:
    """
    직접생산확인증명서 조건 여부 — 공고명에서 패턴 감지 (빠른 1차 필터).
    실제 공고문 파싱은 spd_auto_fetch 단계에서 수행하므로,
    여기서는 공고명에 '직접생산' 텍스트가 있으면 우선 배제.
    """
    title = str(item.get("bidNtceNm", "") or "")
    if "직접생산" in title:
        return "직접생산확인증명서조건"
    return None


def check_region_eligibility(bid_no: str, service_key: str, timeout: int = 10) -> str | None:
    """
    지역제한 API 호출 — 서울 포함 여부 확인.
    prtcptPsblRgnNm(참가가능지역명)이 '서울특별시' 또는 '전국' 포함 시 통과.
    API 오류 시 통과로 처리 (보수적 접근: 놓치는 것보다 검토 기회 보존).

    Returns:
        None   → 통과 (입찰 가능)
        str    → 제외 사유 문자열
    """
    params = {
        "serviceKey": service_key,
        "pageNo": "1", "numOfRows": "10",
        "type": "json", "inqryDiv": "2",
        "bidNtceNo": bid_no,
    }
    try:
        resp = requests.get(
            G2B_ELIGIBILITY_APIS["region"],
            params=params, timeout=timeout, verify=False
        )
        if resp.status_code != 200:
            return None  # API 오류 → 통과 처리

        data = resp.json()
        body = data.get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0))

        if total == 0:
            return None  # 지역제한 없음 → 통과

        items_raw = body.get("items", [])
        if isinstance(items_raw, dict):
            items_raw = items_raw.get("item", [])
        if isinstance(items_raw, dict):
            items_raw = [items_raw]

        regions = [
            str(it.get("prtcptPsblRgnNm", "") or "")
            for it in (items_raw if isinstance(items_raw, list) else [])
        ]

        # 서울 또는 전국이 포함된 항목이 하나라도 있으면 통과
        for rgn in regions:
            if "서울" in rgn or "전국" in rgn:
                return None

        region_str = ", ".join(r for r in regions if r)[:60]
        return f"지역제한({region_str or '서울외'})"

    except Exception:
        return None  # 오류 → 통과 처리 (보수적)


def check_license_eligibility(bid_no: str, service_key: str, timeout: int = 10) -> str | None:
    """
    업종제한 API 호출 — WKMG 허용 업종 포함 여부 확인.
    허용업종 목록(permsnIndstrytyList)에서:
      - 목록이 없으면 → 통과 (업종제한 없음)
      - WKMG 코드{1169, 4440, 9999} 중 하나라도 있으면 → 통과
      - 해당 코드가 전혀 없고 다른 코드만 있으면 → 제외

    Returns:
        None   → 통과
        str    → 제외 사유
    """
    params = {
        "serviceKey": service_key,
        "pageNo": "1", "numOfRows": "50",
        "type": "json", "inqryDiv": "2",
        "bidNtceNo": bid_no,
    }
    try:
        resp = requests.get(
            G2B_ELIGIBILITY_APIS["license"],
            params=params, timeout=timeout, verify=False
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        body = data.get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0))

        if total == 0:
            return None  # 업종제한 없음 → 통과

        items_raw = body.get("items", [])
        if isinstance(items_raw, dict):
            items_raw = items_raw.get("item", [])
        if isinstance(items_raw, dict):
            items_raw = [items_raw]

        if not isinstance(items_raw, list):
            return None

        allowed_codes = set()
        for it in items_raw:
            code = str(it.get("indstrytyNm", "") or "").strip()
            # 응답 필드명이 다를 수 있음 — 여러 필드명 시도
            if not code:
                code = str(it.get("indstrytyCd", "") or "").strip()
            if not code:
                code = str(it.get("prtcptLmtIndstryNm", "") or "").strip()
            if code:
                # 코드 숫자 부분만 추출 (예: "9999(기타자유업종)" → "9999")
                num_match = re.search(r'\d{4}', code)
                if num_match:
                    allowed_codes.add(num_match.group())
                else:
                    allowed_codes.add(code)

        if not allowed_codes:
            return None  # 코드 파싱 불가 → 통과 처리

        # WKMG 코드가 하나라도 포함되어 있으면 통과
        if allowed_codes & WKMG_ALLOWED_INDUSTRY_CODES:
            return None

        # WKMG 코드가 전혀 없음 → 제외
        other_codes = allowed_codes - WKMG_ALLOWED_INDUSTRY_CODES
        return f"업종제한({', '.join(sorted(other_codes)[:3])})"

    except Exception:
        return None  # 오류 → 통과 처리


def verify_eligibility(item: dict, service_key: str = "", run_api_check: bool = True) -> str | None:
    """
    WKMG 입찰 자격 통합 검증 (스코어링 전 실행).

    검증 순서 (빠른 것 → 느린 것):
      1. 수의계약 여부 (필드 직접 확인, 즉시)
      2. 직접생산확인증명서 조건 (공고명 패턴, 즉시)
      3. 지역제한 API (bid_no 있는 경우, ~100ms)
      4. 업종제한 API (bid_no 있는 경우, ~100ms)

    Args:
        item: 공고 딕셔너리
        service_key: 나라장터 API 서비스키 (API 검증용)
        run_api_check: False이면 API 호출 없이 필드 검증만

    Returns:
        None  → 자격 있음 (통과)
        str   → 제외 사유 (예: "수의계약(수의시담)", "지역제한(경기도)", "업종제한(4444)")
    """
    # 1. 수의계약 즉시 확인
    reason = check_voluntary_contract(item)
    if reason:
        return reason

    # 2. 직접생산확인증명서 즉시 확인
    reason = check_direct_production_cert(item)
    if reason:
        return reason

    # 3~4. API 검증 (bid_no 있는 경우만)
    if not run_api_check or not service_key:
        return None

    bid_no = str(item.get("bidNtceNo", "") or "").strip()
    if not bid_no:
        return None  # 직접크롤링 공고 등 bid_no 없음 → API 생략

    # 3. 지역제한
    reason = check_region_eligibility(bid_no, service_key)
    if reason:
        return reason

    # 4. 업종제한
    reason = check_license_eligibility(bid_no, service_key)
    if reason:
        return reason

    return None  # 모든 검증 통과


# =============================================================================
# ★ v8.4: 예산 필드 개선 + 자격검증 통합 메인 함수 오버라이드
# =============================================================================

def get_budget(item: dict) -> int:
    """
    예산 추출 개선 (이세민 의견):
    asignBdgtAmt(배정예산금액) 우선 — 사업금액과 동일하게 산출됨
    presmptPrce(추정가격) 보조 — 부가세·조달수수료 제외된 금액이므로 보조만
    """
    # 우선: asignBdgtAmt
    assign = item.get("asignBdgtAmt", "") or ""
    try:
        val = int(float(str(assign).replace(",", "")))
        if val > 0:
            return val
    except (ValueError, TypeError):
        pass

    # 보조: presmptPrce
    presm = item.get("presmptPrce", "") or item.get("budget_raw", "") or "0"
    try:
        return int(float(str(presm).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def main():
    """v8.4 메인 — 자격 검증 단계 추가"""
    print("\n" + "=" * 70)
    print(f"  🚀 RFP Radar v{VERSION} — 입찰 자격 검증 강화")
    print("=" * 70 + "\n")

    start_time = time.time()
    service_key = CONFIG.get("service_key", "")

    # ── 1. 수집 ──────────────────────────────────────────────────────────────
    items = fetch_all_bids()
    if not items:
        print("❌ 데이터 없음")
        return

    g2b_count    = sum(1 for x in items if x.get('_source') == '나라장터')
    direct_count = sum(1 for x in items if '직접' in str(x.get('_source', '')))

    # ── 2. 스코어링 + 자격 검증 ───────────────────────────────────────────────
    print(f"\n  🎯 스코어링 + 자격 검증 ({len(items):,}건)...")
    scored = []
    stats = {
        "total": len(items), "excluded": 0, "matched": 0,
        "grades": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
        "g2b_count": g2b_count, "direct_count": direct_count,
        # v8.4 추가 통계
        "eligibility_excluded": 0,
        "eligibility_detail": {
            "수의계약": 0, "지역제한": 0, "업종제한": 0,
            "직접생산": 0, "기타": 0,
        },
    }

    for i, item in enumerate(items):
        if (i + 1) % 1000 == 0:
            print(f"  ⏳ {i+1:,}/{len(items):,}")

        # ── 2-1. 기존 스코어링 (v83과 동일) ─────────────────────────────────
        # 예산 필드 개선: asignBdgtAmt 우선 반영
        item['_budget_v84'] = get_budget(item)

        score = calculate_score(item)

        budget = item.get('_budget_v84', 0)
        try:
            budget_str = f"{budget // 10000:,}만원" if budget > 0 else "미정"
        except Exception:
            budget_str = "미정"

        bid_no  = item.get('bidNtceNo', '')
        bid_seq = item.get('bidNtceOrd', '00')
        if bid_no:
            url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={bid_no}&bidPbancOrd={bid_seq}"
        else:
            url = item.get('_url', '')

        scored_item = {
            "title":    item.get('bidNtceNm', ''),
            "agency":   item.get('ntceInsttNm', ''),
            "budget":   budget_str,
            "deadline": (item.get('bidClseDt', '') or '')[:10],
            "bid_no":   bid_no,
            "source":   item.get('_source', ''),
            "url":      url,
            "score":    score,
            # v8.4: 자격 검증 결과 (아직 미실행)
            "eligibility_ok":     True,
            "eligibility_reason": None,
        }

        stats["grades"][score["grade"]] += 1
        if score["exclusion_reason"]:
            stats["excluded"] += 1
        if score["matched_domain"]:
            stats["matched"] += 1

        # ── 2-2. v8.4 자격 검증 ──────────────────────────────────────────────
        # 대상: 키워드 매칭된 공고(is_relevant) 중 수의계약/직접생산은 전건,
        #       지역/업종 API는 S/A 후보(점수 ≥ 55)에만 → API 비용 절약
        if score.get("is_relevant"):
            # 수의계약·직접생산: 전건 즉시 확인 (API 불필요)
            fast_reason = check_voluntary_contract(item) or check_direct_production_cert(item)
            if fast_reason:
                scored_item["eligibility_ok"]     = False
                scored_item["eligibility_reason"] = fast_reason
                scored_item["score"]["exclusion_reason"] = fast_reason
                stats["eligibility_excluded"] += 1
                key = "수의계약" if "수의" in fast_reason else "직접생산"
                stats["eligibility_detail"][key] = stats["eligibility_detail"].get(key, 0) + 1
            elif score["total"] >= 55 and bid_no:
                # API 검증 (S/A/B 후보만)
                api_reason = check_region_eligibility(bid_no, service_key) or \
                             check_license_eligibility(bid_no, service_key)
                if api_reason:
                    scored_item["eligibility_ok"]     = False
                    scored_item["eligibility_reason"] = api_reason
                    scored_item["score"]["exclusion_reason"] = api_reason
                    stats["eligibility_excluded"] += 1
                    if "지역" in api_reason:
                        stats["eligibility_detail"]["지역제한"] += 1
                    elif "업종" in api_reason:
                        stats["eligibility_detail"]["업종제한"] += 1
                    else:
                        stats["eligibility_detail"]["기타"] += 1

        scored.append(scored_item)

    # ── 3. GPT 2단계 평가 (자격 통과한 건만) ──────────────────────────────────
    eligible_scored = [x for x in scored if x["eligibility_ok"]]
    if CONFIG.get("use_gpt"):
        eligible_scored = apply_gpt_evaluation(eligible_scored)
        # 자격 미달 건은 GPT 평가 없이 원래 점수 유지
        ineligible = [x for x in scored if not x["eligibility_ok"]]
        scored = eligible_scored + ineligible
        # 등급 통계 재집계
        stats["grades"] = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for item in scored:
            stats["grades"][item["score"]["grade"]] += 1

    # ── 4. 결과 출력 ───────────────────────────────────────────────────────────
    print(f"\n  📊 결과: 총 {stats['total']:,}건, 매칭 {stats['matched']:,}건")
    print(f"  🚫 자격제한 제외: {stats['eligibility_excluded']}건")
    for k, v in stats["eligibility_detail"].items():
        if v > 0:
            print(f"     - {k}: {v}건")
    for g in ["S", "A", "B", "C"]:
        print(f"    {g}: {stats['grades'].get(g, 0)}건")

    today_str = datetime.now().strftime("%Y-%m-%d")
    def is_not_expired(x):
        dl = x.get("deadline", "")
        return not dl or dl >= today_str

    def is_eligible(x):
        return x.get("eligibility_ok", True)

    # 자격 통과 + 미만료 공고만 추천 대상
    all_recommend = sorted(
        [x for x in scored if x["score"]["grade"] in ["S", "A", "B"]
         and is_not_expired(x) and is_eligible(x)],
        key=lambda x: -x["score"]["total"]
    )
    candidates = sorted(
        [x for x in scored if x["score"]["grade"] in ["S", "A", "B", "C"]
         and is_not_expired(x) and is_eligible(x)],
        key=lambda x: -x["score"]["total"]
    )

    def get_budget_value(item):
        budget_str = item.get("budget", "")
        if "미정" in budget_str:
            return 0
        try:
            num = int(budget_str.replace(",", "").replace("만원", ""))
            return num * 10000
        except Exception:
            return 0

    PRIORITY_BUDGET = 50000000
    recommend = [x for x in all_recommend if get_budget_value(x) >= PRIORITY_BUDGET or get_budget_value(x) == 0]
    quick_win = [x for x in all_recommend if 0 < get_budget_value(x) < PRIORITY_BUDGET]

    print(f"\n  🏆 우선추천: {len(recommend)}건 | 💡 저예산 Quick Win: {len(quick_win)}건 | 후보: {len(candidates)}건")

    for i, item in enumerate(recommend[:10], 1):
        s = item["score"]
        elig = "" if item.get("eligibility_ok", True) else " ⛔"
        src  = " 🌐" if "직접" in item.get("source", "") else ""
        print(f"  {i}. [{s['grade']}/{s['total']:.0f}점] {item['title'][:40]}{src}{elig}")

    # ── 5. 저장 ────────────────────────────────────────────────────────────────
    os.makedirs(CONFIG["data_dir"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    with open(os.path.join(CONFIG["data_dir"], f"v84_recommend_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump(recommend + quick_win, f, ensure_ascii=False, indent=2)
    with open(os.path.join(CONFIG["data_dir"], f"v84_candidates_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    # ── 6. 이메일 발송 ─────────────────────────────────────────────────────────
    if CONFIG.get("send_email") and CONFIG.get("sender_password"):
        print(f"\n  📧 이메일 발송 중...")
        send_email_report(recommend, candidates, stats, quick_win=quick_win)
    else:
        print(f"\n  ⚠️ 이메일 발송 생략")

    elapsed = time.time() - start_time
    print(f"\n  ✅ 완료: {elapsed:.1f}초")
    print(f"  v8.4 자격검증 제외: {stats['eligibility_excluded']}건 추가 차단")


if __name__ == "__main__":
    main()
