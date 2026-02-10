@echo off
chcp 65001 > nul
:: ============================================
::  RFP Radar v8.1 - 자동 스케줄 실행용
::  평일 09:00 자동 실행 (pause 없음)
:: ============================================

cd /d "%~dp0"

echo [%date% %time%] RFP Radar v8.1 시작 >> "%~dp0\data\daily_reports\scheduler.log"

python rfp_radar_v81.py >> "%~dp0\data\daily_reports\scheduler.log" 2>&1

echo [%date% %time%] RFP Radar v8.1 완료 >> "%~dp0\data\daily_reports\scheduler.log"
