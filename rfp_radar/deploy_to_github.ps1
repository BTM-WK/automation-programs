# ============================================================
# RFP Radar v8.2 → GitHub 저장소 배포 스크립트
# GitHub Desktop에서 커밋/푸시하기 전에 실행하세요
# ============================================================

$source = "C:\Users\yso\OneDrive\Documents\RFP_Radar\release_v8"
$target = "C:\Users\yso\OneDrive\Documents\GitHub\automation-programs\rfp_radar"

Write-Host "=== RFP Radar v8.2 GitHub 배포 ===" -ForegroundColor Cyan

# rfp_radar_v82.py 복사
if (Test-Path "$source\rfp_radar_v82.py") {
    Copy-Item "$source\rfp_radar_v82.py" "$target\rfp_radar_v82.py" -Force
    Write-Host "  [OK] rfp_radar_v82.py 복사 완료" -ForegroundColor Green
} else {
    Write-Host "  [!!] rfp_radar_v82.py가 release_v8 폴더에 없습니다!" -ForegroundColor Red
    Write-Host "       Claude에서 다운로드한 파일을 먼저 release_v8에 저장하세요." -ForegroundColor Yellow
}

# sites_db.json 복사
if (Test-Path "$source\sites_db.json") {
    Copy-Item "$source\sites_db.json" "$target\sites_db.json" -Force
    Write-Host "  [OK] sites_db.json 복사 완료" -ForegroundColor Green
}

# config.json은 복사하지 않음 (민감 정보!)
Write-Host ""
Write-Host "  [!!] config.json은 GitHub에 올리지 않습니다 (API키 포함)" -ForegroundColor Yellow
Write-Host ""

# 결과 확인
Write-Host "=== 배포 파일 확인 ===" -ForegroundColor Cyan
Get-ChildItem $target -Recurse | Where-Object { !$_.PSIsContainer } | ForEach-Object {
    $rel = $_.FullName.Replace($target, "rfp_radar")
    Write-Host "  $rel ($([math]::Round($_.Length/1KB, 1)) KB)"
}

Write-Host ""
Write-Host "=== 다음 단계 ===" -ForegroundColor Green
Write-Host "  1. GitHub Desktop에서 변경사항 확인"
Write-Host "  2. Summary에 'RFP Radar v8.2 배포' 입력"
Write-Host "  3. 'Commit to main' 클릭"
Write-Host "  4. 'Push origin' 클릭"
Write-Host "  5. GitHub.com → Settings → Secrets에서 API키 등록"
Write-Host ""
Read-Host "아무 키나 눌러 종료"
