#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Phase 1-B: Analysis Engine
==================================
Auto-Fetch 결과 → GPT-4o 4대 영역 정밀분석 → ChromaDB 유사프로젝트 매칭
→ Go/No-Go 스코어카드 → 종합 진단 리포트 생성

4대 분석 영역:
  01. 역량 부합도 분석 (Capability Fit Score)
  02. 사전 준비 필요사항 (Pre-Bid Preparation)
  03. 제안 성공요소 KSF (Key Success Factors)
  04. 제안서 구성 방향 (Proposal Blueprint)

Usage:
  python spd_analysis_engine.py                              # 최신 fetch 결과 분석
  python spd_analysis_engine.py --fetch fetch_20260214.json  # 특정 fetch 결과
  python spd_analysis_engine.py --bid 20260214001            # 특정 공고만
  python spd_analysis_engine.py --dry-run                    # GPT 미호출

Author: WKMG Automation (SPD System)
Version: 1.0.0
"""

import os
import sys
import json
import glob
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# ---------------------------------------------------------------------------
# 서드파티
# ---------------------------------------------------------------------------
try:
    from openai import OpenAI
except ImportError:
    print("❌ openai 필요: pip install openai --break-system-packages")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    chromadb = None
    print("⚠️ chromadb 미설치 — 유사 프로젝트 매칭 비활성화")

# knowledge_base 매칭 (있으면 사용, 없으면 스킵)
try:
    from kb_matcher import get_kb_matches
    KB_AVAILABLE = True
    print("✅ knowledge_base.json 매칭 활성화")
except ImportError:
    KB_AVAILABLE = False
    print("ℹ️ kb_matcher 미발견 — knowledge_base 매칭 비활성화")

# 프롬프트 버전 자동 감지: v3 → v2 → v1 (내장) fallback
try:
    from spd_prompts_v3 import SYSTEM_PROMPT_V3, build_analysis_prompt_v3
    PROMPT_VERSION = "v3"
    print("✅ SPD Prompts v3.0 로드 (세부 과업 추출 + 차별화 채점)")
except ImportError:
    try:
        from spd_prompts_v2 import SYSTEM_PROMPT_V2, build_analysis_prompt_v2
        PROMPT_VERSION = "v2"
        print("ℹ️ v3 미발견 → v2 프롬프트 사용")
    except ImportError:
        PROMPT_VERSION = "v1"
        print("ℹ️ v2/v3 미발견 → 내장 v1 프롬프트 사용")

# ---------------------------------------------------------------------------
# 경로 & 설정
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    defaults = {
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "openai_model": "gpt-4o",
        "chromadb_dir": os.path.join(SCRIPT_DIR, "chromadb"),
        "chromadb_collection": "wkmg_projects",
        "fetch_results_dir": os.path.join(SCRIPT_DIR, "data", "fetch_results"),
        "extracted_dir": os.path.join(SCRIPT_DIR, "data", "extracted"),
        "analysis_output_dir": os.path.join(SCRIPT_DIR, "data", "analysis_results"),
        "max_context_chars": 20000,   # v3 프롬프트에서 상세 분석을 위해 증가
        "top_similar_projects": 5,
        "temperature": 0.3,
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        if "spd" in user_cfg:
            defaults.update(user_cfg["spd"])
        if "openai_api_key" in user_cfg:
            defaults["openai_api_key"] = user_cfg["openai_api_key"]
    if os.environ.get("OPENAI_API_KEY"):
        defaults["openai_api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("RFP_OPENAI_API_KEY"):
        defaults["openai_api_key"] = os.environ["RFP_OPENAI_API_KEY"]
    return defaults

# 로깅
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("AnalysisEngine")

# ═══════════════════════════════════════════════════════════════
# v1 내장 프롬프트 (v2 미발견 시 폴백)
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_V1 = """당신은 WKMG(WK Marketing Group)의 B2G 입찰 전략 분석 전문가입니다.

WKMG 프로파일:
- 16년 B2G 마케팅 컨설팅 전문기업
- 6대 핵심 도메인: 사회적기업, 농식품, 지역브랜드, 공공홍보, 관광문화, 중소기업유통
- B2B 대기업 브랜드전략 실적: LG전자, 롯데, 정관장, 삼성 등 17개사
- 사회적기업 유통지원 7년 연속 수주

분석 시 주의사항:
- 구체적 근거 없이 낙관적 평가 금지
- 70점 미만은 반드시 NO-GO 또는 CONDITIONAL GO 판단
- WKMG의 실제 실적과 연결하여 분석
- 경쟁 환경도 반드시 고려"""

def build_analysis_prompt_v1(bid_result: Dict, rfp_text: str, similar_projects: List[Dict]) -> str:
    """v1 분석 프롬프트 생성"""
    prompt_parts = []
    
    prompt_parts.append(f"""## 분석 대상 공고
- 공고명: {bid_result.get('title', '')}
- 발주기관: {bid_result.get('agency', '')}
- 예산: {bid_result.get('budget_str', '')}
- 공고번호: {bid_result.get('bid_no', '')}
- 등급: {bid_result.get('grade', '')}
""")
    
    if rfp_text:
        max_chars = 10000
        truncated = rfp_text[:max_chars]
        if len(rfp_text) > max_chars:
            truncated += f"\n\n... (원문 {len(rfp_text):,}자 중 {max_chars:,}자만 표시)"
        prompt_parts.append(f"## RFP 원문 (첨부파일 추출)\n{truncated}")
    
    if similar_projects:
        prompt_parts.append("\n## WKMG 유사 프로젝트 (ChromaDB 매칭)")
        for sp in similar_projects[:5]:
            prompt_parts.append(f"- {sp.get('filename', '?')} (유사도: {sp.get('similarity', 0):.0%}) — {sp.get('preview', '')[:100]}")
    
    prompt_parts.append("""
## 요청: 4대 영역 정밀분석을 JSON으로 출력하세요.

```json
{
  "summary": "한줄 요약",
  "go_no_go": "GO | NO-GO | CONDITIONAL",
  "total_score": 75,
  "capability_fit": {
    "score": 80,
    "matching_domains": ["D1_사회적기업"],
    "key_strengths": ["7년 연속 수주 실적"],
    "gaps": ["해당 없음"],
    "evidence": "2018~2024 사회적기업 유통지원 7회 수행"
  },
  "pre_bid_preparation": {
    "must_do": ["발주기관 사전미팅 추진"],
    "nice_to_have": ["파트너사 컨소시엄 구성"],
    "timeline_days": 14
  },
  "key_success_factors": {
    "top3_ksf": ["실적 기반 신뢰성", "현장 경험", "유통 네트워크"],
    "differentiators": ["B2B+B2G 복합 역량"],
    "risks": ["담당자 교체 가능성"]
  },
  "proposal_blueprint": {
    "recommended_toc": ["사업이해", "수행전략", "실적", "조직"],
    "page_estimate": "45~55p",
    "key_visuals": ["연도별 성과 추이 그래프"],
    "tone": "현장 경험 기반 실무형"
  },
  "competitive_landscape": {
    "likely_competitors": ["공공컨설팅사"],
    "wkmg_advantage": "7년 연속 수주 + 대기업 브랜드 전략",
    "win_probability": "75~85%"
  },
  "action_items": [
    {"action": "발주기관 담당자 미팅", "priority": "HIGH", "deadline": "입찰 2주전"}
  ]
}
```

반드시 유효한 JSON으로 출력하세요.""")
    
    return "\n".join(prompt_parts)

# ═══════════════════════════════════════════════════════════════
# ChromaDB 유사 프로젝트 매칭
# ═══════════════════════════════════════════════════════════════

def get_similar_projects(query_text: str, config: Dict) -> List[Dict]:
    """ChromaDB에서 유사 과거 프로젝트 매칭"""
    if not chromadb:
        return []
    
    db_dir = config.get("chromadb_dir", os.path.join(SCRIPT_DIR, "chromadb"))
    collection_name = config.get("chromadb_collection", "wkmg_projects")
    
    if not os.path.exists(db_dir):
        log.info("  ℹ️ ChromaDB 없음 — 유사 프로젝트 매칭 스킵")
        return []
    
    try:
        client = chromadb.PersistentClient(path=db_dir)
        collection = client.get_collection(name=collection_name)
        
        # 쿼리 텍스트 요약 (너무 길면 잘라서)
        query = query_text[:2000]
        n_results = config.get("top_similar_projects", 5)
        
        results = collection.query(query_texts=[query], n_results=n_results)
        
        matched = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                dist = results["distances"][0][i] if results.get("distances") else 999
                similarity = max(0, 1 - dist)
                
                matched.append({
                    "filename": meta.get("file_name", meta.get("source_file", "unknown")),
                    "project_name": meta.get("project_name", ""),
                    "similarity": similarity,
                    "b2g_b2b": meta.get("business_type", meta.get("b2g_b2b", "")),
                    "category": meta.get("category", ""),
                    "year": meta.get("year", ""),
                    "client": meta.get("client", ""),
                    "domain": meta.get("domain", ""),
                    "sub_category": meta.get("sub_category", ""),
                    "preview": doc[:200],
                })
        
        log.info(f"  🔍 유사 프로젝트 {len(matched)}건 매칭")
        return matched
        
    except Exception as e:
        log.warning(f"  ⚠️ ChromaDB 매칭 실패: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# GPT 분석
# ═══════════════════════════════════════════════════════════════

def call_gpt(system_prompt: str, user_prompt: str, config: Dict) -> Dict:
    """GPT-4o 호출 및 JSON 파싱"""
    api_key = config.get("openai_api_key", "")
    if not api_key:
        return {"error": "OpenAI API 키 없음"}
    
    model = config.get("openai_model", "gpt-4o")
    temperature = config.get("temperature", 0.3)
    
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        
        content = response.choices[0].message.content
        usage = response.usage
        
        log.info(f"  💰 토큰: {usage.prompt_tokens:,} 입력 + {usage.completion_tokens:,} 출력")
        
        result = json.loads(content)
        result["_meta"] = {
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
        return result
        
    except json.JSONDecodeError as e:
        log.error(f"  ❌ JSON 파싱 실패: {e}")
        return {"error": f"JSON 파싱 실패: {e}", "raw": content if 'content' in dir() else ""}
    except Exception as e:
        log.error(f"  ❌ GPT 호출 실패: {e}")
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════
# 분석 파이프라인
# ═══════════════════════════════════════════════════════════════

def load_rfp_text(bid_result: Dict, config: Dict) -> str:
    """fetch 결과에서 RFP 텍스트 로드"""
    texts = []
    
    for extracted in bid_result.get("texts_extracted", []):
        text_file = extracted.get("text_file", "")
        if text_file and os.path.exists(text_file):
            try:
                with open(text_file, "r", encoding="utf-8") as f:
                    texts.append(f.read())
            except:
                pass
    
    combined = "\n\n---\n\n".join(texts)
    max_chars = config.get("max_context_chars", 12000)
    
    if len(combined) > max_chars:
        combined = combined[:max_chars] + f"\n\n... (원문 {len(combined):,}자 중 {max_chars:,}자만 포함)"
    
    return combined

def analyze_bid(bid_result: Dict, config: Dict, dry_run: bool = False) -> Dict:
    """단일 공고 분석 실행"""
    bid_no = bid_result.get("bid_no", "unknown")
    title = bid_result.get("title", "")
    
    log.info(f"\n{'='*60}")
    log.info(f"🔬 분석 시작: [{bid_result.get('grade','?')}] {title}")
    
    # Step 1: RFP 텍스트 로드
    rfp_text = load_rfp_text(bid_result, config)
    log.info(f"  📄 RFP 텍스트: {len(rfp_text):,}자")
    
    # Step 2: ChromaDB 유사 프로젝트 매칭 (기존 그대로)
    query_text = f"{title} {bid_result.get('agency', '')} {rfp_text[:1000]}"
    similar_projects = get_similar_projects(query_text, config)

    # Step 2.5: knowledge_base.json 매칭 (새로 추가)
    kb_result = {"matched_count": 0, "projects": [], "prompt_injection": ""}
    if KB_AVAILABLE:
        try:
            kb_result = get_kb_matches(
                title=title,
                agency=bid_result.get("agency", ""),
                rfp_text=rfp_text,
                top_n=5,
            )
            log.info(f"  📚 KB 유사 프로젝트: {kb_result['matched_count']}건")
        except Exception as kb_err:
            log.warning(f"  ⚠️ KB 매칭 실패 (무시하고 계속): {kb_err}")

    # Step 3: GPT 분석
    if dry_run:
        log.info(f"  🔍 DRY-RUN — GPT 호출 스킵")
        return {
            "bid_no": bid_no,
            "title": title,
            "status": "dry_run",
            "rfp_text_length": len(rfp_text),
            "similar_projects": len(similar_projects),
            "kb_matched_count": kb_result.get("matched_count", 0),
        }

    # ★ KB 인사이트를 RFP 텍스트 뒤에 추가 (프롬프트 주입)
    analysis_rfp_text = rfp_text
    if kb_result.get("prompt_injection"):
        analysis_rfp_text = rfp_text + "\n\n" + kb_result["prompt_injection"]
        log.info(f"  📝 KB 인사이트 {len(kb_result['prompt_injection'])}자 주입")

    log.info(f"  🤖 GPT-4o 정밀분석 시작... (프롬프트: {PROMPT_VERSION})")
    start_time = time.time()

    if PROMPT_VERSION == "v3":
        prompt = build_analysis_prompt_v3(bid_result, analysis_rfp_text, similar_projects)
        gpt_result = call_gpt(SYSTEM_PROMPT_V3, prompt, config)
    elif PROMPT_VERSION == "v2":
        prompt = build_analysis_prompt_v2(bid_result, analysis_rfp_text, similar_projects)
        gpt_result = call_gpt(SYSTEM_PROMPT_V2, prompt, config)
    else:
        prompt = build_analysis_prompt_v1(bid_result, analysis_rfp_text, similar_projects)
        gpt_result = call_gpt(SYSTEM_PROMPT_V1, prompt, config)
    
    elapsed = time.time() - start_time
    log.info(f"  ⏱️ 분석 완료: {elapsed:.1f}초")
    
    # 결과 조합
    analysis = {
        "bid_no": bid_no,
        "title": title,
        "grade": bid_result.get("grade", "?"),
        "agency": bid_result.get("agency", ""),
        "budget_str": bid_result.get("budget_str", ""),
        "analyzed_at": datetime.now().isoformat(),
        "prompt_version": PROMPT_VERSION,
        "rfp_text_length": len(rfp_text),
        "similar_projects_count": len(similar_projects),
        "similar_projects": similar_projects,
        # ★ KB 매칭 결과 추가
        "kb_matched_count": kb_result.get("matched_count", 0),
        "kb_matched_projects": [
            {"name": p["project_name"], "client": p["client_org"], "year": p["year"], "score": p["score"]}
            for p in kb_result.get("projects", [])
        ],
        "analysis": gpt_result,
        "elapsed_seconds": round(elapsed, 1),
        "status": "error" if "error" in gpt_result else "completed",
    }
    
    # Go/No-Go 요약 (v3는 구조가 다름)
    if PROMPT_VERSION == "v3":
        go_section = gpt_result.get("go_no_go", {})
        go_decision = go_section.get("decision", "UNKNOWN") if isinstance(go_section, dict) else str(go_section)
        scoring = gpt_result.get("scoring", {})
        total_score = scoring.get("total_score", 0) if isinstance(scoring, dict) else 0
        # 세부 과업 분석 요약
        deliv = gpt_result.get("deliverables_analysis", {})
        deliv_count = deliv.get("total_deliverables", 0) if isinstance(deliv, dict) else 0
        coverage = deliv.get("wkmg_coverage_pct", 0) if isinstance(deliv, dict) else 0
        log.info(f"  📊 결과: {go_decision} ({total_score}점) | 세부과업 {deliv_count}개, WKMG 커버리지 {coverage}%")
    else:
        go_decision = gpt_result.get("go_no_go", "UNKNOWN")
        total_score = gpt_result.get("total_score", 0)
        log.info(f"  📊 결과: {go_decision} ({total_score}점)")
    
    return analysis

def find_latest_fetch(fetch_dir: str) -> Optional[str]:
    """최신 fetch 결과 파일 찾기"""
    patterns = [
        os.path.join(fetch_dir, "fetch_*.json"),
        os.path.join(fetch_dir, "*.json"),
    ]
    all_files = []
    for p in patterns:
        all_files.extend(glob.glob(p))
    if not all_files:
        return None
    return max(all_files, key=os.path.getmtime)

def run_analysis(args):
    """메인 분석 실행"""
    config = load_config()
    
    # fetch 결과 로드
    if args.fetch:
        fetch_path = args.fetch
    else:
        fetch_dir = config.get("fetch_results_dir", os.path.join(SCRIPT_DIR, "data", "fetch_results"))
        fetch_path = find_latest_fetch(fetch_dir)
    
    if not fetch_path or not os.path.exists(fetch_path):
        log.error("❌ Auto-Fetch 결과를 찾을 수 없습니다.")
        log.info("   먼저 spd_auto_fetch.py를 실행하세요.")
        return
    
    log.info(f"📂 Fetch 결과: {os.path.basename(fetch_path)}")
    
    with open(fetch_path, "r", encoding="utf-8") as f:
        fetch_data = json.load(f)
    
    results_list = fetch_data.get("results", [])
    log.info(f"   공고 수: {len(results_list)}건")
    
    # 필터링
    if args.bid:
        results_list = [r for r in results_list if args.bid in str(r.get("bid_no", ""))]
    
    # 분석 가능한 건만 (텍스트 있거나 제목으로라도)
    analyzable = [r for r in results_list if r.get("status") in ("completed", "no_files", "dry_run")]
    if not analyzable:
        analyzable = results_list  # 어쨌든 분석 시도
    
    log.info(f"   분석 대상: {len(analyzable)}건")
    
    # 출력 디렉토리
    output_dir = config.get("analysis_output_dir", os.path.join(SCRIPT_DIR, "data", "analysis_results"))
    os.makedirs(output_dir, exist_ok=True)
    
    # 분석 실행
    analyses = []
    total_cost = 0
    
    for i, bid_result in enumerate(analyzable, 1):
        log.info(f"\n[{i}/{len(analyzable)}]")
        analysis = analyze_bid(bid_result, config, dry_run=args.dry_run)
        analyses.append(analysis)
        
        # 비용 추적
        meta = analysis.get("analysis", {}).get("_meta", {})
        tokens = meta.get("total_tokens", 0)
        # GPT-4o: ~$5/1M input, ~$15/1M output (대략)
        cost_est = tokens * 0.00001
        total_cost += cost_est
        
        if i < len(analyzable):
            time.sleep(2)  # API 쿨다운
    
    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"analysis_{timestamp}.json")
    
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "fetch_source": fetch_path,
        "prompt_version": PROMPT_VERSION,
        "total_analyzed": len(analyses),
        "total_cost_estimate": f"${total_cost:.4f}",
        "analyses": analyses,
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    # 요약 (v3 구조 호환: go_no_go가 dict일 수 있음)
    def _get_decision(a):
        gng = a.get("analysis", {}).get("go_no_go", "UNKNOWN")
        if isinstance(gng, dict):
            return gng.get("decision", "UNKNOWN")
        return str(gng)
    
    go_count = sum(1 for a in analyses if _get_decision(a) == "GO")
    nogo_count = sum(1 for a in analyses if _get_decision(a) == "NO-GO")
    cond_count = sum(1 for a in analyses if _get_decision(a) == "CONDITIONAL")
    
    log.info(f"\n{'='*60}")
    log.info(f"✅ SPD 분석 완료")
    log.info(f"   GO: {go_count} | NO-GO: {nogo_count} | CONDITIONAL: {cond_count}")
    log.info(f"   비용: ~${total_cost:.4f}")
    log.info(f"   결과: {output_file}")
    log.info(f"{'='*60}")

# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SPD Analysis Engine")
    parser.add_argument("--fetch", help="특정 fetch 결과 JSON 경로")
    parser.add_argument("--bid", help="특정 공고번호만 분석")
    parser.add_argument("--dry-run", action="store_true", help="GPT 호출 없이 구조 확인")
    
    args = parser.parse_args()
    run_analysis(args)
