#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Prompts v3.0 — 과업지시서 심층분석 + JSON 출력 강제 + Winning Playbook 연동
================================================================================
v2 대비 핵심 변경:
  1. JSON 출력 강제 — response_format={"type":"json_object"} 완전 호환
  2. 과업지시서 세부 산출물 추출 — deliverables_analysis 섹션 신규
  3. 구체적 채점 루브릭 — 4영역 × 25점, 5단계 상세 기준 (동점 방지)
  4. Winning Playbook 자동 연동 — get_playbook_summary_for_prompt() 호출
  5. 함수 시그니처 통일 — build_analysis_prompt_v3(bid_result, rfp_text, similar_projects)
  6. 유사 프로젝트 구체적 포맷 — 파일명, 연도, 발주기관, 유사도 모두 표시

Usage:
  from spd_prompts_v3 import SYSTEM_PROMPT_V3, build_analysis_prompt_v3
  prompt = build_analysis_prompt_v3(bid_result, rfp_text, similar_projects)

Author: WKMG Automation (SPD System)
Version: 3.0.0
"""

import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Winning Playbook 연동 (있으면 사용, 없으면 빈 값)
# ---------------------------------------------------------------------------
try:
    from wkmg_winning_playbook import (
        get_matching_patterns,
        get_client_strategy,
        get_pricing_strategy,
        get_applicable_risks,
        get_playbook_summary_for_prompt,
    )
    PLAYBOOK_AVAILABLE = True
except ImportError:
    PLAYBOOK_AVAILABLE = False


# ============================================================
# v3 시스템 프롬프트
# ============================================================

SYSTEM_PROMPT_V3 = """당신은 WKMG(더블유케이마케팅그룹)의 B2G 입찰 전략 수석 분석가입니다.

## WKMG 프로필
- 16년차 B2G/B2B 마케팅 컨설팅 전문기업
- B2B 대기업 17개사 브랜드전략 수행 (LG전자, 롯데웰푸드, 정관장, 풀무원, 오리온, 삼성 등)
- B2G 6대 핵심 도메인에서 113건+ 프로젝트 수행
- 사회적기업 유통채널 진출 지원 7년 연속 수주 (2018~2024)

## 6대 핵심 도메인 및 강점 등급
| 도메인 | 등급 | 대표실적 |
|--------|------|----------|
| D1. 사회적기업 지원 | S (최강) | 진흥원 7년연속, 유통채널진출, 사회적가치 측정 |
| D2. 농식품 마케팅 | A (주력) | 농업기술실용화재단, 6차산업, 제품마켓테스트 |
| D3. 지역브랜드 개발 | A (주력) | 7개 시군 브랜드/특산물 (고성/진안/포천/홍성/군산/화성) |
| D4. 공공기관 브랜드 | B+ | 아리수 홍보전략, 대구시 도시브랜드, 저탄소인증 |
| D5. 관광/문화 마케팅 | B | 한국관광공사, 의료관광, 한식세계화 |
| D6. 중소기업 유통지원 | A (주력) | 중소기업유통센터, 디지털마케팅, 홈쇼핑 |

## 핵심 차별화 포지션
"B2B 대기업 브랜드전략 + B2G 16년 정책사업 = 대한민국 유일한 포지션"

## 분석 원칙
- 근거 없는 낙관적 평가 절대 금지
- 과업지시서의 세부 산출물을 하나하나 추출하여 WKMG 역량과 대조
- 유사 프로젝트는 구체적 프로젝트명으로 언급
- 경쟁 환경을 반드시 고려
- JSON 형식으로만 출력 (마크다운 금지)"""


# ============================================================
# 채점 루브릭 (프롬프트에 삽입)
# ============================================================

SCORING_RUBRIC = """
## 채점 루브릭 (4영역 × 25점 = 100점)

### 영역 1: 도메인 전문성 (/25)
- 22~25: WKMG S등급 도메인 직접 매칭 (사회적기업 유통지원, 농식품 사업화 등)
- 17~21: A등급 도메인 매칭 (유통채널, 지역브랜드, 중소기업 마케팅)
- 12~16: B등급 도메인 부분 매칭 (공공홍보, 관광문화) 또는 크로스도메인
- 7~11: 관련은 있으나 WKMG 직접 경험 부족한 분야
- 0~6: WKMG 전문영역과 거리가 멈 (IT개발, 건설, 법률 등)

### 영역 2: 수행실적 매칭 (/25)
- 22~25: 동일 사업 수행 이력 (같은 발주기관 + 같은 사업)
- 17~21: 유사 사업 수행 (같은 유형, 다른 발주기관 또는 같은 발주기관 다른 사업)
- 12~16: 관련 분야 수행 (산출물 50% 이상 유사)
- 7~11: 간접적 관련 실적만 (산출물 30% 미만 유사)
- 0~6: 관련 실적 거의 없음

### 영역 3: 경쟁우위 (/25)
- 22~25: 재수주 또는 독점적 우위 (기존 관계 + 압도적 실적)
- 17~21: 강한 차별화 (B2B+B2G 복합, 풀밸류체인)
- 12~16: 보통 경쟁력 (유사 수준 경쟁사 2~3개)
- 7~11: 약한 경쟁력 (경쟁사가 더 적합한 실적 보유)
- 0~6: 경쟁우위 없음 (대형사/전문사에 밀림)

### 영역 4: 수주 가능성 (/25)
- 22~25: 거의 확실 (재수주, 압도적 실적, 관계)
- 17~21: 높음 (강한 실적, 유리한 조건, 경쟁 약함)
- 12~16: 보통 (경쟁 치열, 50:50)
- 7~11: 낮음 (약점 다수, 지역제한, 실적 미달 등)
- 0~6: 매우 낮음 (자격요건 미충족, 전문분야 불일치)

### Go/No-Go 판정 기준
- **GO** (75점 이상): 적극 참여
- **CONDITIONAL** (55~74점): 조건부 참여 (조건 충족 시 GO)
- **NO-GO** (54점 이하): 불참 추천
"""


# ============================================================
# JSON 출력 스키마 (프롬프트에 삽입)
# ============================================================

JSON_SCHEMA = """
## 반드시 아래 JSON 구조로만 출력하세요 (마크다운 금지, 설명 금지)

```json
{
  "basic_info": {
    "title": "공고명",
    "bid_type": "A~H형 중 택1",
    "bid_type_reason": "유형 분류 근거 (1줄)",
    "eval_method": "기술평가/적격심사/종합평가 등",
    "summary": "핵심 목적과 요구사항 요약 (2~3줄)"
  },
  "deliverables_analysis": {
    "total_deliverables": 0,
    "items": [
      {
        "deliverable": "과업지시서에 명시된 세부 산출물/과업명",
        "wkmg_capability": "상/중/하",
        "capability_reason": "판단 근거 — WKMG의 실제 수행 프로젝트명과 연결하여 설명",
        "needs_partner": false,
        "partner_type": "필요시 파트너 유형 (디자인사/영상제작사/IT업체 등)"
      }
    ],
    "wkmg_coverage_pct": 0,
    "coverage_summary": "자체 수행 가능 비율과 종합 판단"
  },
  "scoring": {
    "domain_expertise": {"score": 0, "max": 25, "reason": "채점 루브릭에 따른 구체적 근거"},
    "track_record": {"score": 0, "max": 25, "reason": "어떤 유사 프로젝트가 있는지 구체적으로"},
    "competitive_edge": {"score": 0, "max": 25, "reason": "경쟁사 대비 우위/열위 구체적으로"},
    "win_probability": {"score": 0, "max": 25, "reason": "종합적 수주 확률과 근거"},
    "total_score": 0
  },
  "go_no_go": {
    "decision": "GO / CONDITIONAL / NO-GO",
    "decision_reason": "판정의 핵심 근거 (2~3줄)",
    "conditions": ["CONDITIONAL일 때: 충족 필요 조건들"],
    "nogo_reasons": ["NO-GO일 때: 불참 사유들"]
  },
  "strategy": {
    "core_message": "제안서 핵심 메시지 (1줄)",
    "top3_emphasis": ["제안서에서 반드시 강조할 3가지"],
    "evaluator_concerns": ["평가위원이 우려할 수 있는 약점 2가지"],
    "concern_countermeasures": ["약점별 대응 방안"],
    "needed_partners": ["필요한 외부 파트너 (유형+역할)"],
    "proposal_pages": "예상 제안서 분량",
    "prep_days": 14,
    "action_items": [
      {
        "action": "구체적 행동",
        "priority": "HIGH/MEDIUM/LOW",
        "deadline": "시점",
        "owner": "PM/영업팀/디자인팀 등"
      }
    ]
  },
  "similar_projects_assessment": {
    "best_match": "가장 유사한 WKMG 과거 프로젝트명과 유사 이유",
    "reusable_assets": ["재활용 가능한 기존 자산/자료"],
    "gap_from_past": "과거 프로젝트 대비 새로운 요구사항"
  },
  "competitive_landscape": {
    "likely_competitors": [
      {
        "type": "경쟁사 유형",
        "strength": "그들의 강점",
        "wkmg_counter": "WKMG 대응 전략"
      }
    ],
    "wkmg_unique_selling_point": "최종 차별화 포인트"
  }
}
```

### 중요 규칙
1. 반드시 위 JSON 구조를 완전히 채워서 출력하세요
2. deliverables_analysis.items에는 과업지시서/제안요청서에서 추출한 모든 세부 과업/산출물을 나열하세요
3. 채점은 반드시 루브릭 기준에 따라 — 모든 공고에 동일 점수 부여 금지
4. 유사 프로젝트는 ChromaDB 매칭 결과의 구체적 파일명/프로젝트명을 사용하세요
5. JSON만 출력 — 앞뒤에 설명, 마크다운 코드블록(```) 포함 금지
"""


# ============================================================
# 입찰유형 분류 기준
# ============================================================

BID_TYPE_CRITERIA = """
## 입찰유형 분류 기준
**[A형] 브랜드/전략 수립** — BI, CI, 브랜드전략, 마케팅전략 수립
**[B형] 조사/분석** — 시장조사, 실태조사, 만족도조사, 정책연구
**[C형] 유통/판로 지원** — 유통채널 진출, 판로개척, 마케팅지원 사업
**[D형] 종합 컨설팅** — 중장기 계획, 종합전략, 마스터플랜
**[E형] 홍보/콘텐츠** — 홍보영상, 콘텐츠제작, SNS운영, 광고, 캠페인
**[F형] 교육/역량강화** — 교육프로그램, 멘토링, 컨설팅 지원
**[G형] 행사/이벤트** — 박람회, 전시회, 페스티벌 운영
**[H형] 기타/복합** — 위 유형 복합 또는 분류 어려운 경우
"""


# ============================================================
# 헬퍼: 예산 문자열 파싱
# ============================================================

def _parse_budget(budget_str: str) -> int:
    """예산 문자열 → 원(int) 변환"""
    if not budget_str:
        return 0
    s = budget_str.replace(",", "").replace(" ", "")
    try:
        # "22,948만원" → 229480000
        m = re.search(r"([\d.]+)\s*만\s*원", s)
        if m:
            return int(float(m.group(1)) * 10_000)
        # "5억원" → 500000000
        m = re.search(r"([\d.]+)\s*억\s*원?", s)
        if m:
            return int(float(m.group(1)) * 100_000_000)
        # 순수 숫자
        m = re.search(r"(\d+)", s)
        if m:
            return int(m.group(1))
    except:
        pass
    return 0


# ============================================================
# 메인 프롬프트 빌더
# ============================================================

def build_analysis_prompt_v3(
    bid_result: Dict,
    rfp_text: str,
    similar_projects: List[Dict]
) -> str:
    """
    SPD v3.0 분석 프롬프트 생성.
    
    Args:
        bid_result: auto_fetch 결과 dict
            - title, agency, budget_str, bid_no, grade 등
        rfp_text: 첨부파일에서 추출한 RFP/과업지시서 전문
        similar_projects: ChromaDB 매칭 결과 리스트
            - 각 항목: {filename, similarity, year, client, domain, category, preview}
    
    Returns:
        GPT-4o에 전송할 분석 프롬프트 문자열 (JSON 출력 강제)
    """
    title = bid_result.get("title", "")
    agency = bid_result.get("agency", "")
    budget_str = bid_result.get("budget_str", "")
    bid_no = bid_result.get("bid_no", "")
    grade = bid_result.get("grade", "")
    
    parts = []
    
    # ── 1. 공고 기본 정보 ──
    parts.append(f"""## 분석 대상 공고
- 공고명: {title}
- 발주기관: {agency}
- 추정예산: {budget_str}
- 공고번호: {bid_no}
- RFP Radar 등급: {grade}
""")
    
    # ── 2. RFP/과업지시서 전문 ──
    max_chars = 20000
    if rfp_text:
        truncated = rfp_text[:max_chars]
        if len(rfp_text) > max_chars:
            truncated += f"\n\n... (원문 {len(rfp_text):,}자 중 {max_chars:,}자만 포함)"
        parts.append(f"""## RFP 원문 (첨부파일 추출 — 과업지시서/제안요청서)

아래 텍스트에서 모든 세부 과업, 산출물, 평가기준을 빠짐없이 추출하세요.

{truncated}
""")
    else:
        parts.append("## RFP 원문\n(첨부파일 텍스트 없음 — 공고 제목과 기본 정보만으로 분석)\n")
    
    # ── 3. Winning Playbook 자동 연동 ──
    playbook_section = ""
    if PLAYBOOK_AVAILABLE and rfp_text:
        budget_won = _parse_budget(budget_str)
        try:
            playbook_summary = get_playbook_summary_for_prompt(
                rfp_text[:3000], agency, budget_won
            )
            if playbook_summary:
                playbook_section = f"""
## WKMG 승리 공식 (Winning Playbook 자동 매칭)
아래는 WKMG의 16년 실적 DB에서 이 공고와 가장 잘 매칭되는 승리 전략입니다.
분석 시 이 정보를 적극 활용하세요.

{playbook_summary}
"""
        except Exception:
            pass
    
    if playbook_section:
        parts.append(playbook_section)
    
    # ── 4. 유사 프로젝트 (ChromaDB 매칭) ──
    if similar_projects:
        sp_lines = ["## WKMG 유사 수행 실적 (ChromaDB 매칭)\n"]
        sp_lines.append("아래 프로젝트를 참조하여 수행실적 매칭 점수를 채점하고,")
        sp_lines.append("similar_projects_assessment에서 구체적으로 언급하세요.\n")
        
        for i, sp in enumerate(similar_projects[:7], 1):
            sim = sp.get("similarity", 0)
            sim_pct = f"{sim:.0%}" if isinstance(sim, float) else str(sim)
            filename = sp.get("filename", "unknown")
            year = sp.get("year", "?")
            client = sp.get("client", "?")
            domain = sp.get("domain", "?")
            category = sp.get("category", "?")
            b2g_b2b = sp.get("b2g_b2b", "?")
            preview = sp.get("preview", "")[:200]
            
            sp_lines.append(
                f"  {i}. **[{year}] {filename}**\n"
                f"     유사도: {sim_pct} | 분야: {domain} | 유형: {category} | "
                f"발주: {client} | B2G/B2B: {b2g_b2b}\n"
                f"     내용 미리보기: {preview}\n"
            )
        
        parts.append("\n".join(sp_lines))
    else:
        parts.append("## WKMG 유사 수행 실적\n(ChromaDB 매칭 결과 없음)\n")
    
    # ── 5. 분석 지시사항 + 채점 루브릭 + JSON 스키마 ──
    parts.append(BID_TYPE_CRITERIA)
    parts.append(SCORING_RUBRIC)
    parts.append(JSON_SCHEMA)
    
    return "\n\n---\n\n".join(parts)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("SPD Prompts v3.0 — 프롬프트 생성 테스트")
    print("=" * 60)
    
    # 테스트 bid_result
    test_bid = {
        "title": "2026년 사회적경제기업 온라인 유통채널 진출 지원사업",
        "agency": "한국사회적기업진흥원",
        "budget_str": "50,000만원",
        "bid_no": "R26TEST001",
        "grade": "S",
    }
    
    test_rfp = """1. 사업 개요: 사회적기업의 온라인 유통채널 입점 및 마케팅 지원
2. 세부 과업:
   가. 수혜기업 선정 및 진단 컨설팅
   나. 온라인 유통채널 입점 지원 (카카오스토어, 네이버 스마트스토어)
   다. 상품 상세페이지 제작 (30개사)
   라. SNS 마케팅 콘텐츠 제작 (인스타그램, 유튜브)
   마. 온라인 판매 촉진 캠페인 (라이브커머스 포함)
   바. 수혜기업 역량강화 교육 (4회)
   사. 성과분석 보고서
3. 산출물: 진단보고서, 입점결과보고서, 상세페이지 30건, 콘텐츠 120건, 최종보고서"""
    
    test_similar = [
        {
            "filename": "2024_사회적기업_유통채널진출_지원사업_제안서.pdf",
            "similarity": 0.92,
            "year": "2024",
            "client": "한국사회적기업진흥원",
            "domain": "D1_사회적기업",
            "category": "유통지원",
            "b2g_b2b": "B2G",
            "preview": "사회적기업의 온라인 유통채널 입점 및 마케팅 지원을 통한 매출 증대..."
        },
        {
            "filename": "2023_중소기업_디지털마케팅_지원사업.pdf",
            "similarity": 0.78,
            "year": "2023",
            "client": "중소기업유통센터",
            "domain": "D6_중소기업유통",
            "category": "디지털마케팅",
            "b2g_b2b": "B2G",
            "preview": "중소기업 디지털 마케팅 역량 강화 및 온라인 유통 지원..."
        }
    ]
    
    prompt = build_analysis_prompt_v3(test_bid, test_rfp, test_similar)
    
    print(f"✅ 프롬프트 생성 완료")
    print(f"   길이: {len(prompt):,}자")
    print(f"   Winning Playbook: {'연동됨' if PLAYBOOK_AVAILABLE else '미연동'}")
    print(f"\n--- 프롬프트 미리보기 (앞 800자) ---")
    print(prompt[:800])
    print(f"\n--- 프롬프트 끝부분 (마지막 500자) ---")
    print(prompt[-500:])
