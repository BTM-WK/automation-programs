#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Report Module v1.0 — DOCX 리포트 생성 + 이메일 발송
=========================================================
spd_analysis_engine.py의 JSON 결과를 DOCX 리포트로 변환하고 이메일 발송.

사용법:
  python spd_report.py --input data/analysis_results/analysis_20260222.json
  python spd_report.py --input data/analysis_results/analysis_20260222.json --email
  python spd_report.py --latest --email

의존성:
  - Node.js + docx 패키지 (npm install docx)
  - spd_report_generator.js (같은 디렉토리)

Author: WKMG Automation (SPD System)
Version: 1.0.0
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

    # Node.js 의존성 확인
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
    """분석 결과 JSON에서 이메일 본문(HTML) 생성"""
    try:
        with open(input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"<p>분석 결과 로드 실패: {e}</p>"

    analyses = data.get("analyses", [])
    gen_at = data.get("generated_at", "")[:10]
    total = data.get("total_analyzed", len(analyses))
    cost = data.get("total_cost_estimate", "$0")
    ver = data.get("prompt_version", "v3")

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
            "title": a.get("bid_title", "제목 없음"),
            "agency": a.get("agency", ""),
            "budget": a.get("budget_text", ""),
            "score": total_score,
            "decision": decision,
            "coverage": coverage
        })
    items.sort(key=lambda x: x["score"], reverse=True)

    go_c = sum(1 for i in items if i["decision"] == "GO")
    cond_c = sum(1 for i in items if i["decision"] == "CONDITIONAL")
    nogo_c = sum(1 for i in items if i["decision"] == "NO-GO")

    def badge(d):
        colors = {"GO": "#28a745", "CONDITIONAL": "#ffc107", "NO-GO": "#dc3545"}
        bg = colors.get(d, "#6c757d")
        tc = "#000" if d == "CONDITIONAL" else "#fff"
        return f'<span style="background:{bg};color:{tc};padding:2px 8px;border-radius:3px;font-weight:bold;font-size:12px">{d}</span>'

    def sc(s):
        if s >= 75: return "#28a745"
        if s >= 55: return "#856404"
        return "#dc3545"

    rows_html = ""
    for it in items:
        rows_html += f'''<tr>
          <td style="padding:6px 8px">{it['title'][:35]}</td>
          <td style="padding:6px 8px">{it['agency']}</td>
          <td style="padding:6px 8px;text-align:right">{it['budget']}</td>
          <td style="padding:6px 8px;text-align:center;font-weight:bold;color:{sc(it['score'])}">{it['score']}점</td>
          <td style="padding:6px 8px;text-align:center">{badge(it['decision'])}</td>
          <td style="padding:6px 8px;text-align:center">{it['coverage']}%</td>
        </tr>'''

    html = f'''<div style="font-family:Arial,sans-serif;max-width:700px;margin:auto">
      <h2 style="color:#1B365D;border-bottom:2px solid #2E75B6;padding-bottom:8px">SPD 분석 리포트 — {gen_at}</h2>
      <p style="color:#666">분석 {total}건 | 프롬프트 {ver} | 비용 {cost} |
        <span style="color:#28a745;font-weight:bold">GO {go_c}</span> /
        <span style="color:#856404;font-weight:bold">COND {cond_c}</span> /
        <span style="color:#dc3545;font-weight:bold">NO-GO {nogo_c}</span></p>
      <table style="border-collapse:collapse;width:100%;font-size:13px;margin:15px 0">
        <tr style="background:#1B365D;color:#fff">
          <th style="padding:8px">공고명</th><th style="padding:8px">발주기관</th>
          <th style="padding:8px">예산</th><th style="padding:8px">점수</th>
          <th style="padding:8px">판정</th><th style="padding:8px">커버리지</th>
        </tr>{rows_html}</table>
      <p style="color:#999;font-size:11px;margin-top:20px">
        WKMG Strategic Procurement Dashboard — SPD v3.0<br>상세 분석은 첨부 DOCX 파일을 참조하세요.</p>
    </div>'''
    return html


def send_email(docx_path, html_body, config):
    """DOCX 리포트를 이메일로 발송"""
    email_cfg = config.get("email", config)  # config.email 또는 config 직접
    smtp_server = email_cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = email_cfg.get("smtp_port", 587)
    sender_email = email_cfg.get("sender_email", "")
    sender_password = email_cfg.get("sender_password", "")
    recipients = email_cfg.get("recipients", [])

    if not sender_email or not sender_password or not recipients:
        log.error("이메일 설정 불완전 (sender_email, sender_password, recipients 필요)")
        return False

    today = datetime.now().strftime("%Y.%m.%d")
    subject = f"[SPD v3] 입찰 분석 리포트 — {today}"

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # DOCX 첨부
    if docx_path and os.path.exists(docx_path):
        with open(docx_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(docx_path)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)
        log.info(f"📎 첨부: {filename}")

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
            "title": a.get("bid_title", "?"),
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
