#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Report Module v3.0 — DOCX 리포트 생성 + Gmail 호환 이메일 발송
===================================================================
spd_analysis_engine.py의 JSON 결과를 DOCX 리포트로 변환하고 이메일 발송.
v3: Gmail/Outlook 호환 table-based 레이아웃

사용법:
  python spd_report.py --input data/analysis_results/analysis_20260222.json
  python spd_report.py --input data/analysis_results/analysis_20260222.json --email
  python spd_report.py --latest --email

의존성:
  - Node.js + docx 패키지 (npm install docx)
  - spd_report_generator.js (같은 디렉토리)

Author: WKMG Automation (SPD System)
Version: 3.0.0
"""

import os, sys, json, glob, subprocess, argparse, smtplib, logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, Dict, List

log = logging.getLogger("spd_report")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JS_GENERATOR = os.path.join(SCRIPT_DIR, "spd_report_generator.js")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "data", "reports")


def load_config():
    """config.json 로드 + 환경변수 오버라이드 (GitHub Actions 호환)"""
    config = {}
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    
    # 환경변수 오버라이드 (GitHub Actions secrets 우선)
    env_email = {}
    if os.environ.get("SPD_SENDER_EMAIL"):
        env_email["sender_email"] = os.environ["SPD_SENDER_EMAIL"]
    if os.environ.get("SPD_SENDER_PASSWORD"):
        env_email["sender_password"] = os.environ["SPD_SENDER_PASSWORD"]
    if os.environ.get("SPD_SMTP_SERVER"):
        env_email["smtp_server"] = os.environ["SPD_SMTP_SERVER"]
    if os.environ.get("SPD_RECIPIENTS"):
        env_email["recipients"] = [r.strip() for r in os.environ["SPD_RECIPIENTS"].split(",")]
    
    if env_email:
        if "email" not in config:
            config["email"] = {}
        config["email"].update(env_email)
    
    return config


def find_latest_analysis(analysis_dir=None):
    """가장 최근 분석 결과 JSON 경로 반환"""
    if analysis_dir is None:
        analysis_dir = os.path.join(SCRIPT_DIR, "data", "analysis_results")
    if not os.path.isdir(analysis_dir):
        log.error(f"분석 결과 디렉토리 없음: {analysis_dir}")
        return None
    files = sorted(glob.glob(os.path.join(analysis_dir, "analysis_*.json")), reverse=True)
    if not files:
        log.error(f"분석 결과 파일 없음: {analysis_dir}")
        return None
    log.info(f"최신 분석 결과: {files[0]}")
    return files[0]


def ensure_node_deps():
    """Node.js docx 패키지가 설치되어 있는지 확인하고 없으면 설치"""
    node_modules = os.path.join(SCRIPT_DIR, "node_modules", "docx")
    if os.path.isdir(node_modules):
        return True
    log.info("📦 docx 패키지 설치 중...")
    try:
        result = subprocess.run(
            ["npm", "install", "docx"],
            capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR,
        )
        if result.returncode == 0:
            log.info("✅ docx 패키지 설치 완료")
            return True
        else:
            log.error(f"npm install 실패: {result.stderr}")
            return False
    except Exception as e:
        log.error(f"npm install 오류: {e}")
        return False


def generate_docx(input_json, output_docx=None):
    """Node.js 스크립트를 호출하여 DOCX 생성. Returns: 생성된 DOCX 파일 경로"""
    if not os.path.exists(input_json):
        log.error(f"입력 파일 없음: {input_json}")
        return None
    if not os.path.exists(JS_GENERATOR):
        log.error(f"JS 생성기 없음: {JS_GENERATOR}")
        return None

    if not ensure_node_deps():
        log.error("Node.js docx 패키지 설치 실패")
        return None

    if output_docx is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_docx = os.path.join(OUTPUT_DIR, f"SPD_리포트_{timestamp}.docx")

    log.info(f"📄 DOCX 생성 시작: {input_json} → {output_docx}")
    try:
        result = subprocess.run(
            ["node", JS_GENERATOR, input_json, output_docx],
            capture_output=True, text=True, timeout=60, cwd=SCRIPT_DIR,
        )
        if result.returncode != 0:
            log.error(f"DOCX 생성 실패: {result.stderr}")
            return None
        log.info(result.stdout.strip())
        if os.path.exists(output_docx):
            size_kb = os.path.getsize(output_docx) / 1024
            log.info(f"✅ DOCX 생성 완료: {output_docx} ({size_kb:.0f}KB)")
            return output_docx
        else:
            log.error("DOCX 파일이 생성되지 않음")
            return None
    except subprocess.TimeoutExpired:
        log.error("DOCX 생성 타임아웃 (60초)")
        return None
    except Exception as e:
        log.error(f"DOCX 생성 오류: {e}")
        return None


def build_email_body(input_json):
    """분석 결과 JSON에서 Gmail 호환 이메일 본문(HTML) 생성 — v3 table-based 디자인"""
    try:
        with open(input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"<p>분석 결과 로드 실패: {e}</p>"

    analyses = data.get("analyses", [])
    gen_at = data.get("generated_at", "")[:10]
    total = data.get("total_analyzed", len(analyses))
    ver = data.get("prompt_version", "v3")

    # --- 분석 항목 파싱 ---
    items = []
    for a in analyses:
        gpt = a.get("analysis", {})
        scoring = gpt.get("scoring", {})
        go_nogo = gpt.get("go_no_go", {})
        deliv = gpt.get("deliverables_analysis", {})
        strat = gpt.get("strategic_recommendation", {})
        total_score = scoring.get("total_score", 0) if isinstance(scoring, dict) else 0
        decision = go_nogo.get("decision", "UNKNOWN") if isinstance(go_nogo, dict) else str(go_nogo)
        items.append({
            "title": a.get("bid_title") or a.get("title", "제목 없음"),
            "agency": a.get("agency", ""),
            "budget": a.get("budget_text") or a.get("budget_str", ""),
            "url": a.get("url", ""),
            "score": total_score,
            "decision": decision,
            "scoring": scoring if isinstance(scoring, dict) else {},
            "deliverables": deliv if isinstance(deliv, dict) else {},
            "strategy": strat if isinstance(strat, dict) else {},
            "similar": a.get("similar_projects", gpt.get("similar_projects", [])),
            "go_conditions": go_nogo.get("conditions", []) if isinstance(go_nogo, dict) else []
        })
    items.sort(key=lambda x: x["score"], reverse=True)

    # --- 통계 ---
    go_c = sum(1 for i in items if i["decision"] == "GO")
    cond_c = sum(1 for i in items if i["decision"] == "CONDITIONAL")
    nogo_c = sum(1 for i in items if i["decision"] == "NO-GO")
    date_str = gen_at or datetime.now().strftime("%Y-%m-%d")

    # --- 헬퍼 함수 ---
    def _badge(decision):
        if decision == "GO":
            return '<span style="display:inline-block;padding:2px 10px;border-radius:3px;font-size:11px;font-weight:700;background:#d4edda;color:#155724">GO</span>'
        elif decision == "CONDITIONAL":
            return '<span style="display:inline-block;padding:2px 10px;border-radius:3px;font-size:11px;font-weight:700;background:#fff3cd;color:#856404">CONDITIONAL</span>'
        else:
            return '<span style="display:inline-block;padding:2px 10px;border-radius:3px;font-size:11px;font-weight:700;background:#f8d7da;color:#721c24">NO-GO</span>'

    def _score_color(s):
        if s >= 75: return "#28a745"
        if s >= 55: return "#856404"
        return "#dc3545"

    # --- 총괄표 행 ---
    rows_html = ""
    for it in items:
        # v3: NO-GO는 color:#aaa (opacity 대신)
        nogo_style = 'color:#aaa;' if it["decision"] == "NO-GO" else ""
        bold_open = "<strong>" if it["decision"] == "GO" else ""
        bold_close = "</strong>" if it["decision"] == "GO" else ""
        title_display = it['title'][:45]
        if it.get('url'):
            title_display = f'<a href="{it["url"]}" target="_blank" style="color:inherit;text-decoration:underline">{title_display}</a>'
        rows_html += f'''<tr>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;{nogo_style}">{bold_open}{title_display}{bold_close}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;{nogo_style}">{it['agency'][:12]}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;text-align:right;{nogo_style}">{it['budget']}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;text-align:center;font-weight:800;color:{_score_color(it['score'])}">{it['score']}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;text-align:center">{_badge(it['decision'])}</td>
        </tr>'''

    # === GO 상세 섹션 (최고점 GO 1건, 없으면 최고점 CONDITIONAL) ===
    go_items = [i for i in items if i["decision"] == "GO"]
    cond_items = [i for i in items if i["decision"] == "CONDITIONAL"]
    featured = go_items[0] if go_items else (cond_items[0] if cond_items else None)

    go_section_html = ""
    if featured:
        is_go = featured["decision"] == "GO"
        accent = "#28a745" if is_go else "#e6a817"
        bg_color = "#f8fdf9" if is_go else "#fffdf5"
        label_text = "GO — 적극 참여 추천" if is_go else "CONDITIONAL — 조건부 참여 검토"

        sc = featured["scoring"]
        def _safe_score(v):
            return v.get("score", 0) if isinstance(v, dict) else (int(v) if isinstance(v, (int, float)) else 0)
        d1 = _safe_score(sc.get("domain_expertise", 0))
        d2 = _safe_score(sc.get("competitive_advantage", 0))
        d3 = _safe_score(sc.get("win_probability", 0))
        d4 = _safe_score(sc.get("track_record", 0))
        total_s = featured["score"]

        # v3: table-based 프로그레스 바 (flex/linear-gradient 제거)
        def _bar_v3(label, val, max_v=25):
            pct = int(val / max_v * 100) if max_v > 0 else 0
            fill_color = "#28a745" if pct >= 80 else "#2E75B6"
            return f'''<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:6px">
              <tr>
                <td width="90" style="font-size:12px;color:#555;text-align:right;padding-right:8px">{label}</td>
                <td style="padding:0">
                  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#e9ecef;border-radius:3px">
                    <tr><td width="{pct}%" style="background:{fill_color};height:20px;border-radius:3px;font-size:1px">&nbsp;</td><td style="font-size:1px">&nbsp;</td></tr>
                  </table>
                </td>
                <td width="42" style="font-size:13px;font-weight:800;color:#333;text-align:right;padding-left:8px">{val}/{max_v}</td>
              </tr>
            </table>'''

        bars_html = _bar_v3("도메인 전문성", d1) + _bar_v3("경쟁우위", d2) + _bar_v3("수주 가능성", d3) + _bar_v3("수행실적", d4)

        # v3: 유사 프로젝트 — table rows
        similar = featured.get("similar", [])
        similar_html = ""
        if similar:
            sim_rows = ""
            for sp in similar[:5]:
                if isinstance(sp, dict):
                    name = sp.get("project_name") or sp.get("name") or sp.get("title") or sp.get("filename") or ""
                    if not name or name == "unknown":
                        # fallback: year + client + domain 조합
                        parts = [sp.get("year",""), sp.get("client",""), sp.get("domain",""), sp.get("category","")]
                        name = " ".join(p for p in parts if p and p != "unknown")
                    if not name:
                        name = sp.get("preview", str(sp))[:60]
                    # similarity 표시
                    sim_val = sp.get("similarity", 0)
                    if isinstance(sim_val, (int, float)) and sim_val > 0:
                        name += f" ({sim_val*100:.0f}%" if sim_val <= 1 else f" ({sim_val:.0f}%"
                        name += " 유사)"
                else:
                    name = str(sp)
                sim_rows += f'<tr><td style="font-size:12px;color:#444;padding:3px 6px;border-bottom:1px solid #d4edda">&#8226; {name[:60]}</td></tr>'
            similar_html = f'''<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:8px;margin-left:98px;max-width:480px">
              <tr><td style="padding:10px 14px;background:#eef6ee;border-radius:5px;border-left:3px solid {accent}">
                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                  <tr><td style="font-size:11px;font-weight:700;color:#1B365D;padding-bottom:5px">✦ 과거 유사 용역 경험</td></tr>
                  {sim_rows}
                </table>
              </td></tr>
            </table>'''

        # v3: 세부 과업 분석 — table rows
        deliv = featured.get("deliverables", {})
        tasks = deliv.get("key_tasks", [])
        coverage = deliv.get("wkmg_coverage_pct", 0)
        tasks_html = ""
        if tasks:
            task_rows = ""
            for t in tasks[:6]:
                if isinstance(t, dict):
                    tname = t.get("task", t.get("name", ""))
                    cap = t.get("capability", t.get("wkmg_capability", "중"))
                    partner = t.get("required_partner", t.get("partner", ""))
                else:
                    tname, cap, partner = str(t), "중", ""
                if cap in ("상", "높음", "high"):
                    cap_bg, cap_color, cap_label = "#d4edda", "#155724", "● 상"
                elif cap in ("중", "보통", "medium"):
                    cap_bg, cap_color, cap_label = "#fff3cd", "#856404", "◐ 중"
                else:
                    cap_bg, cap_color, cap_label = "#f8d7da", "#721c24", "○ 하"
                partner_tag = f' <span style="font-size:10px;color:#2E75B6;background:#e8f0fe;padding:1px 6px;border-radius:2px">파트너: {partner}</span>' if partner else ""
                task_rows += f'''<tr>
                  <td style="padding:6px 8px;border-bottom:1px solid #e8f5e9;font-size:13px;color:#333">{tname[:50]}</td>
                  <td width="60" style="padding:6px 4px;border-bottom:1px solid #e8f5e9;text-align:center">
                    <span style="font-size:11px;font-weight:700;padding:1px 6px;border-radius:2px;background:{cap_bg};color:{cap_color}">{cap_label}</span>
                  </td>
                  <td width="100" style="padding:6px 4px;border-bottom:1px solid #e8f5e9;font-size:10px;color:#2E75B6">{partner_tag}</td>
                </tr>'''
            tasks_html = f'''<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:18px 0">
              <tr><td style="font-size:13px;font-weight:700;color:#1B365D;padding-bottom:8px">📋 세부 과업 분석 ({len(tasks)}개 · WKMG 커버리지 {coverage}%)</td></tr>
              <tr><td>
                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                  {task_rows}
                </table>
              </td></tr>
            </table>'''

        # 전략 메시지
        strat = featured.get("strategy", {})
        core_msg = strat.get("core_message", "")
        diffs = strat.get("key_differentiators", strat.get("key_points", []))
        partners = strat.get("required_partners", strat.get("partners", ""))
        strategy_html = ""
        if core_msg:
            diff_rows = ""
            for d in (diffs[:4] if isinstance(diffs, list) else []):
                diff_rows += f'<tr><td style="font-size:13px;color:#444;padding:3px 0;padding-left:16px">▸ {d}</td></tr>'
            partner_line = f'<tr><td style="padding-top:10px;border-top:1px solid #eee;font-size:12px;color:#666"><strong style="color:#333">필요 파트너:</strong> {partners}</td></tr>' if partners else ""
            strategy_html = f'''<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:18px 0;border:1px solid #e0e0e0;border-radius:6px">
              <tr><td style="padding:14px 16px;background:#ffffff">
                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                  <tr><td style="font-size:15px;font-weight:700;color:#1B365D;padding-bottom:10px;line-height:1.4">🎯 &quot;{core_msg}&quot;</td></tr>
                  {diff_rows}
                  {partner_line}
                </table>
              </td></tr>
            </table>'''

        go_section_html = f'''
        <tr><td style="padding:24px 32px;background:{bg_color};border-top:3px solid {accent}">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td width="38" style="vertical-align:top">
                <div style="background:{accent};color:#fff;width:28px;height:28px;border-radius:50%;text-align:center;line-height:28px;font-size:14px;font-weight:800">&#10003;</div>
              </td>
              <td style="font-size:12px;font-weight:700;color:{accent};letter-spacing:1px;vertical-align:middle">{label_text}</td>
            </tr>
          </table>
          <div style="font-size:17px;font-weight:700;color:#1B365D;margin:8px 0 4px;line-height:1.4">{'<a href="' + featured["url"] + '" target="_blank" style="color:#1B365D;text-decoration:underline">' + featured["title"] + '</a>' if featured.get("url") else featured["title"]}</div>
          <div style="font-size:13px;color:#666;margin-bottom:16px">
            <strong style="color:#333">{featured['agency']}</strong> &#183; 예산 <strong style="color:#333">{featured['budget']}</strong>{'  &#183;  <a href="' + featured["url"] + '" target="_blank" style="color:#2E75B6;font-size:11px;text-decoration:none">📎 공고 원문 보기</a>' if featured.get("url") else ''}
          </div>
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:16px 0">
            <tr>
              <td width="80" style="vertical-align:top">
                <div style="font-size:36px;font-weight:800;color:{accent};line-height:1">{total_s}</div>
                <div style="font-size:14px;color:#999">/100점</div>
              </td>
              <td style="vertical-align:top;padding-left:12px">
                {bars_html}
              </td>
            </tr>
          </table>
          {similar_html}
          {tasks_html}
          {strategy_html}
        </td></tr>'''

    # === DOCX 파일명 ===
    docx_name = f"SPD_리포트_{gen_at.replace('-', '')}.docx"

    # === 최종 HTML 조립 — v3 table-based (Gmail/Outlook 호환) ===
    html = f'''<table cellpadding="0" cellspacing="0" border="0" width="680" align="center" style="background:#ffffff;border-radius:8px;overflow:hidden;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif">

  <!-- 헤더 -->
  <tr><td style="background:#1B365D;padding:28px 32px">
    <div style="color:#8899b3;font-size:10px;letter-spacing:2.5px;text-transform:uppercase;margin-bottom:6px">WKMG &#183; STRATEGIC PROCUREMENT DASHBOARD</div>
    <table cellpadding="0" cellspacing="0" border="0" width="100%">
      <tr>
        <td style="color:#ffffff;font-size:22px;font-weight:700;line-height:1.3">&#128202; SPD 일일 분석 리포트</td>
        <td style="color:#8899b3;font-size:13px;font-weight:400;letter-spacing:0.5px;padding-left:14px;border-left:1px solid #4a5f80;text-align:right">대한민국 마케팅 No.1 전문가 그룹</td>
      </tr>
    </table>
    <div style="color:#8899b3;font-size:12px;margin-top:10px"><span style="display:inline-block;background:#2a4a75;padding:3px 12px;border-radius:4px">{date_str} &#183; 오전 9시 자동 분석</span></div>
  </td></tr>

  <!-- 대시보드 요약 -->
  <tr><td style="padding:24px 32px;border-bottom:1px solid #e8eaed">
    <table cellpadding="0" cellspacing="0" border="0" width="100%">
      <tr>
        <td style="font-size:14px;font-weight:700;color:#1B365D">오늘의 입찰 분석 현황</td>
        <td style="font-size:11px;color:#888;text-align:right">RFP RADAR 예비후보 대상 정밀 평가</td>
      </tr>
    </table>
    <!-- 4칸 대시보드 — td width 25% -->
    <table cellpadding="0" cellspacing="8" border="0" width="100%" style="margin:14px 0 18px">
      <tr>
        <td width="25%" style="text-align:center;padding:14px 8px;border-radius:8px;background:#f0f4f8">
          <div style="font-size:28px;font-weight:800;line-height:1;color:#1B365D">{total}</div>
          <div style="font-size:11px;color:#666;margin-top:4px;letter-spacing:0.5px">분석 공고</div>
        </td>
        <td width="25%" style="text-align:center;padding:14px 8px;border-radius:8px;background:#d4edda">
          <div style="font-size:28px;font-weight:800;line-height:1;color:#28a745">{go_c}</div>
          <div style="font-size:11px;color:#666;margin-top:4px;letter-spacing:0.5px">GO</div>
        </td>
        <td width="25%" style="text-align:center;padding:14px 8px;border-radius:8px;background:#fff3cd">
          <div style="font-size:28px;font-weight:800;line-height:1;color:#856404">{cond_c}</div>
          <div style="font-size:11px;color:#666;margin-top:4px;letter-spacing:0.5px">CONDITIONAL</div>
        </td>
        <td width="25%" style="text-align:center;padding:14px 8px;border-radius:8px;background:#f8d7da">
          <div style="font-size:28px;font-weight:800;line-height:1;color:#dc3545">{nogo_c}</div>
          <div style="font-size:11px;color:#666;margin-top:4px;letter-spacing:0.5px">NO-GO</div>
        </td>
      </tr>
    </table>
    <!-- 총괄표 -->
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-size:13px">
      <tr>
        <th style="background:#1B365D;color:#fff;padding:8px 10px;text-align:left;font-weight:600;font-size:11px;letter-spacing:0.5px;width:42%">공고명</th>
        <th style="background:#1B365D;color:#fff;padding:8px 10px;text-align:left;font-weight:600;font-size:11px;letter-spacing:0.5px;width:18%">발주기관</th>
        <th style="background:#1B365D;color:#fff;padding:8px 10px;text-align:right;font-weight:600;font-size:11px;letter-spacing:0.5px;width:16%">예산</th>
        <th style="background:#1B365D;color:#fff;padding:8px 10px;text-align:center;font-weight:600;font-size:11px;letter-spacing:0.5px;width:10%">점수</th>
        <th style="background:#1B365D;color:#fff;padding:8px 10px;text-align:center;font-weight:600;font-size:11px;letter-spacing:0.5px;width:14%">판정</th>
      </tr>
      {rows_html}
    </table>
  </td></tr>

  <!-- GO 상세 분석 -->
  {go_section_html}

  <!-- 푸터 -->
  <tr><td style="padding:20px 32px;background:#f8f9fa;border-top:1px solid #e8eaed">
    <div style="font-size:14px;font-weight:800;color:#1B365D;margin-bottom:10px">[제안 전략] 리포트 참조</div>
    <div style="font-size:13px;color:#333;margin-bottom:6px">
      &#128206; 전체 상세 분석 리포트
      <span style="display:inline-block;background:#2E75B6;color:#fff;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:600;margin-left:4px">{docx_name}</span>
    </div>
    <div style="font-size:12px;color:#dc3545;font-weight:700;margin-top:10px;line-height:1.5;padding:8px 12px;background:#fff5f5;border-radius:4px;border-left:3px solid #dc3545">
      &#9888; 조건부 입찰 대상(CONDITIONAL) 용역도 매우 중요한 건이니 리포트 내용 반드시 확인 바랍니다.
    </div>
    <div style="font-size:11px;color:#999;line-height:1.5;margin-top:14px">
      &#8251; 본 리포트는 SPD {ver} 자동 분석 시스템이 생성했습니다.<br>
      &#8251; GO 공고는 영업팀 검토 후 입찰 진행을 결정해주세요.<br>
      &#8251; CONDITIONAL 공고의 상세 조건은 첨부 DOCX를 참조하세요.
    </div>
    <div style="font-size:10px;color:#bbb;margin-top:8px;letter-spacing:1px">WKMG STRATEGIC PROCUREMENT DASHBOARD &#183; SPD v3.0</div>
  </td></tr>

</table>'''
    return html


def send_email(docx_path, html_body, config):
    """DOCX 리포트를 이메일로 발송"""
    email_cfg = config.get("email", config)
    smtp_server = email_cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = email_cfg.get("smtp_port", 587)
    sender_email = email_cfg.get("sender_email", "")
    sender_password = email_cfg.get("sender_password", "")
    recipients = email_cfg.get("recipients", [])

    if not sender_email or not sender_password or not recipients:
        log.error("이메일 설정 불완전 (sender_email, sender_password, recipients 필요)")
        return False

    today = datetime.now().strftime("%Y.%m.%d")
    subject = f"SPD 일일 분석 리포트 | 대한민국 마케팅 No.1 전문가 그룹 — {today}"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # DOCX 첨부 (한글 파일명 RFC 2231 인코딩)
    if docx_path and os.path.exists(docx_path):
        with open(docx_path, "rb") as f:
            part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(docx_path)
        # ASCII 안전한 fallback + UTF-8 filename* 파라미터
        ascii_name = f"SPD_Report_{today.replace('.','')}.docx"
        part.add_header(
            "Content-Disposition", "attachment",
            filename=ascii_name  # ASCII fallback
        )
        # RFC 2231 UTF-8 파라미터 추가 (한글 파일명 지원)
        part.set_param("filename*", f"UTF-8''{filename}", header="Content-Disposition", charset="utf-8")
        msg.attach(part)
        log.info(f"📎 첨부: {filename} (fallback: {ascii_name})")

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        log.info(f"✅ 이메일 발송 완료 → {len(recipients)}명")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("이메일 인증 실패 — 앱 비밀번호를 사용하세요 (Gmail 2단계 인증)")
        return False
    except Exception as e:
        log.error(f"이메일 발송 실패: {e}")
        return False


def generate_summary_stats(input_json):
    """분석 결과 통계 출력 (CLI용)"""
    try:
        with open(input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"분석 결과 로드 실패: {e}")
        return

    analyses = data.get("analyses", [])
    ver = data.get("prompt_version", "v3")
    cost = data.get("total_cost_estimate", "$0")

    print(f"\n{'='*60}")
    print(f"  SPD 분석 결과 요약 ({ver})")
    print(f"{'='*60}")
    print(f"  분석 공고: {len(analyses)}건 | 비용: {cost}")
    print(f"{'-'*60}")

    items = []
    for a in analyses:
        gpt = a.get("analysis", {})
        scoring = gpt.get("scoring", {})
        go_nogo = gpt.get("go_no_go", {})
        deliv = gpt.get("deliverables_analysis", {})
        total_score = scoring.get("total_score", 0) if isinstance(scoring, dict) else 0
        decision = go_nogo.get("decision", "UNKNOWN") if isinstance(go_nogo, dict) else str(go_nogo)
        coverage = deliv.get("wkmg_coverage_pct", 0) if isinstance(deliv, dict) else 0
        items.append({
            "title": a.get("bid_title") or a.get("title", "?"),
            "agency": a.get("agency", "?"),
            "score": total_score,
            "decision": decision,
            "coverage": coverage
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    for it in items:
        icon = "🟢" if it["decision"] == "GO" else ("🟡" if it["decision"] == "CONDITIONAL" else "🔴")
        print(f"  {icon} [{it['score']:3d}점] {it['decision']:<12s} {it['title'][:30]}  ({it['agency']}, 커버리지 {it['coverage']}%)")

    go_c = sum(1 for i in items if i["decision"] == "GO")
    cond_c = sum(1 for i in items if i["decision"] == "CONDITIONAL")
    nogo_c = sum(1 for i in items if i["decision"] == "NO-GO")
    print(f"{'-'*60}")
    print(f"  GO: {go_c}건 | CONDITIONAL: {cond_c}건 | NO-GO: {nogo_c}건")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════
# MAIN — CLI 인터페이스
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SPD Report — DOCX 리포트 생성 및 이메일 발송")
    parser.add_argument("--input", "-i", help="분석 결과 JSON 파일 경로")
    parser.add_argument("--latest", action="store_true", help="가장 최근 분석 결과 사용")
    parser.add_argument("--output", "-o", help="출력 DOCX 파일 경로")
    parser.add_argument("--email", action="store_true", help="이메일 발송")
    parser.add_argument("--stats-only", action="store_true", help="통계만 출력 (DOCX 미생성)")
    args = parser.parse_args()

    # 1. 입력 파일 결정
    input_json = args.input
    if not input_json and args.latest:
        input_json = find_latest_analysis()
    if not input_json:
        log.error("입력 파일을 지정하세요: --input <path> 또는 --latest")
        sys.exit(1)
    if not os.path.exists(input_json):
        log.error(f"파일 없음: {input_json}")
        sys.exit(1)

    log.info(f"📂 입력: {input_json}")

    # 2. 통계 출력
    generate_summary_stats(input_json)

    if args.stats_only:
        return

    # 3. DOCX 생성
    log.info("=" * 50)
    log.info("Phase 1: DOCX 리포트 생성")
    log.info("=" * 50)
    docx_path = generate_docx(input_json, args.output)

    # 4. 이메일 발송 (옵션)
    if args.email:
        log.info("=" * 50)
        log.info("Phase 2: 이메일 발송")
        log.info("=" * 50)
        config = load_config()
        html_body = build_email_body(input_json)
        send_email(docx_path, html_body, config)

    # 5. 완료 요약
    print(f"\n{'='*50}")
    print(f"  SPD Report 완료")
    print(f"{'='*50}")
    if docx_path:
        size_kb = os.path.getsize(docx_path) / 1024
        print(f"  📄 DOCX: {docx_path} ({size_kb:.0f}KB)")
    if args.email:
        print(f"  📧 이메일: 발송 {'완료' if docx_path else '실패'}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
