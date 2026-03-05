"""
SPD용 knowledge_base.json 매칭 모듈
공고 정보(제목, 기관, RFP 텍스트)로 유사 과거 프로젝트를 검색하고
GPT 프롬프트에 주입할 인사이트를 추출한다.

매칭 알고리즘:
  1단계 — 키워드 매칭 (40점 만점)
  2단계 — 산업/도메인 매칭 (30점 만점)
  3단계 — 발주기관 매칭 (30점 만점)
  + B2G 가산점 (+5점)
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("KBMatcher")

SCRIPT_DIR = Path(__file__).parent
KB_PATH = SCRIPT_DIR / "data" / "knowledge_base.json"


class KBMatcher:
    """knowledge_base.json 기반 유사 프로젝트 매칭"""

    def __init__(self, kb_path: str = None):
        path = Path(kb_path) if kb_path else KB_PATH
        if not path.exists():
            self._entries = []
            self._available = False
            log.warning(f"knowledge_base.json 없음: {path}")
            return

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._entries = data.get("entries", [])
        self._available = True
        log.info(f"knowledge_base 로드 완료: {len(self._entries)}건")

    @property
    def available(self) -> bool:
        return self._available and len(self._entries) > 0

    def search(self, title: str, agency: str, rfp_text: str, top_n: int = 5) -> Dict:
        """
        공고와 유사한 과거 프로젝트 검색.

        Args:
            title: 공고 제목
            agency: 발주기관명
            rfp_text: RFP/과업지시서 텍스트 (없으면 빈 문자열)
            top_n: 상위 N개 반환

        Returns:
            {
                "matched_count": int,
                "projects": [
                    {
                        "project_name": str,
                        "client_org": str,
                        "year": int,
                        "score": float,
                        "match_reasons": [str],
                        "field_insights": dict,
                        "reusable_content": dict,
                        "quantitative_data": dict,
                    }
                ],
                "prompt_injection": str,  # GPT 프롬프트에 바로 삽입할 텍스트
            }
        """
        if not self._available:
            return {"matched_count": 0, "projects": [], "prompt_injection": ""}

        search_text = f"{title} {agency} {rfp_text}".lower()
        scored = []

        for entry in self._entries:
            score = 0.0
            reasons = []

            # ── 키워드 매칭 (40점) ──
            entry_keywords = entry.get("keywords", [])
            match_count = sum(1 for kw in entry_keywords if kw.lower() in search_text)
            if match_count > 0:
                score += min(40, match_count * 8)
                reasons.append(f"키워드 {match_count}개 일치")

            # ── 산업/도메인 매칭 (30점) ──
            entry_industry = entry.get("industry", "")
            entry_domain = entry.get("primary_domain", "")

            # 공고 제목/텍스트에서 산업 키워드 감지
            industry_signals = {
                "agrifood": ["농", "식품", "농산물", "특산물", "가공", "6차산업"],
                "social_enterprise": ["사회적기업", "사회적경제", "소셜벤처", "협동조합"],
                "tourism": ["관광", "여행", "축제", "문화관광"],
                "fmcg": ["소비재", "생활용품", "화장품"],
                "electronics": ["전자", "가전", "IT", "디지털"],
            }

            for ind, signals in industry_signals.items():
                if any(s in search_text for s in signals):
                    if ind == entry_industry:
                        score += 20
                        reasons.append(f"산업 일치: {entry_industry}")
                        break
                    if ind in entry_domain:
                        score += 10
                        reasons.append(f"도메인 관련: {entry_domain}")

            # ── 발주기관 매칭 (30점) ──
            entry_client = entry.get("client_org", "").lower()
            agency_lower = agency.lower() if agency else ""

            if agency_lower and entry_client:
                if agency_lower in entry_client or entry_client in agency_lower:
                    score += 30
                    reasons.append(f"동일기관: {entry.get('client_org', '')}")
                elif _same_org_type(agency_lower, entry_client):
                    score += 15
                    reasons.append(f"유사기관: {entry.get('client_org', '')}")

            # B2G 가산점
            if entry.get("_meta", {}).get("client_type") == "B2G":
                score += 5

            if score > 0:
                scored.append((score, entry, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_n]

        projects = []
        for score, entry, reasons in top:
            projects.append({
                "project_name": entry.get("project_name", ""),
                "client_org": entry.get("client_org", ""),
                "year": entry.get("year", 0),
                "score": min(100, score),
                "match_reasons": reasons,
                "field_insights": entry.get("field_insights", {}),
                "reusable_content": entry.get("reusable_content", {}),
                "quantitative_data": entry.get("quantitative_data", {}),
            })

        # GPT 프롬프트 주입용 텍스트 생성
        prompt_text = _build_prompt_injection(projects)

        return {
            "matched_count": len(projects),
            "projects": projects,
            "prompt_injection": prompt_text,
        }


def _same_org_type(a: str, b: str) -> bool:
    """기관 유형 유사성 판단"""
    groups = [
        ["시청", "군청", "구청", "도청"],
        ["진흥원", "진흥재단", "재단"],
        ["공사", "공단"],
        ["센터", "지원센터"],
    ]
    for g in groups:
        if any(t in a for t in g) and any(t in b for t in g):
            return True
    return False


def _build_prompt_injection(projects: list) -> str:
    """GPT 프롬프트에 삽입할 인사이트 텍스트 생성 (4000자 제한)"""
    if not projects:
        return ""

    parts = []
    parts.append("## WKMG 과거 유사 프로젝트 인사이트 (knowledge_base 자동 매칭)")
    parts.append("아래는 WKMG가 실제 수행한 유사 프로젝트에서 추출한 검증된 인사이트입니다.")
    parts.append("채점 시 수행실적 매칭(track_record) 및 전략 수립에 적극 활용하세요.\n")

    for i, p in enumerate(projects[:3], 1):  # 상위 3개만 상세 표시
        parts.append(f"### 유사 프로젝트 {i}: {p['project_name']} ({p['client_org']}, {p['year']}년)")
        parts.append(f"유사도: {p['score']:.0f}점 | 매칭 근거: {', '.join(p['match_reasons'])}")

        fi = p.get("field_insights", {})
        if fi.get("client_real_pain"):
            parts.append(f"\n발주기관의 진짜 고민: {fi['client_real_pain']}")

        challenges = fi.get("hidden_challenges", [])
        if challenges:
            parts.append("\n숨은 과제:")
            for c in challenges[:3]:
                parts.append(f"  - {c}")

        success = fi.get("success_factors", [])
        if success:
            parts.append("\n성공 요인:")
            for s in success[:3]:
                parts.append(f"  - {s}")

        risks = fi.get("failure_risks", [])
        if risks:
            parts.append("\n실패 리스크:")
            for r in risks[:3]:
                parts.append(f"  - {r}")

        qd = p.get("quantitative_data", {})
        kpis = qd.get("kpi_targets", [])
        results = qd.get("actual_results", [])
        if kpis or results:
            parts.append("\n수치 데이터:")
            for k in kpis[:2]:
                parts.append(f"  - KPI: {k}")
            for r in results[:2]:
                parts.append(f"  - 실적: {r}")

        parts.append("")  # 빈 줄

    # 나머지는 목록만
    if len(projects) > 3:
        parts.append("### 추가 유사 프로젝트:")
        for p in projects[3:]:
            parts.append(f"  - {p['project_name']} ({p['client_org']}, {p['year']}년, {p['score']:.0f}점)")

    full_text = "\n".join(parts)

    # 4000자 제한
    if len(full_text) > 4000:
        full_text = full_text[:3980] + "\n... (이하 생략)"

    return full_text


# ── 편의 함수 (싱글턴) ──

_matcher_instance = None


def get_kb_matches(title: str, agency: str, rfp_text: str = "", top_n: int = 5) -> Dict:
    """편의 함수: KB 매칭 (싱글턴)"""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = KBMatcher()
    return _matcher_instance.search(title, agency, rfp_text, top_n)
