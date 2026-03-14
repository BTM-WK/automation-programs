#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD → WPG 브릿지 모듈
========================
SPD가 발굴한 GO 공고를 WPG 제안서 생성 파이프라인으로 자동 연결.

Author: WKMG
Version: 1.1.0 (2026-03-14) — analysis_engine 실제 출력 구조 대응
"""

import os, json, glob
from datetime import datetime
from typing import Optional

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
SPD_DATA_DIR = os.path.join(_BASE, "data", "analysis_results")

WPG_ROOT = next((p for p in [
    r"C:\Users\yso\OneDrive\Documents\GitHub\WPG",
    r"C:\Users\wangk\OneDrive\Documents\GitHub\WPG",
] if os.path.isdir(p)), None)

WPG_INBOX_DIR = os.path.join(WPG_ROOT, "spd_inbox") if WPG_ROOT else None


# ─── 필드 추출 헬퍼 (analysis_engine 출력 + test_email.json 양쪽 대응) ────────

def _get_title(item: dict) -> str:
    """공고명: analysis_engine → 'title', test_email → 'bid_title'"""
    return item.get("title") or item.get("bid_title") or ""

def _get_agency(item: dict) -> str:
    return item.get("agency") or ""

def _get_budget(item: dict) -> str:
    """예산: analysis_engine → 'budget_str', test_email → 'budget_text'"""
    return item.get("budget_str") or item.get("budget_text") or item.get("budget") or ""

def _get_bid_no(item: dict) -> str:
    return str(item.get("bid_no") or item.get("bidNtceNo") or "")

def _get_url(item: dict) -> str:
    return item.get("url") or ""

def _get_decision(item: dict) -> str:
    """
    Go/No-Go 결정값 추출.
    - analysis_engine v3: analysis.go_no_go.decision (dict)
    - analysis_engine v1/v2: analysis.go_no_go (문자열 "GO"/"NO-GO")
    - test_email: analysis.go_no_go.decision (dict)
    """
    a = item.get("analysis", {})
    if not a:
        return "UNKNOWN"
    gng = a.get("go_no_go", {})
    if isinstance(gng, dict):
        return gng.get("decision", "UNKNOWN")
    return str(gng) if gng else "UNKNOWN"

def _get_score(item: dict) -> int:
    """점수: analysis.scoring.total_score"""
    a = item.get("analysis", {})
    if not a:
        return 0
    scoring = a.get("scoring", {})
    if isinstance(scoring, dict):
        return int(scoring.get("total_score", 0))
    return int(a.get("total_score", 0))

def _get_coverage(item: dict) -> int:
    a = item.get("analysis", {})
    deliv = a.get("deliverables_analysis", {}) if a else {}
    return int(deliv.get("wkmg_coverage_pct", 0)) if isinstance(deliv, dict) else 0

def _get_key_tasks(item: dict) -> list:
    a = item.get("analysis", {})
    deliv = a.get("deliverables_analysis", {}) if a else {}
    tasks = deliv.get("key_tasks", []) if isinstance(deliv, dict) else []
    return [
        {"task": t.get("task", ""), "capability": t.get("capability", ""),
         "partner": t.get("required_partner", "")}
        for t in tasks if isinstance(t, dict)
    ]

def _get_strategic_rec(item: dict) -> dict:
    a = item.get("analysis", {})
    return a.get("strategic_recommendation", {}) if a else {}

def _get_similar_projects(item: dict) -> list:
    """유사 프로젝트: analysis_engine → similar_projects[].project_name or filename"""
    projects = item.get("similar_projects", [])
    result = []
    for p in projects:
        if isinstance(p, dict):
            name = p.get("project_name") or p.get("filename") or p.get("name") or ""
            if name:
                result.append(name)
        elif isinstance(p, str):
            result.append(p)
    return result


# ─── 핵심 함수 ────────────────────────────────────────────────────────────────

def get_latest_analysis() -> Optional[dict]:
    """SPD 최신 분석 결과 JSON 반환"""
    if not os.path.isdir(SPD_DATA_DIR):
        return None
    files = sorted(glob.glob(os.path.join(SPD_DATA_DIR, "*.json")),
                   key=os.path.getmtime, reverse=True)
    real_files = [f for f in files if "test" not in os.path.basename(f).lower()]
    target = real_files[0] if real_files else (files[0] if files else None)
    if not target:
        return None
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    data["_source_file"] = os.path.basename(target)
    return data


def filter_go_bids(analysis_data: dict, min_score: int = 65) -> list:
    """GO 또는 CONDITIONAL 공고만 추출"""
    result = []
    for item in analysis_data.get("analyses", []):
        decision = _get_decision(item)
        score    = _get_score(item)
        if decision in ("GO", "CONDITIONAL") and score >= min_score:
            result.append(item)
    result.sort(key=lambda x: _get_score(x), reverse=True)
    return result


def convert_to_wpg_format(spd_item: dict, source_file: str = "") -> dict:
    """SPD 분석 결과 1건 → WPG inbox 형식 변환 (양쪽 구조 모두 대응)"""
    rec   = _get_strategic_rec(spd_item)
    title = _get_title(spd_item)
    agency = _get_agency(spd_item)

    return {
        "wpg_inbox_version": "1.1",
        "created_at": datetime.now().isoformat(),
        "source": "SPD",
        "source_file": source_file,
        # ── 용역 기본 정보 (WPG + 이후 모든 단계가 사용) ────────
        "bid_title":   title,
        "agency":      agency,
        "budget_text": _get_budget(spd_item),
        "bid_no":      _get_bid_no(spd_item),
        "url":         _get_url(spd_item),
        "rfp_text":    f"{title} {agency}",
        # ── SPD 분석 결과 (WPG 집요분석 참고용) ─────────────────
        "spd_score":          _get_score(spd_item),
        "spd_decision":       _get_decision(spd_item),
        "coverage_pct":       _get_coverage(spd_item),
        "core_message":       rec.get("core_message", ""),
        "key_differentiators": rec.get("key_differentiators", []),
        "key_tasks":          _get_key_tasks(spd_item),
        "similar_projects":   _get_similar_projects(spd_item),
        "required_partners":  rec.get("required_partners", ""),
        # ── WPG 처리 상태 ────────────────────────────────────────
        "wpg_status": "PENDING",
        "wpg_proposal_path": "",
    }


def push_to_wpg_inbox(go_bids: list, source_file: str = "") -> list:
    """GO 공고들을 WPG spd_inbox 폴더에 저장"""
    if not WPG_INBOX_DIR:
        print("[WARN] WPG 루트를 찾을 수 없습니다.")
        return []
    os.makedirs(WPG_INBOX_DIR, exist_ok=True)
    pushed = []
    for bid in go_bids:
        wpg_item = convert_to_wpg_format(bid, source_file)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in wpg_item["bid_title"][:30])
        fname = f"spd_{ts}_{safe}.json"
        fpath = os.path.join(WPG_INBOX_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(wpg_item, f, ensure_ascii=False, indent=2)
        pushed.append(fpath)
        print(f"  ✅ WPG inbox → {fname}  [점수:{wpg_item['spd_score']} / {wpg_item['spd_decision']}]")
    return pushed


def run_bridge(min_score: int = 65, dry_run: bool = False) -> dict:
    """브릿지 실행 엔트리포인트"""
    print("=" * 60)
    print("  SPD → WPG 브릿지 v1.1")
    print("=" * 60)

    data = get_latest_analysis()
    if not data:
        print("[ERROR] SPD 분석 결과 파일 없음:", SPD_DATA_DIR)
        return {"pushed": 0, "skipped": 0, "files": []}

    src   = data.get("_source_file", "unknown")
    total = data.get("total_analyzed", len(data.get("analyses", [])))
    print(f"\n분석 파일: {src}  (전체 {total}건)")

    go_bids = filter_go_bids(data, min_score=min_score)
    skipped = total - len(go_bids)
    print(f"GO/CONDITIONAL: {len(go_bids)}건  |  NO-GO/미달: {skipped}건\n")

    for b in go_bids:
        print(f"  [{_get_decision(b):11s}] {_get_score(b):3d}점  {_get_title(b)[:40]}")

    if dry_run:
        print("\n[DRY RUN] inbox 저장 생략")
        return {"pushed": 0, "skipped": skipped, "files": [], "go_bids": go_bids}

    print(f"\nWPG inbox: {WPG_INBOX_DIR}")
    pushed_files = push_to_wpg_inbox(go_bids, src)
    print(f"\n완료: {len(pushed_files)}건 WPG inbox 투입")
    return {"pushed": len(pushed_files), "skipped": skipped, "files": pushed_files}


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    result = run_bridge(min_score=65, dry_run=dry)
    if result.get("files"):
        print("\n[다음 단계]")
        print("  WPG UI > spd_inbox 탭에서 공고 확인 후 '집요분석 시작' 클릭")
