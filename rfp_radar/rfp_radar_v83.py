# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║  RFP Radar v8.3                                                      ║
║  공공기관 마케팅 용역 입찰 추천 시스템 (통합 크롤링)                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  버전: v8.3 (2026-02-12)                                             ║
║  개발: WKMG (WK Marketing Group)                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  주요 기능:                                                           ║
║  - 나라장터 API (81개 기관 커버)                                       ║
║  - 47개 기관 직접 크롤링 + GPT HTML 파싱                               ║
║  - MASTER_DB 128개 기관 완전 커버                                     ║
║  - 4개 핵심 영역 스코어링 + GPT 2단계 평가                             ║
║  - WKMG 수행기관 24개 가산점 반영                                     ║
║  - fingerprint 중복 제거 + 이메일 자동 발송                            ║
╠══════════════════════════════════════════════════════════════════════╣
║  v8.3 변경사항:                                                       ║
║  - 차세대 나라장터 URL 수정 (통합검색 URL + 공고번호 표시)              ║
║  - 이메일 2섹션: 우선추천(5천만+) / 저예산 Quick Win(3~5천만)           ║
║  - AI/디지털전환 키워드 추가 (4개 영역 + 산업 가산점)                   ║
║  - 예산구간별 scale_score 차별화                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  v8.2 변경사항:                                                       ║
║  - GPT 프롬프트 개선: 홍보마케팅 적합 판단 완화                         ║
║  - "컨설팅/전략/기획/마케팅+운영용역" 감점 경감(-7점) 로직              ║
║  - 산업키워드 확대 (장애인기업, 여성기업 등)                            ║
║  - G2B 공고 URL 패턴 업데이트 (차세대 나라장터 대응)                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import requests
import json
import os
import sys
import hashlib
import time
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import urllib3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding='utf-8')

VERSION = "8.3"

# =============================================================================
# 경로 설정
# =============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
SITES_DB_FILE = os.path.join(SCRIPT_DIR, "sites_db.json")

# =============================================================================
# 설정 로드
# =============================================================================
def load_config():
    default_config = {
        "service_key": "",
        "openai_api_key": "",
        "sender_email": "",
        "sender_password": "",
        "recipient_email": "",
        "recipient_emails": [],
        "api_url": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc",
        "num_of_rows": 100,
        "max_pages": 100,
        "search_days": 7,
        "data_dir": os.path.join(SCRIPT_DIR, "data", "daily_reports"),
        "use_gpt": True,
        "gpt_threshold": 55,
        "send_email": True,
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "crawl_enabled": True,
        "crawl_timeout": 15,
        "crawl_delay": 1.0,
        "crawl_priority_only": False,
        "gpt_parse_model": "gpt-4o-mini",
    }
    
    # ★ v8.2: 환경변수 우선 → config.json fallback (GitHub Actions 지원)
    env_mappings = {
        "RFP_SERVICE_KEY": "service_key",
        "RFP_OPENAI_API_KEY": "openai_api_key",
        "RFP_SENDER_EMAIL": "sender_email",
        "RFP_SENDER_PASSWORD": "sender_password",
        "RFP_RECIPIENT_EMAIL": "recipient_email",
        "RFP_RECIPIENT_EMAILS": "recipient_emails",  # 콤마 구분
    }
    
    env_loaded = False
    for env_key, config_key in env_mappings.items():
        env_val = os.environ.get(env_key)
        if env_val:
            if config_key == "recipient_emails":
                default_config[config_key] = [e.strip() for e in env_val.split(",")]
            else:
                default_config[config_key] = env_val
            env_loaded = True
    
    if env_loaded:
        print(f"  ✅ 환경변수에서 설정 로드 (GitHub Actions 모드)")
    
    # config.json이 있으면 추가 로드 (환경변수가 우선)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                # 환경변수로 이미 설정된 키는 덮어쓰지 않음
                for k, v in file_config.items():
                    if k not in [env_mappings.get(ek) for ek in env_mappings if os.environ.get(ek)]:
                        default_config[k] = v
                print(f"  ✅ 설정 로드: config.json")
        except Exception as e:
            print(f"  ❌ config.json 로드 실패: {e}")
            if not env_loaded:
                sys.exit(1)
    elif not env_loaded:
        print(f"  ❌ config.json 파일이 없고 환경변수도 없습니다.")
        sys.exit(1)
    
    required = ["service_key"]
    for key in required:
        if not default_config.get(key):
            print(f"  ❌ 필수 설정 누락: {key}")
            sys.exit(1)
    
    return default_config

def load_sites_db():
    """sites_db.json 로드 (v8.1: G2B/WEB_CRAWL 분류 통계 표시)"""
    if not os.path.exists(SITES_DB_FILE):
        print(f"  ⚠️ sites_db.json 없음 → 나라장터 API만 사용")
        return {"sites": []}
    try:
        with open(SITES_DB_FILE, 'r', encoding='utf-8') as f:
            db = json.load(f)
            sites = db.get("sites", [])
            enabled = [s for s in sites if s.get("enabled", True)]
            g2b = len([s for s in enabled if s['collect_method'] == 'G2B_API'])
            crawl = len([s for s in enabled if s['collect_method'] == 'WEB_CRAWL'])
            wkmg = len([s for s in enabled if s.get('wkmg_partner')])
            db_ver = db.get("_meta", {}).get("version", "?")
            print(f"  ✅ 기관 DB v{db_ver}: {len(enabled)}개 기관 (G2B:{g2b} + 크롤링:{crawl}) | WKMG파트너:{wkmg}개")
            return db
    except Exception as e:
        print(f"  ❌ sites_db.json 로드 실패: {e}")
        return {"sites": []}

CONFIG = load_config()
SITES_DB = load_sites_db()

# =============================================================================
# ★ v8.3: 예산 분류 기준
# =============================================================================
MIN_BUDGET = 30000000          # 최소 배제선: 3천만원 미만 제외
PRIORITY_BUDGET = 50000000     # 우선추천 기준: 5천만원 이상
# 3천만~5천만 = 저예산 Quick Win


# =============================================================================
# 배제 키워드 (163개)
# =============================================================================
EXCLUSIONS = [
    "교육여행", "수학여행", "체험학습", "해외연수", "영어체험", "어학연수",
    "글로벌리더", "영어캠프", "해외캠프", "리더십프로그램", "글로컬리더십",
    "수련활동", "수련원", "청소년수련", "인재양성", "인력양성", "교육훈련",
    "역량강화", "역량강화교육", "교육영상", "교육프로그램", "연수프로그램",
    "의료기기", "의약품", "의약정보", "헬스케어", "임상", "진료", "처방",
    "시스템구축", "시스템개발", "플랫폼구축", "플랫폼개발",
    "앱개발", "웹개발", "DB구축", "정보화사업", "클라우드구축", "SW개발",
    "아키텍처개발", "개방형아키텍처", "공통아키텍처",
    "스포츠산업", "체육진흥", "스포츠클럽", "체육시설", "스포츠마케팅",
    "시설구축", "가공유통시설", "설계용역", "기본설계", "실시설계",
    "구축사업", "건립사업", "도시재생", "도시계획", "건축설계", "조경공사",
    "기획운영", "기획 및 운영", "운영대행", "전시운영", "전시대행",
    "박람회운영", "페어운영", "환영주간", "방문주간",
    "개막식", "폐막식", "기념식", "축제운영", "공연운영",
    "운송통관", "통관대행", "샘플운송", "물류대행", "배송대행",
    "창고관리", "입출고", "하역", "재고관리", "포장대행",
    "안전컨설팅", "안전관리컨설팅", "PSM", "공정안전", "안전매뉴얼",
    "산업안전", "재난안전", "소방안전", "안전진단", "안전점검", "소방점검",
    "규제기관", "규제기관장", "규제협의", "규제대응", "비상대응",
    "협력센터운영", "협력센터", "협의체운영", "협의체",
    "방송콘텐츠", "방송채널", "방송제작", "IPTV", "OTT", "스트리밍서비스",
    "다큐멘터리", "프로그램제작",
    "일터혁신", "노사관계", "노무관리", "상생컨설팅", "노동컨설팅",
    "인사관리", "급여관리", "채용대행",
    "회계감사", "세무대리", "법률자문",
    "경기동향조사", "통계조사", "실태조사", "모니터링조사", "사후모니터링",
    "모니터링연구", "모니터링용역", "점검용역", "감시용역",
    "기술분석", "국내외기술분석",
    "청소용역", "경비용역", "시설관리", "청소", "경비", "미화", "방범",
    "주차관리", "보안관리",
    "유지관리", "유지보수", "정비용역", "관측장비", "측정장비", "계측장비",
    "물품구매", "장비구매", "차량구매", "비품구매",
    "수출상담회", "상담회운영",
    "광고대행사선정", "홍보대행사선정", "종합광고홍보대행사선정",
    "광고홍보대행사", "대행사선정",
    "통학버스", "임차용역", "버스임차",
    "정책홍보컨설팅대행", "홍보컨설팅대행",
]

# =============================================================================
# 4개 핵심 영역 + 산업 적합성 + WKMG 수행기관
# =============================================================================
CORE_DOMAINS = {
    "1_브랜드전략": {
        "keywords": [
            "브랜딩", "브랜드개발", "브랜드전략", "브랜드컨설팅", "리브랜딩",
            "브랜드마케팅", "브랜드커뮤니케이션",
            "포지셔닝", "컨셉", "네이밍", "슬로건",
            "BI개발", "CI개발", "아이덴티티", "브랜드아키텍처",
            # ★ v8.3: AI 관련
            "AI브랜딩", "AI브랜드", "AI기반브랜드", "생성AI브랜드",
        ],
        "max_score": 65, "partial": 58.5, "marginal": 52
    },
    "2_상품화제품개발": {
        "keywords": [
            "상품화", "제품개발", "상품개발", "제품기획", "상품기획",
            "NPD", "컨셉개발", "경쟁력진단",
            "Value-Up", "밸류업", "시장기회", "신사업발굴",
            "상품기술서", "컨셉보드", "USP",
            "패키지디자인", "제품디자인", "디자인개발",
            # ★ v8.3: AI 관련
            "AI상품화", "AI제품개발", "AI기반상품",
        ],
        "max_score": 65, "partial": 58.5, "marginal": 52
    },
    "3_유통판로개척": {
        "keywords": [
            "판로개척", "판로확대", "판로지원", "판로",
            "유통채널", "유통전략", "유통지원",
            "입점전략", "입점지원", "온라인입점",
            "라이브커머스", "기획전",
            "수출지원", "수출마케팅", "해외진출지원",
            "글로벌마케팅", "글로벌브랜드", "글로벌진출",
            "바이어발굴", "바이어매칭지원",
            # ★ v8.3: AI/디지털 관련
            "AI수출", "AI유통", "AI판로", "AI커머스",
            "크로스보더", "역직구", "글로벌이커머스",
        ],
        "max_score": 60, "partial": 54, "marginal": 48
    },
    "4_마케팅커뮤니케이션": {
        "keywords": [
            "마케팅전략", "마케팅기획", "마케팅컨설팅", "통합마케팅",
            "디지털마케팅", "온라인마케팅", "콘텐츠마케팅",
            "홍보마케팅", "마케팅홍보",
            "홍보전략", "홍보기획", "홍보캠페인", "PR전략", "PR기획",
            "캠페인", "프로모션", "IMC",
            "SNS운영", "SNS콘텐츠", "SNS마케팅",
            "콘텐츠기획", "콘텐츠전략",
            "누리소통망", "소셜미디어",
            "광고기획", "광고전략",
            # ★ v8.3: AI/디지털 관련
            "AI마케팅", "AI홍보", "AI콘텐츠", "AI광고",
            "생성AI마케팅", "생성AI콘텐츠", "생성AI활용",
            "AI활용마케팅", "AI활용홍보", "AI활용콘텐츠",
            "챗봇마케팅", "AI챗봇", "데이터마케팅",
            "퍼포먼스마케팅", "그로스마케팅",
        ],
        "max_score": 65, "partial": 58.5, "marginal": 52
    }
}

# ★ v8.3: AI/디지털 전환 범용 키워드 (영역과 무관하게 제목에 포함 시 가산)
AI_BONUS_KEYWORDS = [
    "AI활용", "AI기반", "인공지능", "생성AI", "생성형AI",
    "ChatGPT", "GPT활용", "AI전환", "디지털전환", "DX",
]
AI_BONUS_SCORE = 5  # AI 키워드 포함 시 추가 가산점

INDUSTRY_SCORES = {
    "농식품": 15, "식품": 15, "농산물": 15, "화장품": 15, "뷰티": 15,
    "건강기능식품": 15, "소상공인": 15, "중소기업": 15, "소기업": 15,
    "사회적기업": 12, "소셜벤처": 12, "사회적경제": 12, "전자": 12, "생태목장": 12,
    "장애인기업": 12, "여성기업": 10, "사회적약자": 10,
    "관광공사": 10, "6차산업": 10, "공공기관": 10, "정부": 10,
    "목장": 10, "수산물": 10, "축산물": 10,
    "지역특산물": 8, "특산품": 8, "지역특산": 8, "농촌": 8, "로컬푸드": 8,
    "등산관광": 8, "생태관광": 8, "지역관광": 8,
    "협동조합": 5, "마을기업": 5, "관광": 5, "기타": 5,
    # ★ v8.3: AI/디지털전환 산업 가산
    "AI활용": 12, "인공지능": 12, "디지털전환": 10, "DX": 10,
}

MIN_BUDGET = 30000000

PENALTY_KEYWORDS = {
    # --- 단순 대행/운영 (전략 아닌 실행) ---
    "대행용역": -15, "운영용역": -15, "운영대행용역": -15,
    "운영및활성화": -12, "운영및관리": -12, "운영활성화": -12,
    "행사운영": -12, "행사대행": -12,
    "채널운영": -10, "계정운영": -10, "계정관리": -10,
    "콘텐츠제작운영": -10, "콘텐츠운영": -10,
    # --- 기존 ---
    "수출계약": -10, "바이어매칭": -10, "해외바이어": -10,
    "특허출원": -8, "특허": -8, "인증취득": -8, "KC인증": -8,
    "직접입점": -6, "입점계약": -6,
    "R&D": -4, "기술개발": -4, "연구개발": -4,
    "시설구축": -2, "설비구축": -2,
}

def _build_wkmg_agencies():
    """sites_db.json에서 WKMG 수행기관 목록 동적 생성"""
    agencies = set()
    for site in SITES_DB.get("sites", []):
        if site.get("wkmg_partner"):
            name = site["name"]
            agencies.add(name)
            for suffix in ["청", "공사", "공단", "진흥원", "재단", "센터", "원"]:
                if name.endswith(suffix) and len(name) > len(suffix) + 2:
                    agencies.add(name)
            m = re.search(r'\(([^)]+)\)', name)
            if m:
                agencies.add(m.group(1))
                agencies.add(name.split('(')[0].strip())
    
    alias_map = {
        "aT 한국농수산식품유통공사": ["한국농수산식품유통공사", "농수산식품유통공사", "aT"],
        "한국사회적기업진흥원": ["사회적기업진흥원"],
        "한국관광공사": ["관광공사"],
        "한국디자인진흥원(KIDP)": ["디자인진흥원", "KIDP"],
        "한국농업기술진흥원(KOAT)": ["농업기술진흥원", "KOAT"],
        "한국콘텐츠진흥원": ["콘텐츠진흥원", "KOCCA"],
        "소상공인시장진흥공단": ["소진공"],
        "중소기업진흥공단": ["중진공", "중소벤처기업진흥공단"],
        "화성시청": ["화성시"],
        "농촌진흥청": ["농진청"],
        "농업기술실용화재단(구 FACT)": ["FACT", "농업기술실용화재단"],
        "중소기업유통센터": ["유통센터"],
    }
    for base, aliases in alias_map.items():
        for a in aliases:
            agencies.add(a)
    
    return list(agencies)

WKMG_AGENCIES = _build_wkmg_agencies()


# =============================================================================
# 유틸리티
# =============================================================================
def make_fingerprint(title, agency=""):
    normalized = re.sub(r'\s+', '', (title + agency).lower())
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()[:16]


# =============================================================================
# 스코어링
# =============================================================================
def calculate_score(item):
    title = (item.get('title', '') or item.get('bidNtceNm', '') or '').strip()
    title_normalized = title.replace(' ', '').replace('-', '').replace('_', '')
    agency = (item.get('agency', '') or item.get('ntceInsttNm', '') or '').strip()
    
    budget_raw = item.get('budget_raw', 0) or item.get('presmptPrce', '0')
    try:
        budget = int(float(budget_raw)) if budget_raw else 0
    except:
        budget = 0
    
    result = {
        "total": 0, "grade": "D", "is_relevant": False,
        "exclusion_reason": None, "matched_domain": None,
        "matched_keywords": [], "domain_score": 0,
        "industry_score": 0, "scale_score": 0,
        "competition_score": 0, "penalty": 0, "wkmg_agency": False,
        "gpt_result": None, "gpt_adjustment": 0,
    }
    
    # ★ 마감일 경과 건 필터링
    deadline_str = (item.get('bidClseDt', '') or item.get('deadline', '') or '')[:10]
    if deadline_str:
        try:
            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d")
            if deadline_dt.date() < datetime.now().date():
                result["exclusion_reason"] = f"마감경과:{deadline_str}"
                return result
        except:
            pass
    
    for kw in EXCLUSIONS:
        if kw.replace(' ', '') in title_normalized:
            result["exclusion_reason"] = f"배제:{kw}"
            return result
    
    if 0 < budget < MIN_BUDGET:
        result["exclusion_reason"] = f"예산부적격:{budget//10000}만원"
        return result
    
    best_domain, best_score, best_kws = None, 0, []
    for domain_name, domain_data in CORE_DOMAINS.items():
        matched = [kw for kw in domain_data["keywords"] if kw in title or kw.replace(' ', '') in title_normalized]
        if matched:
            cnt = len(matched)
            score = domain_data["max_score"] if cnt >= 3 else (domain_data["partial"] if cnt == 2 else domain_data["marginal"])
            if score > best_score:
                best_score, best_domain, best_kws = score, domain_name, matched
    
    if not best_domain:
        result["exclusion_reason"] = "영역불일치"
        return result
    
    result["is_relevant"] = True
    result["matched_domain"] = best_domain
    result["matched_keywords"] = best_kws
    result["domain_score"] = best_score
    
    ind_score = 5
    for ind, sc in INDUSTRY_SCORES.items():
        if ind in title or ind in agency:
            ind_score = max(ind_score, sc)
    result["industry_score"] = ind_score
    
    if 10000000 <= budget <= 500000000:
        budget_sc = 5
    elif 5000000 <= budget < 10000000:
        budget_sc = 4
    elif budget > 500000000:
        budget_sc = 3
    else:
        budget_sc = 3
    result["scale_score"] = budget_sc + 4
    
    comp_score = 3
    for wkmg in WKMG_AGENCIES:
        if wkmg in agency:
            comp_score += 3
            result["wkmg_agency"] = True
            break
    if not result["wkmg_agency"]:
        comp_score += 1
    result["competition_score"] = comp_score + 1
    
    # ★ v8.2: 기관명 제거 후 제목 (전략성 판단용)
    title_without_agency = title
    if agency:
        title_without_agency = title.replace(agency, '').strip()
    
    penalty = 0
    # ★ v8.2: 전략키워드가 있으면 "운영용역" 계열 감점을 면제하되 -7점 적용
    #   - "마케팅"도 전략 영역으로 포함 (마케팅=전략/기획/컨설팅)
    #   - 예: "홍보마케팅 운영" → 마케팅 포함 → 면제(-7점만)
    #   - 예: "홍보 운영" → 마케팅 미포함 → 기존 페널티 유지 (부적합)
    STRATEGIC_EXEMPTION_WORDS = ["컨설팅", "전략", "기획", "진단", "분석", "수립", "마케팅"]
    has_strategic_context = any(sw in title_without_agency for sw in STRATEGIC_EXEMPTION_WORDS)
    
    OPERATION_PENALTY_KEYWORDS = ("운영용역", "운영대행용역", "운영및활성화", "운영및관리", "운영활성화")
    already_reduced = False  # 이중 경감 방지 플래그
    
    for kw, p in PENALTY_KEYWORDS.items():
        if kw in title or kw in title_normalized:
            # 전략 키워드가 있으면 운영 계열 감점을 면제하되 -7점 경감 적용
            if has_strategic_context and kw in OPERATION_PENALTY_KEYWORDS:
                penalty += -7  # 완전 면제가 아닌 경감 처리
                already_reduced = True
            else:
                penalty += p
    result["penalty"] = penalty
    
    # ★ 전략성 판단: 실행 키워드("운영","대행" 등) 존재 시 감점 처리
    #   - 전략 키워드 없이 실행만 → -15 (단순 실행)
    #   - 전략 키워드 + 실행 → -7 (경감: 검토 기회 보존)
    #   - 이미 PENALTY_KEYWORDS에서 경감 적용된 경우 → 이중 감점 방지
    STRATEGY_WORDS = ["전략", "컨설팅", "진단", "분석", "수립", "설계", "체계", "마케팅"]
    EXECUTION_WORDS = ["대행", "운영", "관리", "활성화", "위탁"]
    has_strategy = any(sw in title_without_agency for sw in STRATEGY_WORDS)
    has_execution = any(ew in title for ew in EXECUTION_WORDS)
    if has_execution and not has_strategy:
        penalty -= 15  # 전략 없는 단순 실행은 추가 감점
        result["penalty"] = penalty
    elif has_execution and has_strategy and not already_reduced:
        penalty -= 7   # 전략+실행 조합: 경감 (아깝게 놓치지 않도록)
        result["penalty"] = penalty
    
    # ★ v8.3: AI/디지털전환 키워드 가산점
    ai_bonus = 0
    for ai_kw in AI_BONUS_KEYWORDS:
        if ai_kw in title or ai_kw.replace(' ', '') in title_normalized:
            ai_bonus = AI_BONUS_SCORE
            break
    result["ai_bonus"] = ai_bonus
    
    total = result["domain_score"] + result["industry_score"] + result["scale_score"] + result["competition_score"] + penalty + ai_bonus
    result["total"] = max(0, min(100, total))
    result["grade"] = "S" if result["total"] >= 80 else ("A" if result["total"] >= 65 else ("B" if result["total"] >= 55 else "C"))
    
    return result


# =============================================================================
# GPT 2단계 평가
# =============================================================================
GPT_SYSTEM_PROMPT = """당신은 WKMG(WK Marketing Group)의 공공 입찰 적합성 평가 전문가입니다.

## WKMG 핵심 역량 (적합 분야) - '전략 컨설팅' 또는 '마케팅 기획/실행' 성격
1. 브랜드 전략: 브랜드 개발, BI/CI 개발, 네이밍, 포지셔닝 전략 컨설팅
2. 상품화/제품개발: 상품 기획 전략, 패키지 디자인 전략, 제품 컨셉 개발 컨설팅
3. 유통/판로개척: 판로 확대 전략, 유통채널 컨설팅, 입점 전략 수립, 공공판로 컨설팅
4. 마케팅 커뮤니케이션: 마케팅 전략 수립, 홍보 전략 기획, 캠페인 전략 컨설팅

## ★ 적합으로 판정해야 하는 경우 (주의!)
- "홍보마케팅 용역": 마케팅 기획+실행을 포함하므로 적합 (단순 인쇄물 제작과 다름)
- "온라인 홍보마케팅": 디지털 마케팅 전략+실행이므로 적합
- "○○컨설팅 운영 용역": 컨설팅이 핵심이고 운영은 사업 형태이므로 적합
- "판로컨설팅", "브랜드컨설팅": 명확한 컨설팅 용역이므로 적합
- 관광/문화 홍보마케팅: WKMG 핵심 역량 분야이므로 적합

## WKMG 부적합 분야 (반드시 부적합 판정)
- 건설/공사/설계: 시설 조성, 건축 공사, 감리
- 전시/연출: 박물관 전시, 기획전시 연출, 전시물 제작설치
- 센터/시설 운영: 지원센터 운영, 사업단 운영, 플랫폼 운영 (마케팅 무관)
- 대행 실무: 수출 실무 대행, 통관, 바이어 매칭 실무
- ★ 단순 인쇄물/홍보물 제작만 하는 용역 (마케팅 기획 없이 제작만)
- ★ SNS 계정 관리/운영만 하는 용역 (전략/기획 없이 게시만)

## 핵심 판단 기준
- "마케팅", "홍보마케팅", "브랜드", "컨설팅"이 제목에 포함 → 기본적으로 적합 판단
- "운영", "대행"이 있더라도 앞에 "컨설팅", "전략", "기획", "마케팅"이 있으면 → 적합
- 제목만으로 판단이 어려우면 → 적합 (검토 기회를 놓치지 않기 위해)

## 응답 형식 (JSON만)
{"result": "적합", "score": 10, "reason": "브랜드 전략 컨설팅이 핵심 과업"}
{"result": "부적합", "score": -25, "reason": "마케팅과 무관한 시설 운영 용역"}"""

def evaluate_with_gpt(title, agency, matched_domain, matched_keywords):
    if not CONFIG.get("openai_api_key"):
        return None
    user_prompt = f"""공고명: {title}
발주기관: {agency}
매칭 영역: {matched_domain}
매칭 키워드: {', '.join(matched_keywords)}

이 용역이 WKMG에 적합한지 JSON으로 판단해주세요."""
    try:
        import openai
        client = openai.OpenAI(api_key=CONFIG["openai_api_key"])
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": GPT_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
            temperature=0.1, max_tokens=200
        )
        result_text = response.choices[0].message.content.strip()
        if '{' in result_text and '}' in result_text:
            result = json.loads(result_text[result_text.find('{'):result_text.rfind('}')+1])
            return {"result": result.get("result", "부적합"), "score": result.get("score", 0), "reason": result.get("reason", "")}
    except Exception as e:
        print(f"     ⚠️ GPT 평가 오류: {e}")
    return None

def apply_gpt_evaluation(scored_items):
    if not CONFIG.get("use_gpt") or not CONFIG.get("openai_api_key"):
        print("  ⚠️ GPT 평가 비활성화")
        return scored_items
    threshold = CONFIG.get("gpt_threshold", 55)
    candidates = [x for x in scored_items if x["score"]["total"] >= threshold and x["score"]["is_relevant"]]
    if not candidates:
        return scored_items
    print(f"\n  🤖 GPT 2단계 평가 ({len(candidates)}건)")
    evaluated, filtered = 0, 0
    for item in candidates:
        s = item["score"]
        gpt_result = evaluate_with_gpt(item["title"], item["agency"], s.get("matched_domain", ""), s.get("matched_keywords", []))
        if gpt_result:
            s["gpt_result"] = gpt_result["result"]
            s["gpt_reason"] = gpt_result["reason"]
            s["gpt_adjustment"] = gpt_result["score"]
            s["total"] = max(0, min(100, s["total"] + gpt_result["score"]))
            s["grade"] = "S" if s["total"] >= 80 else ("A" if s["total"] >= 65 else ("B" if s["total"] >= 55 else "C"))
            evaluated += 1
            if gpt_result["result"] == "부적합":
                filtered += 1
                print(f"     ❌ {item['title'][:35]}...")
            else:
                print(f"     ✅ {item['title'][:35]}...")
    print(f"  📊 GPT 완료: {evaluated}건 평가, {filtered}건 부적합")
    return scored_items


# =============================================================================
# [v8.1] 직접 크롤링 + AI 파싱 (강화)
# =============================================================================
CRAWL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
}

GPT_PARSE_PROMPT = """당신은 한국 공공기관 웹사이트의 입찰/조달 공고 게시판 파서입니다.

아래 HTML 텍스트에서 입찰/용역/조달 공고 목록을 추출하세요.

## 추출 규칙
1. 게시판의 각 공고에서: 제목(title), 등록일(date), 상세링크(link)를 추출
2. 날짜는 YYYY-MM-DD 형식으로 변환
3. 최근 7일 이내 공고만 추출
4. 입찰, 용역, 조달, 공모, 제안 관련 공고만 (일반 공지사항 제외)
5. 제목이 없거나 의미없는 항목은 제외

## 응답 형식 (JSON 배열만, 다른 텍스트 없이)
[{"title": "공고 제목", "date": "2026-02-05", "link": "/board/view?id=123"}]

공고가 없으면 빈 배열: []"""

def fetch_page_html(url, timeout=15):
    """v8.1: 리다이렉트 추적 + 상세 에러 분류"""
    try:
        resp = requests.get(url, headers=CRAWL_HEADERS, timeout=timeout,
                           verify=False, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        
        # 리다이렉트 추적 정보
        final_url = resp.url
        redirected = final_url != url
        
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}", None
        
        if len(resp.content) < 30:
            return None, f"응답너무짧({len(resp.content)}B)", None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header',
                                   'meta', 'link', 'noscript', 'iframe', 'img']):
            tag.decompose()
        
        html_text = str(soup.body) if soup.body else str(soup)
        if len(html_text) > 15000:
            html_text = html_text[:15000] + "\n... (truncated)"
        
        return html_text, None, final_url
    except requests.Timeout:
        return None, "타임아웃", None
    except requests.ConnectionError as e:
        err_str = str(e)
        if 'SSL' in err_str or 'ssl' in err_str:
            return None, "SSL에러", None
        return None, "연결실패", None
    except Exception as e:
        return None, str(e)[:40], None

def parse_with_gpt(html_text, site_name, site_url):
    """GPT로 HTML에서 공고 목록 추출"""
    if not CONFIG.get("openai_api_key"):
        return []
    
    user_prompt = f"""기관: {site_name}
URL: {site_url}
오늘 날짜: {datetime.now().strftime('%Y-%m-%d')}

아래는 이 기관의 입찰공고 게시판 HTML입니다. 공고 목록을 JSON으로 추출하세요.

---
{html_text}
---"""
    
    try:
        import openai
        client = openai.OpenAI(api_key=CONFIG["openai_api_key"])
        response = client.chat.completions.create(
            model=CONFIG.get("gpt_parse_model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": GPT_PARSE_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0, max_tokens=2000
        )
        result_text = response.choices[0].message.content.strip()
        
        if '[' in result_text:
            json_str = result_text[result_text.find('['):result_text.rfind(']')+1]
            items = json.loads(json_str)
            return items if isinstance(items, list) else []
        return []
    except Exception as e:
        print(f"       ⚠️ GPT 파싱 오류 ({site_name}): {e}")
        return []

def resolve_url(base_url, relative_link):
    if not relative_link:
        return ""
    if relative_link.startswith(('http://', 'https://')):
        return relative_link
    from urllib.parse import urljoin
    return urljoin(base_url, relative_link)

def crawl_direct_sites():
    """v8.1: 직접 크롤링 (상세 진행률 + 에러 분류 리포트)"""
    if not CONFIG.get("crawl_enabled", True):
        print("  ⚠️ 직접 크롤링 비활성화")
        return []
    
    sites = [s for s in SITES_DB.get("sites", [])
             if s.get("enabled", True) and s.get("collect_method") == "WEB_CRAWL"]
    
    if CONFIG.get("crawl_priority_only"):
        sites = [s for s in sites if s.get("priority") == "중요"]
    
    if not sites:
        return []
    
    print(f"\n  🌐 직접 크롤링 시작 ({len(sites)}개 기관)")
    
    all_items = []
    success, fail, empty = 0, 0, 0
    fail_details = []  # v8.1: 실패 상세 기록
    timeout = CONFIG.get("crawl_timeout", 15)
    delay = CONFIG.get("crawl_delay", 1.0)
    
    for idx, site in enumerate(sites, 1):
        name = site["name"]
        url = site.get("url", "")
        
        if not url or url == 'None':
            continue
        
        # 진행률 표시 (5개마다)
        if idx % 5 == 0 or idx == 1 or idx == len(sites):
            print(f"     → [{idx}/{len(sites)}] {name[:15]}...")
        
        # HTML 가져오기 (v8.1: 3-tuple 반환)
        result = fetch_page_html(url, timeout=timeout)
        html, error = result[0], result[1]
        final_url = result[2] if len(result) > 2 else None
        
        if error:
            fail += 1
            fail_details.append({"name": name, "error": error, "wkmg": site.get("wkmg_partner", False)})
            if site.get("wkmg_partner"):
                print(f"     ⚠️ WKMG파트너 실패: {name} ({error})")
            continue
        
        # GPT 파싱
        parse_url = final_url or url
        parsed = parse_with_gpt(html, name, parse_url)
        
        if not parsed:
            empty += 1
            continue
        
        # 결과를 표준 형식으로 변환
        for p in parsed:
            link = resolve_url(parse_url, p.get("link", ""))
            item = {
                "bidNtceNm": p.get("title", ""),
                "ntceInsttNm": name,
                "presmptPrce": "0",
                "bidClseDt": p.get("date", ""),
                "bidNtceNo": "",
                "_source": f"직접크롤링:{name}",
                "_url": link,
                "_site_priority": site.get("priority", "일반"),
                "_wkmg_partner": site.get("wkmg_partner", False),
            }
            all_items.append(item)
        
        success += 1
        
        if delay > 0:
            time.sleep(delay)
    
    # v8.1: 크롤링 요약 리포트
    print(f"\n     ┌─ 크롤링 결과 요약 ──────────────────")
    print(f"     │ ✅ 성공: {success}개 기관")
    print(f"     │ 📭 빈결과: {empty}개 (공고 없음)")
    print(f"     │ ❌ 실패: {fail}개")
    if fail_details:
        wkmg_fails = [f for f in fail_details if f["wkmg"]]
        if wkmg_fails:
            print(f"     │    ⚠️ WKMG파트너 실패: {', '.join(f['name'] for f in wkmg_fails)}")
        # 에러 유형별 집계
        err_types = {}
        for f in fail_details:
            err_types[f["error"]] = err_types.get(f["error"], 0) + 1
        for err, cnt in sorted(err_types.items(), key=lambda x: -x[1]):
            print(f"     │    - {err}: {cnt}개")
    print(f"     │ 📋 수집 공고: {len(all_items)}건")
    print(f"     └──────────────────────────────────")
    
    return all_items


# =============================================================================
# 나라장터 API 수집
# =============================================================================
def fetch_koneps():
    items = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=CONFIG["search_days"])
    
    print("\n  📡 나라장터 API 수집...")
    page, total_count = 1, 0
    
    while page <= CONFIG["max_pages"]:
        params = {
            "numOfRows": str(CONFIG["num_of_rows"]),
            "type": "json", "inqryDiv": "1",
            "inqryBgnDt": start_date.strftime("%Y%m%d") + "0000",
            "inqryEndDt": end_date.strftime("%Y%m%d") + "2359",
            "ServiceKey": CONFIG["service_key"],
            "pageNo": str(page)
        }
        try:
            resp = requests.get(CONFIG["api_url"], params=params, timeout=30, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                body = data.get('response', {}).get('body', {})
                if page == 1:
                    total_count = body.get('totalCount', 0)
                    print(f"     → 총 {total_count:,}건")
                page_items = body.get('items', [])
                if not page_items:
                    break
                for item in page_items:
                    item['_source'] = '나라장터'
                items.extend(page_items)
                if page % 20 == 0:
                    print(f"     → {page}페이지: {len(items):,}건")
                if len(items) >= total_count:
                    break
                page += 1
            else:
                print(f"     ❌ HTTP {resp.status_code}")
                break
        except Exception as e:
            print(f"     ❌ 오류: {e}")
            break
    
    print(f"     ✅ 수집: {len(items):,}건")
    return items


# =============================================================================
# [v8.1] 통합 수집 + 중복 제거
# =============================================================================
def fetch_all_bids():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=CONFIG["search_days"])
    
    # v8.1: DB에서 동적으로 기관 수 표시
    all_sites = SITES_DB.get("sites", [])
    g2b_sites = [s for s in all_sites if s.get("collect_method") == "G2B_API" and s.get("enabled", True)]
    crawl_sites = [s for s in all_sites if s.get("collect_method") == "WEB_CRAWL" and s.get("enabled", True)]
    
    print("=" * 70)
    print(f"  RFP Radar v{VERSION} (통합 크롤링)")
    print(f"  기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"  배제 키워드: {len(EXCLUSIONS)}개 | GPT: {'ON' if CONFIG['use_gpt'] else 'OFF'}")
    print(f"  기관 DB: {len(all_sites)}개 (G2B:{len(g2b_sites)} + 크롤링:{len(crawl_sites)})")
    print("=" * 70)
    
    # 1) 나라장터 API
    g2b_items = fetch_koneps()
    
    # 2) 직접 크롤링 (v8.1: 동시 실행)
    direct_items = crawl_direct_sites()
    
    # 3) 통합
    all_items = g2b_items + direct_items
    
    # 4) fingerprint 기반 중복 제거
    seen = {}
    unique = []
    for item in all_items:
        title = item.get('bidNtceNm', '') or ''
        if not title:
            continue
        fp = make_fingerprint(title, item.get('ntceInsttNm', ''))
        if fp not in seen:
            seen[fp] = item
            unique.append(item)
    
    dup_count = len(all_items) - len(unique)
    print(f"\n  📊 통합: 나라장터 {len(g2b_items):,}건 + 직접 {len(direct_items):,}건")
    print(f"     → 중복제거 {dup_count}건 → 최종 {len(unique):,}건")
    
    return unique


# =============================================================================
# 이메일 발송 (v8.1)
# =============================================================================
def send_email_report(recommend, candidates, stats, excel_path=None, quick_win=None):
    if not CONFIG.get("sender_password"):
        print("  ⚠️ 이메일 비밀번호 미설정")
        return False
    
    today = datetime.now().strftime('%Y-%m-%d')
    weekday = ['월', '화', '수', '목', '금', '토', '일'][datetime.now().weekday()]
    
    grade_counts = stats.get('grades', {})
    s_cnt, a_cnt, b_cnt, c_cnt = grade_counts.get('S', 0), grade_counts.get('A', 0), grade_counts.get('B', 0), grade_counts.get('C', 0)
    
    qw_cnt = len(quick_win) if quick_win else 0
    total_recommend = len(recommend) + qw_cnt
    subject = f"[RFP Radar] {today} 추천 {total_recommend}건 (🏆{len(recommend)} + 💡{qw_cnt}) — S:{s_cnt} A:{a_cnt} B:{b_cnt}"
    
    # ── 프로젝트 카드 생성 (Stitch 디자인) ──
    projects_html = ""
    for i, item in enumerate(recommend[:30], 1):
        s = item["score"]
        grade, score = s["grade"], s["total"]
        
        # 등급별 뱃지 색상 (모노톤 베이스)
        badge_colors = {"S": "#0F172A", "A": "#334155", "B": "#64748B", "C": "#94A3B8"}
        badge_bg = badge_colors.get(grade, "#94A3B8")
        
        # WKMG 수행기관 뱃지
        wkmg_html = ''
        if s.get("wkmg_agency"):
            wkmg_html = '<span style="display:inline-block;margin-left:8px;padding:2px 8px;background:#F0FDF4;color:#166534;font-size:10px;font-weight:700;border-radius:4px;border:1px solid #BBF7D0;">WKMG</span>'
        
        # 출처 뱃지
        source_html_item = ''
        if "직접" in item.get("source", ""):
            source_html_item = f'<span style="display:inline-block;margin-left:6px;padding:2px 6px;background:#ECFDF5;color:#065F46;font-size:9px;font-weight:600;border-radius:3px;">{item.get("source", "")[:8]}</span>'
        
        # GPT Insight 섹션
        insight_html = ''
        if s.get("gpt_reason"):
            insight_html = f'''
            <div style="background:#F8FAFC;padding:12px 16px;border-radius:8px;margin:12px 0 16px;">
                <div style="font-size:11px;color:#64748B;line-height:1.6;">
                    <span style="font-weight:700;color:#0F172A;">Insight</span>&nbsp;&nbsp;{s.get("gpt_reason", "")[:80]}
                </div>
            </div>'''
        
        # ★ v8.3: 공고번호 표시 + CTA 버튼
        bid_no_html = ''
        if item.get("bid_no"):
            bid_no_html = f'''
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:4px;">
                    <tr>
                        <td style="width:20px;vertical-align:top;padding-top:2px;"><span style="color:#94A3B8;font-size:13px;">&#9679;</span></td>
                        <td style="font-size:12px;color:#94A3B8;font-weight:500;">공고번호: {item.get("bid_no", "")}</td>
                    </tr>
                </table>'''
        
        url_html = ''
        if item.get("url"):
            url_html = f'''
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;">
                <tr><td align="center">
                    <a href="{item.get("url", "")}" style="display:block;background:#0F172A;color:#FFFFFF;padding:12px 0;border-radius:8px;text-decoration:none;font-size:13px;font-weight:700;text-align:center;letter-spacing:-0.3px;" target="_blank">
                        공고 상세보기
                    </a>
                </td></tr>
            </table>'''
        
        # 마감일 강조 (3일 이내 빨간색)
        deadline = item.get("deadline", "")
        deadline_color = "#64748B"
        try:
            dl = datetime.strptime(deadline, '%Y-%m-%d')
            if (dl - datetime.now()).days <= 3:
                deadline_color = "#DC2626"
        except:
            pass
        
        projects_html += f'''
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
            <tr><td style="padding:24px;background:#FFFFFF;border:1px solid #F1F5F9;border-radius:12px;">
                <!-- 등급 + 번호 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td>
                            <span style="display:inline-block;padding:4px 10px;background:{badge_bg};color:white;font-size:10px;font-weight:700;border-radius:4px;letter-spacing:0.5px;">GRADE {grade}</span>
                            <span style="font-size:12px;font-weight:700;color:#0F172A;margin-left:8px;">{score:.0f} PTS</span>
                        </td>
                        <td style="text-align:right;">
                            <span style="font-size:11px;color:#CBD5E1;font-weight:500;">#{i:02d}</span>
                        </td>
                    </tr>
                </table>
                <!-- 제목 -->
                <div style="font-size:16px;font-weight:700;color:#0F172A;margin:14px 0;line-height:1.5;letter-spacing:-0.3px;">{item["title"][:60]}</div>
                <!-- 발주처 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:8px;">
                    <tr>
                        <td style="width:20px;vertical-align:top;padding-top:2px;"><span style="color:#94A3B8;font-size:13px;">&#9679;</span></td>
                        <td style="font-size:13px;color:#64748B;font-weight:500;">{item["agency"][:30]}{wkmg_html}</td>
                    </tr>
                </table>
                <!-- 예산 + 마감 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:4px;">
                    <tr>
                        <td style="width:20px;vertical-align:top;padding-top:2px;"><span style="color:#94A3B8;font-size:13px;">&#9679;</span></td>
                        <td style="font-size:13px;">
                            <span style="font-weight:700;color:#0F172A;">{item["budget"]}</span>
                            <span style="color:#E2E8F0;margin:0 8px;">|</span>
                            <span style="color:{deadline_color};">마감 {deadline[5:] if len(deadline) >= 10 else deadline}</span>
                            {source_html_item}
                        </td>
                    </tr>
                </table>
                {bid_no_html}{insight_html}{url_html}
            </td></tr>
        </table>'''
    
    if not projects_html:
        projects_html = '''
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr><td style="text-align:center;padding:40px 20px;">
                <div style="font-size:14px;color:#94A3B8;font-weight:500;">오늘은 우선 추천 공고가 없습니다</div>
            </td></tr>
        </table>'''
    
    # ★ v8.3: 저예산 Quick Win 섹션 생성
    quick_win_section = ''
    if quick_win:
        qw_cards = ''
        for i, item in enumerate(quick_win[:15], 1):
            s = item["score"]
            grade, score = s["grade"], s["total"]
            
            wkmg_html = ''
            if s.get("wkmg_agency"):
                wkmg_html = '<span style="display:inline-block;margin-left:8px;padding:2px 8px;background:#F0FDF4;color:#166534;font-size:10px;font-weight:700;border-radius:4px;border:1px solid #BBF7D0;">WKMG</span>'
            
            bid_no_qw = ''
            if item.get("bid_no"):
                bid_no_qw = f' &middot; {item.get("bid_no", "")}'
            
            deadline = item.get("deadline", "")
            deadline_color = "#64748B"
            try:
                dl = datetime.strptime(deadline, '%Y-%m-%d')
                if (dl - datetime.now()).days <= 3:
                    deadline_color = "#DC2626"
            except:
                pass
            
            url_html_qw = ''
            if item.get("url"):
                url_html_qw = f'<a href="{item.get("url", "")}" style="color:#2563EB;font-size:12px;font-weight:600;text-decoration:none;" target="_blank">상세보기 &rarr;</a>'
            
            qw_cards += f'''
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                <tr><td style="padding:16px 20px;background:#FEFCE8;border:1px solid #FEF08A;border-radius:10px;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td>
                                <span style="display:inline-block;padding:3px 8px;background:#EAB308;color:white;font-size:9px;font-weight:700;border-radius:4px;letter-spacing:0.5px;">💡 QUICK WIN</span>
                                <span style="font-size:11px;font-weight:600;color:#713F12;margin-left:6px;">{grade} &middot; {score:.0f}pts</span>
                            </td>
                            <td style="text-align:right;">{url_html_qw}</td>
                        </tr>
                    </table>
                    <div style="font-size:14px;font-weight:700;color:#1C1917;margin:10px 0 6px;line-height:1.5;letter-spacing:-0.3px;">{item["title"][:55]}</div>
                    <div style="font-size:12px;color:#78716C;">
                        {item["agency"][:25]}{wkmg_html}
                        <span style="color:#D6D3D1;margin:0 6px;">|</span>
                        <span style="font-weight:600;color:#92400E;">{item["budget"]}</span>
                        <span style="color:#D6D3D1;margin:0 6px;">|</span>
                        <span style="color:{deadline_color};">마감 {deadline[5:] if len(deadline) >= 10 else deadline}</span>
                        {bid_no_qw}
                    </div>
                </td></tr>
            </table>'''
        
        quick_win_section = f'''
    <tr><td style="padding:8px 24px 8px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #F1F5F9;padding-top:24px;">
            <tr>
                <td>
                    <div style="font-size:11px;font-weight:700;color:#92400E;text-transform:uppercase;letter-spacing:1.5px;">💡 저예산 QUICK WIN (3~5천만)</div>
                </td>
                <td style="text-align:right;">
                    <span style="font-size:10px;color:#94A3B8;font-weight:500;">{len(quick_win)}건</span>
                </td>
            </tr>
        </table>
    </td></tr>
    <tr><td style="padding:8px 24px 24px;">
        {qw_cards}
    </td></tr>'''
    
    # ── 통계 정보 ──
    g2b_count = stats.get('g2b_count', 0)
    direct_count = stats.get('direct_count', 0)
    total_analyzed = stats.get('total', 0)
    
    html = f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic','Noto Sans KR',sans-serif;background:#F1F5F9;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F1F5F9;">
<tr><td align="center" style="padding:24px 16px;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#FFFFFF;border-radius:16px;overflow:hidden;">
    
    <!-- ═══ HEADER ═══ -->
    <tr><td style="background:#0F172A;padding:40px 32px 48px;text-align:center;">
        <h1 style="margin:0;font-size:20px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">공공기관 마케팅 용역 추천</h1>
        <div style="margin-top:10px;font-size:12px;color:#64748B;letter-spacing:0.5px;">
            {today}&nbsp;&nbsp;&#183;&nbsp;&nbsp;RFP RADAR v{VERSION}
        </div>
    </td></tr>
    
    <!-- ═══ GRADE SUMMARY (오버랩 카드) ═══ -->
    <tr><td style="padding:0 24px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:-24px;background:#FFFFFF;border-radius:12px;border:1px solid #F1F5F9;box-shadow:0 4px 16px rgba(0,0,0,0.04);">
            <tr>
                <td style="text-align:center;padding:20px 0;width:25%;">
                    <div style="font-size:22px;font-weight:700;color:#0F172A;">{s_cnt}</div>
                    <div style="font-size:10px;font-weight:700;color:#94A3B8;margin-top:4px;letter-spacing:1px;">S</div>
                </td>
                <td style="text-align:center;padding:20px 0;width:25%;border-left:1px solid #F1F5F9;">
                    <div style="font-size:22px;font-weight:700;color:#0F172A;opacity:0.8;">{a_cnt}</div>
                    <div style="font-size:10px;font-weight:700;color:#94A3B8;margin-top:4px;letter-spacing:1px;">A</div>
                </td>
                <td style="text-align:center;padding:20px 0;width:25%;border-left:1px solid #F1F5F9;">
                    <div style="font-size:22px;font-weight:700;color:#0F172A;opacity:0.6;">{b_cnt}</div>
                    <div style="font-size:10px;font-weight:700;color:#94A3B8;margin-top:4px;letter-spacing:1px;">B</div>
                </td>
                <td style="text-align:center;padding:20px 0;width:25%;border-left:1px solid #F1F5F9;">
                    <div style="font-size:22px;font-weight:700;color:#0F172A;opacity:0.4;">{c_cnt}</div>
                    <div style="font-size:10px;font-weight:700;color:#94A3B8;margin-top:4px;letter-spacing:1px;">C</div>
                </td>
            </tr>
        </table>
    </td></tr>
    
    <!-- ═══ STATS BAR ═══ -->
    <tr><td style="padding:16px 24px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F8FAFC;border-radius:10px;border:1px solid #F1F5F9;">
            <tr>
                <td style="padding:14px 20px;">
                    <span style="font-size:11px;color:#64748B;font-weight:500;">총 분석&nbsp;</span>
                    <span style="font-size:11px;color:#0F172A;font-weight:700;">{total_analyzed:,}건</span>
                </td>
                <td style="padding:14px 20px;text-align:right;">
                    <span style="font-size:11px;color:#64748B;font-weight:500;">AI 추천&nbsp;</span>
                    <span style="font-size:11px;color:#2563EB;font-weight:700;">{len(recommend)}건</span>
                </td>
            </tr>
        </table>
    </td></tr>
    
    <!-- ═══ PRIORITY SECTION ═══ -->
    <tr><td style="padding:32px 24px 8px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
                <td>
                    <div style="font-size:11px;font-weight:700;color:#0F172A;text-transform:uppercase;letter-spacing:1.5px;">🏆 우선 추천 (5천만원+)</div>
                </td>
                <td style="text-align:right;">
                    <span style="font-size:10px;color:#94A3B8;font-weight:500;">{len(recommend)}건</span>
                </td>
            </tr>
        </table>
    </td></tr>
    
    <tr><td style="padding:16px 24px 16px;">
        {projects_html}
    </td></tr>
    
    <!-- ═══ QUICK WIN SECTION ═══ -->
    {quick_win_section}
    
    <!-- ═══ FOOTER ═══ -->
    <tr><td style="background:#0F172A;padding:28px 24px;text-align:center;">
        <div style="font-size:11px;color:#64748B;margin-bottom:4px;">
            나라장터 {g2b_count:,}건&nbsp;&nbsp;&#183;&nbsp;&nbsp;직접크롤링 {direct_count:,}건&nbsp;&nbsp;&#183;&nbsp;&nbsp;첨부: 후보 목록 ({len(candidates)}건)
        </div>
        <div style="font-size:10px;color:#475569;margin-top:8px;">
            본 정보는 AI 분석 모델에 의해 자동 생성된 리스트입니다.
        </div>
        <div style="font-size:10px;color:#334155;margin-top:12px;letter-spacing:0.5px;">
            WKMG&nbsp;&nbsp;&#183;&nbsp;&nbsp;{datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </td></tr>
    
</table>
</td></tr>
</table>
</body></html>'''
    
    try:
        msg = MIMEMultipart()
        recipients = CONFIG.get('recipient_emails', [])
        if not recipients:
            recipients = [CONFIG.get('recipient_email', '')]
        recipients = [r for r in recipients if r]
        
        msg['Subject'] = subject
        msg['From'] = CONFIG['sender_email']
        msg['To'] = ', '.join(recipients)
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        
        if excel_path and os.path.exists(excel_path):
            with open(excel_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(excel_path)}"')
                msg.attach(part)
        
        with smtplib.SMTP(CONFIG['smtp_server'], CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(CONFIG['sender_email'], CONFIG['sender_password'])
            server.send_message(msg)
        
        print(f"  ✅ 이메일 발송: {len(recipients)}명")
        return True
    except Exception as e:
        print(f"  ❌ 이메일 실패: {e}")
        return False


# =============================================================================
# 메인
# =============================================================================
def main():
    print("\n" + "=" * 70)
    print(f"  🚀 RFP Radar v{VERSION} — 128개 기관 통합 모니터링")
    print("=" * 70 + "\n")
    
    start_time = time.time()
    
    items = fetch_all_bids()
    if not items:
        print("❌ 데이터 없음")
        return
    
    g2b_count = sum(1 for x in items if x.get('_source') == '나라장터')
    direct_count = sum(1 for x in items if '직접' in str(x.get('_source', '')))
    
    print(f"\n  🎯 스코어링...")
    scored = []
    stats = {
        "total": len(items), "excluded": 0, "matched": 0,
        "grades": {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
        "g2b_count": g2b_count, "direct_count": direct_count,
    }
    
    for i, item in enumerate(items):
        if (i + 1) % 1000 == 0:
            print(f"  ⏳ {i+1:,}/{len(items):,}")
        
        score = calculate_score(item)
        
        budget_raw = item.get('presmptPrce', '0')
        try:
            budget = int(float(budget_raw)) if budget_raw else 0
            budget_str = f"{budget // 10000:,}만원" if budget > 0 else "미정"
        except:
            budget_str = "미정"
        
        bid_no = item.get('bidNtceNo', '')
        bid_seq = item.get('bidNtceOrd', '00')  # v8.2: 차수 정보
        if bid_no:
            # ★ v8.3: 차세대 나라장터 공고 상세 URL
            url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={bid_no}&bidPbancOrd={bid_seq}"
        else:
            url = item.get('_url', '')
        
        scored.append({
            "title": item.get('bidNtceNm', ''),
            "agency": item.get('ntceInsttNm', ''),
            "budget": budget_str,
            "deadline": (item.get('bidClseDt', '') or '')[:10],
            "bid_no": bid_no,
            "source": item.get('_source', ''),
            "url": url,
            "score": score
        })
        
        stats["grades"][score["grade"]] += 1
        if score["exclusion_reason"]:
            stats["excluded"] += 1
        if score["matched_domain"]:
            stats["matched"] += 1
    
    if CONFIG.get("use_gpt"):
        scored = apply_gpt_evaluation(scored)
        stats["grades"] = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for item in scored:
            stats["grades"][item["score"]["grade"]] += 1
    
    print(f"\n  📊 결과: 총 {stats['total']:,}건, 매칭 {stats['matched']:,}건")
    for g in ["S", "A", "B", "C"]:
        print(f"    {g}: {stats['grades'].get(g, 0)}건")
    
    # ★ 마감일 경과 건 이중 필터 (안전장치)
    today_str = datetime.now().strftime("%Y-%m-%d")
    def is_not_expired(x):
        dl = x.get("deadline", "")
        if not dl:
            return True  # 마감일 정보 없으면 포함
        return dl >= today_str
    
    # ★ v8.3: 우선추천(5천만+) / 저예산 Quick Win(3~5천만) 분류
    all_recommend = sorted([x for x in scored if x["score"]["grade"] in ["S", "A", "B"] and is_not_expired(x)], key=lambda x: -x["score"]["total"])
    candidates = sorted([x for x in scored if x["score"]["grade"] in ["S", "A", "B", "C"] and is_not_expired(x)], key=lambda x: -x["score"]["total"])
    
    def get_budget_value(item):
        """budget 문자열에서 숫자 추출 (\ub9cc\uc6d0 -> \uc6d0)"""
        budget_str = item.get("budget", "")
        if "미정" in budget_str:
            return 0
        try:
            num = int(budget_str.replace(",", "").replace("만원", ""))
            return num * 10000
        except:
            return 0
    
    # 우선추천: 5천만원 이상 또는 예산미정
    recommend = [x for x in all_recommend if get_budget_value(x) >= PRIORITY_BUDGET or get_budget_value(x) == 0]
    # 저예산 Quick Win: 3천만~5천만
    quick_win = [x for x in all_recommend if 0 < get_budget_value(x) < PRIORITY_BUDGET]
    
    print(f"\n  🏆 우선추천: {len(recommend)}건 | 💡 저예산 Quick Win: {len(quick_win)}건 | 후보: {len(candidates)}건")
    
    for i, item in enumerate(recommend[:10], 1):
        s = item["score"]
        src = " 🌐" if "직접" in item.get("source", "") else ""
        print(f"  {i}. [🏆{s['grade']}/{s['total']:.0f}점] {item['title'][:40]}{src}")
    if quick_win:
        print(f"\n  💡 저예산 Quick Win:")
        for i, item in enumerate(quick_win[:5], 1):
            s = item["score"]
            print(f"  {i}. [💡{s['grade']}/{s['total']:.0f}점] {item['title'][:40]} ({item['budget']})")
    
    # recommend + quick_win 통합 (\ubc1c\uc1a1\uc6a9)
    recommend_all = recommend  # 이메일에서는 별도 섹션으로 표시
    
    # 저장
    os.makedirs(CONFIG["data_dir"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with open(os.path.join(CONFIG["data_dir"], f"v83_recommend_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump(recommend + quick_win, f, ensure_ascii=False, indent=2)
    with open(os.path.join(CONFIG["data_dir"], f"v83_candidates_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    
    excel_path = None
    try:
        import pandas as pd
        excel_data = [{
            "등급": x["score"]["grade"],
            "점수": x["score"]["total"],
            "공고명": x["title"],
            "발주처": x["agency"],
            "예산": x["budget"],
            "마감일": x["deadline"],
            "출처": x.get("source", ""),
            "URL": x.get("url", "")
        } for x in candidates]
        df = pd.DataFrame(excel_data)
        excel_path = os.path.join(CONFIG["data_dir"], f"v83_candidates_{ts}.xlsx")
        df.to_excel(excel_path, index=False, engine='openpyxl')
        print(f"\n  📊 엑셀: {excel_path}")
    except ImportError:
        print("\n  ⚠️ pandas 없음 - 엑셀 생략")
    
    if CONFIG.get("send_email"):
        print("\n  📧 이메일 발송...")
        send_email_report(recommend, candidates, stats, excel_path, quick_win=quick_win)
    
    elapsed = time.time() - start_time
    print(f"\n  ✅ v{VERSION} 완료! (소요: {elapsed:.1f}초)")
    return scored, recommend, candidates, quick_win

if __name__ == "__main__":
    main()
