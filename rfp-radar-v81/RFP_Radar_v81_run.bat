@echo off
chcp 65001 > nul
title RFP Radar v8.1 - WKMG
echo.
echo  ============================================
echo   RFP Radar v8.1 - 128개 기관 통합 모니터링
echo   G2B: 81개 / WEB_CRAWL: 47개
echo  ============================================
echo.

cd /d "%~dp0"
python rfp_radar_v81.py

echo.
echo  [완료] 아무 키나 누르면 종료합니다...
pause > nul
