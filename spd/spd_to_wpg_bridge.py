"""
SPD -> WPG Bridge
=================
SPD 분석 결과(analysis_*.json)에서 GO/CONDITIONAL 공고를 추출하여
WPG의 spd_inbox/ 폴더에 JSON으로 전달한다.

사용법:
  python spd_to_wpg_bridge.py                    # 최신 분석 결과 자동 전달
  python spd_to_wpg_bridge.py --file analysis_20260323.json  # 특정 파일
  python spd_to_wpg_bridge.py --all              # 미전달 전체 처리
  python spd_to_wpg_bridge.py --dry-run          # 실제 저장 없이 미리보기
"""

import json
import os
import re
import sys
import glob
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("spd_to_wpg_bridge")

# ═══════════════════════════════════════════════════
# 경로 설정 (멀티PC 대응: yso/wangk)
# ═══════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).parent
SPD_ANALYSIS_DIR = SCRIPT_DIR / "data" / "analysis_results"


def _find_wpg_inbox() -> Path:
    """WPG inbox 경로 자동 감지 (OneDrive 동기화)"""
    candidates = [
        Path(r"C:\Users\yso\OneDrive\Documents\GitHub\WPG\spd_inbox"),
        Path(r"C:\Users\wangk\OneDrive\Documents\GitHub\WPG\spd_inbox"),
        SCRIPT_DIR.parent / "WPG" / "spd_inbox",
    ]
    for c in candidates:
        if c.parent.exists():
            c.mkdir(parents=True, exist_ok=True)
            return c
    fallback = SCRIPT_DIR / "wpg_inbox_pending"
    fallback.mkdir(exist_ok=True)
    log.warning(f"WPG inbox not found. fallback: {fallback}")
    return fallback


WPG_INBOX_DIR = _find_wpg_inbox()


# ═══════════════════════════════════════════════════
# SPD 분석 결과 -> WPG Inbox JSON 변환
# ═══════════════════════════════════════════════════

def convert_spd_to_wpg_inbox(analysis_item: dict, source_file: str) -> dict:
    """SPD 분석 결과 1건 -> WPG inbox JSON 1건 변환. v1/v2/v3 구조 모두 호환."""

    analysis = analysis_item.get("analysis", {})

    # --- GO/NO-GO 판정 ---
    go_section = analysis.get("go_no_go", {})
    if isinstance(go_section, dict):
        decision = go_section.get("decision", "UNKNOWN")
    else:
        decision = str(go_section)

    # --- 점수 ---
    scoring = analysis.get("scoring", {})
    total_score = scoring.get("total_score", 0) if isinstance(scoring, dict) else analysis.get("total_score", 0)

    # --- 커버리지 (v3: deliverables_analysis.wkmg_coverage_pct) ---
    deliv = analysis.get("deliverables_analysis", {})
    if isinstance(deliv, dict):
        coverage_pct = deliv.get("wkmg_coverage_pct", 0)
    else:
        cov = analysis.get("wkmg_coverage", {})
        coverage_pct = cov.get("coverage_pct", 0) if isinstance(cov, dict) else 0

    # --- 전략 추천 (v3: strategic_recommendation) ---
    strat = analysis.get("strategic_recommendation", {})
    if isinstance(strat, dict):
        core_message = strat.get("core_message", "")
        differentiators = strat.get("key_differentiators", [])
        partners = strat.get("required_partners", "")
    else:
        core_message = str(strat) if strat else ""
        comp = analysis.get("competitive_advantage", {})
        differentiators = comp.get("key_differentiators", []) if isinstance(comp, dict) else []
        partners = analysis.get("required_partners", "")

    # --- 핵심 과업 (v3: deliverables_analysis.key_tasks) ---
    if isinstance(deliv, dict):
        tasks_raw = deliv.get("key_tasks", [])
    else:
        tasks_raw = analysis.get("key_tasks", [])

    key_tasks = []
    if isinstance(tasks_raw, list):
        for t in tasks_raw:
            if isinstance(t, dict):
                key_tasks.append({
                    "task": t.get("task", t.get("name", "")),
                    "capability": t.get("capability", t.get("wkmg_capability", "")),
                    "partner": t.get("partner", t.get("required_partner", "")),
                })
            else:
                key_tasks.append({"task": str(t), "capability": "", "partner": ""})

    # --- 유사 프로젝트 ---
    similar = analysis_item.get("similar_projects", [])
    similar_names = []
    if isinstance(similar, list):
        for sp in similar:
            if isinstance(sp, dict):
                similar_names.append(sp.get("project_name", sp.get("filename", str(sp))))
            else:
                similar_names.append(str(sp))

    if isinstance(partners, list):
        partners = ", ".join(partners)

    # --- RFP 텍스트 ---
    rfp_text = analysis_item.get("rfp_text", "")
    if not rfp_text:
        rfp_text = f"{analysis_item.get('bid_title', '')} {analysis_item.get('agency', '')}"

    return {
        "wpg_inbox_version": "1.0",
        "created_at": datetime.now().isoformat(),
        "source": "SPD",
        "source_file": source_file,
        "bid_title": analysis_item.get("bid_title", ""),
        "agency": analysis_item.get("agency", analysis_item.get("demand_agency", "")),
        "budget_text": analysis_item.get("budget_text", analysis_item.get("estimated_price", "")),
        "rfp_text": rfp_text,
        "spd_score": total_score,
        "spd_decision": decision,
        "coverage_pct": coverage_pct,
        "core_message": core_message,
        "key_differentiators": differentiators,
        "key_tasks": key_tasks,
        "similar_projects": similar_names[:5],
        "required_partners": partners,
        # SPD 상세 분석 결과 전체 (WPG 집요분석에서 활용 -> 중복 분석 방지)
        "spd_full_analysis": analysis,
        # WPG 상태 (초기값)
        "wpg_status": "PENDING",
        "wpg_proposal_path": "",
        "wpg_job_id": "",
    }


def _make_inbox_filename(bid_title: str, timestamp: str) -> str:
    """WPG inbox JSON 파일명 생성"""
    safe_title = re.sub(r'[\\/:*?"<>|\s]+', '_', bid_title)[:60]
    return f"spd_{timestamp}_{safe_title}.json"


# ═══════════════════════════════════════════════════
# 메인: 분석 결과 -> WPG Inbox 전달
# ═══════════════════════════════════════════════════

def push_to_wpg_inbox(analysis_file: str, decisions: list = None, dry_run: bool = False) -> dict:
    """SPD 분석 결과 파일에서 GO/CONDITIONAL 공고를 WPG inbox로 전달."""
    if decisions is None:
        decisions = ["GO", "CONDITIONAL"]

    with open(analysis_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    analyses = data.get("analyses", [])
    source_name = os.path.basename(analysis_file)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    pushed, skipped, files_created = 0, 0, []

    # 기존 inbox 파일들의 bid_title 목록 (중복 체크용, 한 번만 로드)
    existing_titles = set()
    for ef in WPG_INBOX_DIR.glob("spd_*.json"):
        try:
            with open(ef, "r", encoding="utf-8") as ef_f:
                existing_titles.add(json.load(ef_f).get("bid_title", ""))
        except Exception:
            continue

    for item in analyses:
        analysis = item.get("analysis", {})
        go_section = analysis.get("go_no_go", {})
        decision = go_section.get("decision", str(go_section)) if isinstance(go_section, dict) else str(go_section)
        bid_title = item.get("bid_title", "")

        if decision not in decisions:
            skipped += 1
            log.info(f"  skip {decision}: {bid_title}")
            continue

        if bid_title in existing_titles:
            skipped += 1
            log.info(f"  skip already exists: {bid_title}")
            continue

        inbox_json = convert_spd_to_wpg_inbox(item, source_name)
        filename = _make_inbox_filename(bid_title, timestamp)
        filepath = WPG_INBOX_DIR / filename

        if dry_run:
            log.info(f"  [DRY-RUN] {decision}: {bid_title} -> {filename}")
        else:
            with open(filepath, "w", encoding="utf-8") as out_f:
                json.dump(inbox_json, out_f, ensure_ascii=False, indent=2)
            log.info(f"  PUSHED {decision}: {bid_title} -> {filename}")

        pushed += 1
        files_created.append(str(filepath))
        existing_titles.add(bid_title)

    return {"pushed": pushed, "skipped": skipped, "files": files_created, "inbox_dir": str(WPG_INBOX_DIR)}


def find_latest_analysis() -> Optional[str]:
    """최신 분석 결과 파일 찾기"""
    pattern = str(SPD_ANALYSIS_DIR / "analysis_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None


# ═══════════════════════════════════════════════════
# spd_analysis_engine.py / spd_report.py에서 호출
# ═══════════════════════════════════════════════════

def auto_push_after_analysis(analysis_file: str) -> dict:
    """SPD 분석 완료 후 자동 호출. GO/CONDITIONAL 공고를 WPG inbox로 전달."""
    log.info(f"\n{'='*50}")
    log.info(f"SPD -> WPG Inbox auto-push started")
    log.info(f"   source: {analysis_file}")
    log.info(f"   target: {WPG_INBOX_DIR}")
    result = push_to_wpg_inbox(analysis_file, decisions=["GO", "CONDITIONAL"])
    log.info(f"   pushed: {result['pushed']} | skipped: {result['skipped']}")
    log.info(f"{'='*50}")
    return result


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="SPD -> WPG Inbox Bridge")
    parser.add_argument("--file", help="특정 분석 결과 파일")
    parser.add_argument("--all", action="store_true", help="미전달 전체 처리")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 미리보기")
    args = parser.parse_args()

    if args.file:
        result = push_to_wpg_inbox(args.file, dry_run=args.dry_run)
    elif args.all:
        pattern = str(SPD_ANALYSIS_DIR / "analysis_*.json")
        for f in sorted(glob.glob(pattern)):
            log.info(f"\nProcessing: {f}")
            push_to_wpg_inbox(f, dry_run=args.dry_run)
        sys.exit(0)
    else:
        latest = find_latest_analysis()
        if latest:
            result = push_to_wpg_inbox(latest, dry_run=args.dry_run)
        else:
            log.error("No analysis result files found.")
            sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
