# RFP Radar v8.1

공공기관 마케팅 용역 입찰 자동 모니터링 시스템

## 개요
- 나라장터 API (81개 기관) + 직접 크롤링 (47개 기관) = **128개 기관 커버**
- 4개 핵심 영역 스코어링 + GPT-4o-mini 2단계 평가
- WKMG 수행기관 24개 가산점 반영
- 평일 09:00 자동 실행 + 이메일 발송 (7명)

## 설치
1. `config.json.example` → `config.json` 복사 후 API 키 설정
2. `pip install requests beautifulsoup4 openai openpyxl pandas`
3. `python rfp_radar_v81.py` 또는 스케줄러 등록

## 스케줄러 등록
```powershell
# PowerShell 관리자 권한으로 실행
.\register_task.ps1
```

## 구조
```
rfp_radar_v81.py      # 메인 프로그램
sites_db.json         # 128개 기관 DB
config.json           # 설정 (API키, 이메일 등)
run_scheduled.bat     # 스케줄러용 실행 배치
register_task.ps1     # Windows 작업 스케줄러 등록
```

## 버전 히스토리
- v8.1: CCEI URL 수정, 크롤링 에러 핸들링 강화, 이메일 디자인 리뉴얼 (Deep Navy)
- v8.0: 128개 기관 통합 (G2B 81 + 직접크롤링 47)
- v7.0: 나라장터 API 기반 + 멀티 키워드 스코어링
