#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Prompts v2.0 — WKMG 16년 실적 기반 고도화 분석 프롬프트
=============================================================
Chain-of-Thought 분석, 입찰유형 분류, 평가위원 시뮬레이션을 포함한
GPT-4o 분석 프롬프트 생성 모듈.

from spd_prompts_v2 import build_analysis_prompt_v2
prompt = build_analysis_prompt_v2(rfp_title, rfp_text, agency, budget)

Author: WKMG Automation (SPD System)
Version: 2.0.0
"""

# ============================================================
# WKMG 핵심 역량 요약 (프롬프트 내장)
# ============================================================

WKMG_PROFILE = """
## WKMG(더블유케이마케팅그룹) 핵심 프로필
- 설립 16년차 B2G/B2B 마케팅 컨설팅 전문기업
- B2B 대기업 17개사 브랜드전략 (LG전자, 롯데웰푸드, 정관장, 풀무원, 오리온 등)
- B2G 6대 전문 도메인에서 113건+ 프로젝트 수행

### 6대 도메인 역량
| 도메인 | 강점 | 대표실적 |
|--------|------|----------|
| D1. 사회적기업 지원 | ★★★★★ | 진흥원 7년연속 수주, 유통채널진출 지원 |
| D2. 농식품 마케팅 | ★★★★☆ | 농업기술실용화재단, 6차산업 사업화 |
| D3. 지역브랜드 개발 | ★★★★☆ | 7개 시군 브랜드/특산물 개발 |
| D4. 공공기관 브랜드 | ★★★☆☆ | 아리수 홍보전략, 대구시 도시브랜드 |
| D5. 관광/문화 마케팅 | ★★★☆☆ | 한국관광공사, 의료관광 마케팅 |
| D6. 중소기업 유통지원 | ★★★★☆ | 중소기업유통센터, 디지털마케팅 지원 |

### 핵심 차별화
- B2B 대기업 브랜드전략 + B2G 정책사업 경험 = 대한민국 유일한 포지션
- 브랜드전략→상품기획→유통진출→디지털마케팅 풀밸류체인 원스톱 서비스
"""

# ============================================================
# 입찰유형 분류 기준
# ============================================================

BID_TYPE_CRITERIA = """
## 입찰유형 분류 기준
다음 기준으로 입찰유형을 분류하세요:

**[A형] 브랜드/전략 수립** — BI, CI, 브랜드전략, 마케팅전략 수립
**[B형] 조사/분석** — 시장조사, 실태조사, 만족도조사, 정책연구
**[C형] 유통/판로 지원** — 유통채널 진출, 판로개척, 마케팅지원 사업
**[D형] 종합 컨설팅** — 중장기 계획, 종합전략, 마스터플랜
**[E형] 홍보/콘텐츠** — 홍보영상, 콘텐츠제작, SNS운영, 광고
**[F형] 교육/역량강화** — 교육프로그램, 멘토링, 컨설팅 지원
**[G형] 행사/이벤트** — 박람회, 전시회, 페스티벌 운영
**[H형] 기타/복합** — 위 유형 복합 또는 분류 어려운 경우
"""


# ============================================================
# 분석 프롬프트 빌더
# ============================================================

def build_analysis_prompt_v2(
    rfp_title: str,
    rfp_text: str,
    agency: str = "",
    budget: int = 0,
    playbook_context: str = "",
    similar_projects: str = ""
) -> str:
    """
    SPD v2.0 분석 프롬프트 생성.
    
    Args:
        rfp_title: 공고 제목
        rfp_text: 공고 본문/첨부파일 텍스트 (최대 8000자)
        agency: 발주기관명
        budget: 예산 (원)
        playbook_context: wkmg_winning_playbook에서 생성한 전략 컨텍스트
        similar_projects: ChromaDB에서 매칭된 유사 프로젝트 요약
    
    Returns:
        GPT-4o에 전송할 분석 프롬프트 문자열
    """
    
    budget_display = ""
    if budget > 0:
        if budget >= 100_000_000:
            budget_display = f"{budget / 100_000_000:.1f}억원"
        else:
            budget_display = f"{budget / 10_000:.0f}만원"
    
    # RFP 텍스트 길이 제한
    rfp_excerpt = rfp_text[:8000] if len(rfp_text) > 8000 else rfp_text
    
    prompt = f"""당신은 B2G(정부조달) 입찰 전략 전문가입니다. 
아래 공고를 WKMG(더블유케이마케팅그룹)의 관점에서 정밀 분석해주세요.

{WKMG_PROFILE}

{BID_TYPE_CRITERIA}

---
## 분석 대상 공고

**공고명**: {rfp_title}
**발주기관**: {agency if agency else '미확인'}
**예산규모**: {budget_display if budget_display else '미확인'}

### 공고 본문/과업지시서 (발췌)
{rfp_excerpt}

"""
    
    # Playbook 컨텍스트 추가
    if playbook_context:
        prompt += f"""
---
## WKMG 승리 공식 (자동 매칭)
{playbook_context}

"""
    
    # 유사 프로젝트 추가
    if similar_projects:
        prompt += f"""
---
## WKMG 유사 수행 실적 (ChromaDB 매칭)
{similar_projects}

"""
    
    # Chain-of-Thought 분석 지시
    prompt += """
---
## 분석 지시사항 (Chain-of-Thought)

다음 단계를 순서대로 수행하고, 각 단계의 사고과정을 명시하세요:

### STEP 1: 공고 기본 파악
- 사업 목적과 핵심 과업 요약 (3줄 이내)
- 입찰유형 분류 (A~H형 중 택1, 복합이면 H형)
- 예상 평가 방식 (기술평가/적격심사/종합평가 등)

### STEP 2: WKMG 적합도 평가 (100점 만점)
다음 4개 영역을 각 25점 만점으로 채점하세요:

| 영역 | 기준 | 점수(/25) |
|------|------|-----------|
| 도메인 전문성 | WKMG 6대 도메인과의 일치도 | ? |
| 수행실적 매칭 | 유사 프로젝트 수행 경험 | ? |
| 경쟁우위 | 경쟁사 대비 차별화 가능성 | ? |
| 수주 가능성 | 종합적 수주 확률 판단 | ? |
| **합계** | | **?/100** |

각 점수에 대한 근거를 1~2줄로 설명하세요.

### STEP 3: Go/No-Go 판정
- **GO** (70점 이상): 적극 참여 추천
- **CONDITIONAL** (50~69점): 조건부 참여 (보완 필요사항 명시)
- **NO-GO** (49점 이하): 불참 추천 (사유 명시)

### STEP 4: 평가위원 시뮬레이션
당신이 이 사업의 기술평가 위원이라고 가정하세요.
- WKMG가 받을 수 있는 가장 높은 점수를 위해 반드시 포함해야 할 3가지
- 평가위원이 우려할 수 있는 약점 2가지와 대응 방안

### STEP 5: 제안 전략 요약
- 핵심 메시지 (1줄)
- 제안서 강조 포인트 3가지
- 필요한 파트너/외부 자원
- 예상 제안서 분량 및 제작 기간

---
**출력 형식**: 위 STEP 1~5를 순서대로, 마크다운 형식으로 출력하세요.
**언어**: 한국어
**분량**: 1500~2500자
"""
    
    return prompt



def build_quick_screening_prompt(rfp_title: str, rfp_summary: str) -> str:
    """
    빠른 1차 스크리닝용 프롬프트 (토큰 절약).
    RFP Radar에서 S/A 등급 받은 공고의 2차 검증용.
    """
    return f"""당신은 B2G 입찰 전문가입니다. 아래 공고가 마케팅 컨설팅사(WKMG)에 적합한지 빠르게 판단하세요.

**WKMG 전문분야**: 브랜드전략, 마케팅컨설팅, 유통채널지원, 농식품사업화, 사회적기업지원, 지역브랜드개발

**공고명**: {rfp_title}
**요약**: {rfp_summary[:2000]}

다음 형식으로만 답변하세요 (JSON):
{{
    "적합도": "HIGH/MEDIUM/LOW",
    "입찰유형": "A~H형",
    "주요도메인": "D1~D6 또는 DX",
    "한줄평": "...",
    "참여추천": true/false
}}
"""


def build_comparison_prompt(rfp_list: list) -> str:
    """
    복수 공고 비교 우선순위 결정 프롬프트.
    여러 GO 판정 공고 중 어디에 집중할지 결정.
    """
    items = []
    for i, rfp in enumerate(rfp_list, 1):
        items.append(f"""
### 공고 {i}
- 제목: {rfp.get('title', '')}
- 발주기관: {rfp.get('agency', '')}
- 예산: {rfp.get('budget_display', '')}
- Go/No-Go: {rfp.get('go_nogo', '')}
- 종합점수: {rfp.get('total_score', 0)}점
- WKMG 적합도: {rfp.get('wkmg_fit_score', 0)}점
""")
    
    rfp_text = "\n".join(items)
    
    return f"""당신은 WKMG의 영업전략 디렉터입니다. 
아래 공고들의 우선순위를 결정하세요. WKMG는 동시에 최대 2~3개 제안서만 준비할 수 있습니다.

{WKMG_PROFILE}

---
## 비교 대상 공고들
{rfp_text}

---
## 우선순위 결정 기준
1. **수주 가능성** (가중치 40%) — 기존 실적, 관계, 경쟁 강도
2. **전략적 가치** (가중치 30%) — 매출 규모, 레퍼런스 가치, 후속사업 가능성
3. **투입 효율성** (가중치 30%) — 제안서 준비 난이도, 기존 자료 활용 가능성

## 출력 형식
각 공고에 대해:
- 우선순위 순서 (1순위, 2순위, ...)
- 종합 추천점수 (/100)
- 추천 사유 (2줄)
- 제안서 준비 핵심 포인트

마지막에 "이번 주 집중 공고" 1~2개를 명확히 지정하세요.
"""


def parse_gpt_scores(gpt_response: str) -> dict:
    """
    GPT 응답에서 점수 및 판정 결과를 파싱.
    구조화된 결과 딕셔너리 반환.
    """
    result = {
        "domain_expertise": 0,
        "track_record": 0,
        "competitive_edge": 0,
        "win_probability": 0,
        "total_score": 0,
        "go_nogo": "NO-GO",
        "bid_type": "H",
        "key_message": "",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "raw_response": gpt_response
    }
    
    import re
    
    # 점수 추출 패턴
    score_patterns = [
        (r"도메인\s*전문성.*?(\d{1,2})", "domain_expertise"),
        (r"수행실적\s*매칭.*?(\d{1,2})", "track_record"),
        (r"경쟁우위.*?(\d{1,2})", "competitive_edge"),
        (r"수주\s*가능성.*?(\d{1,2})", "win_probability"),
    ]
    
    for pattern, key in score_patterns:
        match = re.search(pattern, gpt_response)
        if match:
            score = int(match.group(1))
            if score <= 25:
                result[key] = score
    
    # 합계 계산
    result["total_score"] = (
        result["domain_expertise"] +
        result["track_record"] +
        result["competitive_edge"] +
        result["win_probability"]
    )
    
    # Go/No-Go 판정
    total = result["total_score"]
    if total >= 70:
        result["go_nogo"] = "GO"
    elif total >= 50:
        result["go_nogo"] = "CONDITIONAL"
    else:
        result["go_nogo"] = "NO-GO"
    
    # 입찰유형 추출
    bid_match = re.search(r"\[?([A-H])형\]?", gpt_response)
    if bid_match:
        result["bid_type"] = bid_match.group(1)
    
    # 핵심 메시지 추출
    msg_match = re.search(r"핵심\s*메시지[:\s]*(.+?)(?:\n|$)", gpt_response)
    if msg_match:
        result["key_message"] = msg_match.group(1).strip()
    
    return result


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    print("SPD Prompts v2.0 — 프롬프트 생성 테스트")
    print("=" * 50)
    
    # 테스트 프롬프트 생성
    test_prompt = build_analysis_prompt_v2(
        rfp_title="2026년 사회적경제기업 온라인 유통채널 진출 지원사업",
        rfp_text="사회적기업의 온라인 유통채널 입점 및 마케팅 지원을 통한 매출 증대",
        agency="한국사회적기업진흥원",
        budget=500_000_000
    )
    
    print(f"프롬프트 길이: {len(test_prompt)}자")
    print(f"프롬프트 앞부분:\n{test_prompt[:500]}...")
    
    # 빠른 스크리닝 프롬프트
    quick = build_quick_screening_prompt(
        "사회적기업 유통지원", 
        "사회적기업 제품의 온라인몰 입점 지원"
    )
    print(f"\n빠른 스크리닝 프롬프트: {len(quick)}자")
    
    print("\n✅ 프롬프트 모듈 정상 작동")
