# 윈드러너 가이드 미션 자동화 - 설치/업데이트 스크립트
#
# 사용법 (PowerShell 에 한 줄 붙여넣기):
#   [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://raw.githubusercontent.com/l1539ym-cyber/windrunner-guide-auto/main/install.ps1 | iex
#
# 하는 일:
#   1) Python 3.12 확인 → 없으면 설치 (winget 이 있으면 winget, 없으면 python.org 에서 직접 내려받아 설치)
#   2) 바탕화면에 windrunner 폴더를 만들고 최신 프로그램을 ZIP 으로 내려받아 풀기 (Git 불필요)
#      이미 있으면 프로그램 파일만 새 버전으로 덮어씀 (logs 등은 유지) = 업데이트
#   3) 필요한 부품(opencv-python, numpy) 설치
#   4) windrunner 폴더 열기

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'   # 진행 표시줄 끄기 (PowerShell 5.1 에서 다운로드가 매우 느려지는 문제 방지)

$Repo       = 'l1539ym-cyber/windrunner-guide-auto'
$Branch     = 'main'
$PyVersion  = '3.12.10'
$PyUrl      = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
$Dir        = if ($env:WINDRUNNER_DIR) { $env:WINDRUNNER_DIR } else { Join-Path ([Environment]::GetFolderPath('Desktop')) 'windrunner' }

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/4] $msg" -ForegroundColor Cyan }
function Ok($msg)       { Write-Host "  OK  $msg" -ForegroundColor Green }
function Fail($msg)     { Write-Host ""; Write-Host "  설치 실패: $msg" -ForegroundColor Red; throw $msg }

function Find-Python {
    $cands = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    return $null
}

try {
    # ---------------------------------------------------------------- 1. Python
    Step 1 'Python 확인'
    $py = Find-Python
    if ($py) {
        Ok "이미 설치됨: $py"
    } else {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host '  winget 으로 Python 3.12 설치 중... (1~3분)'
            winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        }
        $py = Find-Python
        if (-not $py) {
            Write-Host '  python.org 에서 Python 설치 파일을 내려받는 중... (약 25MB)'
            $exe = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
            Invoke-WebRequest $PyUrl -OutFile $exe -UseBasicParsing
            Write-Host '  Python 설치 중... (1~3분, 창이 뜨지 않아도 기다려 주세요)'
            $p = Start-Process $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0' -Wait -PassThru
            Remove-Item $exe -ErrorAction SilentlyContinue
            if ($p.ExitCode -ne 0) { Fail "Python 설치 프로그램 오류 (코드 $($p.ExitCode))" }
            $py = Find-Python
        }
        if (-not $py) { Fail 'Python 을 설치하지 못했습니다.' }
        Ok "설치 완료: $py"
    }

    # ---------------------------------------------------------------- 2. 프로그램
    Step 2 "프로그램 내려받기 → $Dir"
    $zip = Join-Path $env:TEMP 'windrunner.zip'
    $tmp = Join-Path $env:TEMP 'windrunner_unzip'
    # 최신 커밋 번호를 먼저 알아내서 정확히 그 버전을 받음 (자동 업데이트가 버전을 비교할 때 사용)
    $sha = (Invoke-RestMethod "https://api.github.com/repos/$Repo/commits/$Branch" -Headers @{ 'User-Agent' = 'windrunner-installer' }).sha
    Invoke-WebRequest "https://github.com/$Repo/archive/$sha.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    $isUpdate = Test-Path (Join-Path $Dir 'guide_auto.py')
    New-Item -ItemType Directory -Force $Dir | Out-Null
    Copy-Item (Join-Path $src.FullName '*') $Dir -Recurse -Force
    Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
    [IO.File]::WriteAllText((Join-Path $Dir '.version'), $sha)
    if ($isUpdate) { Ok "새 버전으로 업데이트됨 ($($sha.Substring(0,7)))" } else { Ok "설치됨 ($($sha.Substring(0,7)))" }

    # ---------------------------------------------------------------- 3. 부품
    Step 3 '필요한 부품 설치 (opencv-python, numpy)'
    & $py -m pip install --disable-pip-version-check -q -r (Join-Path $Dir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail '부품 설치(pip) 실패 - 인터넷 연결을 확인하세요.' }
    & $py -c "import cv2, numpy"
    if ($LASTEXITCODE -ne 0) { Fail '부품 확인 실패' }
    Ok '완료'

    # ---------------------------------------------------------------- 4. 끝
    Step 4 '설치 완료'
    Write-Host "  바탕화면 windrunner 폴더의 run_guide.bat 을 더블클릭하면 실행됩니다." -ForegroundColor Yellow
    Write-Host "  새 버전이 나오면 프로그램이 알아서 업데이트합니다. (다시 설치할 필요 없음)" -ForegroundColor Yellow
    if (-not $env:WINDRUNNER_NO_EXPLORER) { explorer $Dir }
}
catch {
    Write-Host ""
    Write-Host "오류 내용: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '인터넷 연결을 확인하고 같은 명령을 다시 붙여넣어 보세요.' -ForegroundColor Yellow
}
