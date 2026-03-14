#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD → WPG 브릿지 모듈
========================
SPD가 발굴한 GO 공고를 WPG 제안서 생성 파이프라인으로 자동 연결.

사용 시나리오:
  1. SPD GitHub Actions 실행 완료 → analysis_results JSON 생성
  2. 이 브릿지가 GO/CONDITIONAL 공고를 WPG inbox에 자동 투입
  3. WPG UI에서 inbox 아이콘 클릭 → 바로 집요분석 시작

Author: WKMG
Version: 1.0.0 (2026-03-14)
"""

import os, json, glob, shutil
from datetime import datetime
from typing import Optional

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
SPD_DATA_DIR    = os.path.join(_BASE, "data", "analysis_results")

WPG_ROOT = next((p for p in [
    r"C:\Users\yso\OneDrive\Documents\GitHub\WPG",
    r"C:\Users\wangk\OneDrive\Documents\GitHub\WPG",
] if os.path.isdir(p)), None)

WPG_INBOX_DIR = os.path.join(WPG_ROOT, "spd_inbox") if WPG_ROOT else None


# ─── 핵심 함수 ────────────────────────────────────────────────────────────────

def get_latest_analysis() -> Optional[dict]:
    """SPD 최신 분석 결과 JSON 반환"""
    if not os.path.isdir(SPD_DATA_DIR):
        return None
    files = sorted(glob.glob(os.path.join(SPD_DATA_DIR, "*.json")),
                   key=os.path.getmtime, reverse=True)
    # test_ 파일 제외, 실제 분석 결과만
    real_files = [f for f in files if "test" not in os.path.basename(f).lower()]
    target = real_files[0] if real_files else (files[0] if files else None)
    if not target:
        return None
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    data["_source_file"] = os.path.basename(target)
    return data


def filter_go_bids(analysis_data: dict, min_score: int = 65) -> list:
    """GO 또는 CONDITIONAL 공고만 추출 (점수 기준 필터)"""
    result = []
    for item in analysis_data.get("analyses", []):
        decision = item.get("analysis", {}).get("go_no_go", {}).get("decision", "NO-GO")
        score    = item.get("analysis", {}).get("scoring", {}).get("total_score", 0)
        if decision in ("GO", "CONDITIONAL") and score >= min_score:
            result.append(item)
    result.sort(key=lambda x: x["analysis"]["scoring"]["total_score"], reverse=True)
    return result


def convert_to_wpg_format(spd_item: dict, source_file: str = "") -> dict:
    """SPD 분석 결과 1건을 WPG inbox 형식으로 변환"""
    a   = spd_item.get("analysis", {})
    rec = a.get("strategic_recommendation", {})
    tasks = a.get("deliverables_analysis", {}).get("key_tasks", [])

    return {
        "wpg_inbox_version": "1.0",
        "created_at": datetime.now().isoformat(),
        "source": "SPD",
        "source_file": source_file,
        # ── WPG가 읽는 핵심 필드 ──────────────────────────────
        "bid_title":  spd_item.get("bid_title", ""),
        "agency":     spd_item.get("agency", ""),
        "budget_text": spd_item.get("budget_text", ""),
        "rfp_text":   f"{spd_item.get('bid_title','')} {spd_item.get('agency','')}",
        # ── SPD 분석 결과 (WPG 집요분석 참고용) ─────────────────
        "spd_score":       a.get("scoring", {}).get("total_score", 0),
        "spd_decision":    a.get("go_no_go", {}).get("decision", ""),
        "coverage_pct":    a.get("deliverables_analysis", {}).get("wkmg_coverage_pct", 0),
        "core_message":    rec.get("core_message", ""),
        "key_differentiators": rec.get("key_differentiators", []),
        "key_tasks": [
            {"task": t.get("task",""), "capability": t.get("capability",""),
             "partner": t.get("required_partner","")}
            for t in tasks
        ],
        "similar_projects": [p.get("project_name","") for p in spd_item.get("similar_projects", [])],
        "required_partners": rec.get("required_partners", ""),
        # ── WPG 처리 상태 ────────────────────────────────────────
        "wpg_status": "PENDING",   # PENDING → IN_PROGRESS → DONE
        "wpg_proposal_path": "",
    }


def push_to_wpg_inbox(go_bids: list, source_file: str = "") -> list:
    """GO 공고들을 WPG spd_inbox 폴더에 JSON으로 저장"""
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
    """브릿지 실행 엔트리포인트 — SPD 분석 결과 → WPG inbox"""
    print("=" * 60)
    print("  SPD → WPG 브릿지 실행")
    print("=" * 60)

    # 1. 최신 분석 파일 로드
    data = get_latest_analysis()
    if not data:
        print("[ERROR] SPD 분석 결과 파일 없음:", SPD_DATA_DIR)
        return {"pushed": 0, "skipped": 0, "files": []}

    src = data.get("_source_file", "unknown")
    total = data.get("total_analyzed", 0)
    print(f"\n분석 파일: {src}  (전체 {total}건)")

    # 2. GO/CONDITIONAL 필터링
    go_bids = filter_go_bids(data, min_score=min_score)
    skipped = total - len(go_bids)
    print(f"GO/CONDITIONAL: {len(go_bids)}건  |  NO-GO/미달: {skipped}건\n")

    for b in go_bids:
        score = b["analysis"]["scoring"]["total_score"]
        dec   = b["analysis"]["go_no_go"]["decision"]
        print(f"  [{dec:11s}] {score:3d}점  {b['bid_title'][:40]}")

    if dry_run:
        print("\n[DRY RUN] inbox 저장 생략")
        return {"pushed": 0, "skipped": skipped, "files": [], "go_bids": go_bids}

    # 3. WPG inbox에 저장
    print(f"\nWPG inbox: {WPG_INBOX_DIR}")
    pushed_files = push_to_wpg_inbox(go_bids, src)

    print(f"\n완료: {len(pushed_files)}건 WPG inbox 투입")
    return {"pushed": len(pushed_files), "skipped": skipped, "files": pushed_files}


# ─── 직접 실행 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    result = run_bridge(min_score=65, dry_run=dry)
    if result.get("files"):
        print("\n[다음 단계]")
        print("  WPG UI > spd_inbox 탭에서 공고 확인 후 '집요분석 시작' 클릭")
