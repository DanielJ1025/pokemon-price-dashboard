# 포켓몬 매물 감시기 — 이 PC(회사 등)에 설치. PowerShell에서 실행:
#   powershell -ExecutionPolicy Bypass -File setup_pokemon_watch.ps1
# 경로 자동 인식(스크립트 위치 기준). .env는 워크스페이스 루트에 직접 만들어야 함(아래 안내).

$ErrorActionPreference = "Stop"
$here   = $PSScriptRoot                                   # ...\90_SYSTEM\automation
$script = Join-Path $here "pokemon_deal_watch.py"
$root   = $here   # .env 는 스크립트 폴더(watcher/)에
$envf   = Join-Path $root ".env"

Write-Output "== 포켓몬 감시기 설치 =="
Write-Output "스크립트: $script"

# 1) pythonw 찾기(창 안 뜨는 파이썬)
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-ChildItem "C:\Python*\pythonw.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName }
if (-not $py) { Write-Output "[!] pythonw.exe 없음 — 파이썬 설치 필요"; exit 1 }
Write-Output "python : $py"

# 2) .env 확인(텔레그램 토큰 필수)
if (-not (Test-Path $envf) -or -not (Select-String -Path $envf -Pattern "TELEGRAM_BOT_TOKEN=\S" -Quiet)) {
    Write-Output ""
    Write-Output "[!] .env 가 없거나 텔레그램 토큰이 비어있습니다: $envf"
    Write-Output "    아래 내용으로 .env 를 만든 뒤 이 스크립트를 다시 실행하세요:"
    Write-Output "    ----------------------------------------"
    Write-Output "    TELEGRAM_BOT_TOKEN=<봇 토큰>"
    Write-Output "    TELEGRAM_CHAT_ID=<chat id>"
    Write-Output "    ----------------------------------------"
    Write-Output "    (다나와는 무인증이라 다른 키는 필요 없음)"
    exit 1
}
Write-Output ".env    : OK"

# 3) 작업 스케줄러 등록(3분마다, 창 없음)
$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
           -RepetitionInterval (New-TimeSpan -Minutes 3) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "PokemonDealWatch" -Action $action -Trigger $trigger `
    -Settings $settings -Description "포켓몬 카드 정가 매물 감시 → 텔레그램(다나와, 3분마다)" -Force | Out-Null

# 4) 첫 실행 시 backfill(현재 매물 알림없이 등록 — 홍수 방지)
& $py $script "--backfill"

$info = Get-ScheduledTask -TaskName "PokemonDealWatch" | Get-ScheduledTaskInfo
Write-Output ""
Write-Output "[완료] 등록됨. 다음 실행: $($info.NextRunTime)"
Write-Output "  - 확인:  Get-ScheduledTask PokemonDealWatch"
Write-Output "  - 삭제:  Unregister-ScheduledTask PokemonDealWatch -Confirm:`$false"
