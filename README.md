# 윈드러너 키우기 - 가이드 미션 자동화 (이미지 컨트롤)

MuMu Player에서 돌아가는 「윈드러너 키우기」의 **가이드 미션 보상 수령과 소환 미션**을 자동화하는 Python 스크립트.

**이미지 컨트롤** 방식으로 동작한다. 게임 내부 데이터나 메모리는 건드리지 않는다.
ADB로 화면을 캡처한 뒤 OpenCV 템플릿 매칭과 색상 판정으로 화면 상태를 인식하고,
조건문에 따라 ADB 터치/키 입력을 보낸다.

> ⚠️ 매크로·자동화 사용은 게임 이용약관에 어긋날 수 있다. 사용에 따른 책임은 사용자에게 있다.
> 개인 학습용 예제로 공개한다.

---

## 설치 방법 (그대로 따라 하기)

코드를 몰라도 됩니다. 아래 명령어를 **복사해서 붙여넣기**만 하면 됩니다.
설치가 끝나면 **바탕화면에 `windrunner` 폴더**가 생기고, 프로그램은 그 안에 들어갑니다.

### 준비
| 항목 | 내용 |
|---|---|
| 컴퓨터 | Windows 10 또는 11 |
| 에뮬레이터 | MuMu Player (기본 경로에 설치) |
| 화면 크기 | MuMu 설정 → 화면 → 해상도 **세로(모바일) 900x1600** |

### 1단계. PowerShell 열기
키보드에서 `윈도우 키`를 누르고 `powershell`을 입력한 뒤 `Enter`를 누릅니다.
파란색(또는 검은색) 창이 뜨면 됩니다.

### 2단계. Git과 Python 설치 (처음 한 번만)
아래 두 줄을 복사해서 PowerShell 창에 붙여넣고(마우스 오른쪽 클릭) `Enter`를 누릅니다.
설치 창이 뜨면 "예"를 누르세요.
```powershell
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
```
> 설치가 끝나면 **PowerShell 창을 닫고 1단계부터 다시 엽니다.** (새로 설치한 프로그램을 인식시키기 위해)
> 이미 설치되어 있다는 메시지가 나오면 그냥 넘어가면 됩니다.

### 3단계. 프로그램 내려받기 + 필요한 부품 설치
새로 연 PowerShell 창에 아래 내용을 **통째로** 복사해서 붙여넣고 `Enter`를 누릅니다.
바탕화면 위치를 자동으로 찾아 `windrunner` 폴더를 만들고, 그 안에 프로그램을 내려받습니다.
```powershell
$dir = Join-Path ([Environment]::GetFolderPath('Desktop')) 'windrunner'
git clone https://github.com/l1539ym-cyber/windrunner-guide-auto.git $dir
cd $dir
$py = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $py -m pip install -r requirements.txt
explorer $dir
```
> 바탕화면 위치(OneDrive 바탕화면 포함)와 Python 설치 위치는 자동으로 찾습니다. 아무것도 고칠 필요가 없습니다.
마지막에 `windrunner` 폴더 창이 열리면 설치가 끝난 것입니다.

### 4단계. 실행
1. MuMu Player에서 게임을 켜고 **기본(전투) 화면**을 띄워 둡니다.
2. 바탕화면 `windrunner` 폴더에서 **`run_guide.bat`을 더블클릭**합니다.
3. 검은 창에 `시작 - 기기 ...`가 뜨면 동작 중입니다. 끄려면 그 창에서 `Ctrl + C`를 누르거나 창을 닫습니다.

> MuMu 창은 **최소화하지 마세요.** 최소화하면 자동으로 일시정지됩니다. 다른 창 뒤에 두는 것은 괜찮습니다.

### 새 버전으로 업데이트
PowerShell을 열고 아래를 붙여넣습니다.
```powershell
cd (Join-Path ([Environment]::GetFolderPath('Desktop')) 'windrunner')
git pull
```

### 잘 안 될 때
| 증상 | 해결 |
|---|---|
| `winget`을 찾을 수 없다고 나옴 | Microsoft Store에서 "앱 설치 관리자(App Installer)"를 설치한 뒤 다시 시도 |
| `git`을 찾을 수 없다고 나옴 | PowerShell 창을 닫고 새로 연 뒤 다시 시도 (그래도 안 되면 컴퓨터 재시작) |
| `식이 null` / `& $py` 관련 오류 | Python이 설치되지 않은 것. 2단계의 Python 설치 줄을 다시 실행 |
| `already exists and is not an empty directory` | 이미 설치되어 있다는 뜻. 위의 "업데이트"를 하면 됨 |
| `연결된 안드로이드 기기가 없습니다` | MuMu Player가 켜져 있는지 확인 |
| `adb.exe 를 찾을 수 없습니다` | MuMu를 기본 경로가 아닌 곳에 설치한 경우. `guide_auto.py` 위쪽 `ADB_CANDIDATES`에 경로 추가 |

### (선택) 개발자용 실행 방법
- **VS Code**: `windrunner` 폴더를 열고 실행(F5) → `가이드 미션 자동화` 선택 (판정만 볼 때는 `(dry-run)`)
- **터미널**
  ```bash
  python guide_auto.py            # 실행
  python guide_auto.py --dry-run  # 판정만 출력, 탭하지 않음
  ```

---

## 동작 방식

### 판정 순서 (5초 주기)
```
매 주기:
  if   MuMu 창이 최소화됨              → 일시정지 (복원되면 3초 후 재개)
  elif 직전 뽑기 후 아직 복귀 못 함     → 기본 화면까지 빠져나오기부터 계속
  elif [반복] 미션 패널                 → 패널 탭 = 모험 코인 즉시 수령 (뽑기 안 함)
  elif [가이드] 클리어 (분홍 테두리)    → 패널 탭 = 보상 수령
  elif [가이드] ○○ 소환 (캐릭터/소환수/탈것)
        → 패널 탭 → 소환 화면 '30회' 탭 → 10초 대기 → 기본 화면까지 빠져나오기
  elif [가이드] 진행 중 (콤보, 몬스터 처치 등) → 대기
  else 기본 화면이 아님 (채팅, 길드, 상점, 메뉴 등) → 대기 (아무것도 누르지 않음)
                                                      기본 화면으로 돌아오면 자동 재개
```

### 가이드 미션 순환 (예시)
`콤보 50회 달성` → `일반 몬스터 27마리 처치` → `콤보 달성` → `일반 몬스터 27마리 처치` → `콤보 50회 달성` → `○○ 소환(30회)` → 반복

소환 미션 직전에 해당 종류의 30회 뽑기권이 지급되므로 따로 재화를 확인하지 않는다.

### 뽑기 후 기본 화면으로 빠져나오기
| 화면 | 처리 |
|---|---|
| 소환 결과 (카드 30장) | '터치하여 닫기' 탭 (이 화면은 ESC가 먹지 않음) |
| **'신규' 획득 연출** (새 캐릭터/소환수/탈것, 노란 빛 + "신규") | 화면 어디에 있든 **'터치하여 닫기' 등 닫기 문구를 찾아** 그 위치를 탭 |
| 소환 화면 | ESC (`KEYCODE_ESCAPE`) 한 번 → 3초 대기 후 다시 확인 |
| 모르는 화면이 약 7초 이상 계속됨 | 화면을 `logs/`에 저장하고 하단 중앙(닫기 문구 기본 위치)을 한 번 탭 |
| 기본 화면 | 복귀 완료 |

닫기 문구는 `templates/close_text/` 폴더에 있는 이미지를 **전부** 사용한다.
흰 글자만 뽑아 살짝 흐리게 처리한 뒤, 0.7~1.5배 크기로 화면 전체를 탐색한다.
글자 크기와 위치가 달라도 찾을 수 있다.
"화면을 눌러 돌아가기"처럼 다른 문구가 나오는 화면이 있으면, 그 글자 부분만 잘라 이 폴더에 넣으면 된다.
```bash
python adbtool.py cap new_screen.png   # 현재 화면 캡처 → 글자 부분만 잘라 templates/close_text/ 에 저장
```

### 인식 방법
| 대상 | 방법 |
|---|---|
| 가이드 패널 위치 | `[가이드` 글자 템플릿 매칭 (진행 중/클리어 두 종류) |
| 클리어 여부 | 패널 영역의 분홍색 픽셀 비율 (클리어 약 27~50%, 진행 중 약 0%) |
| 소환 미션 여부 | 문구 속 '소환' 글자. 반투명 패널이라 흰 글자만 마스크해서 매칭 |
| `[반복]` 패널 | `[반복]` 글자 템플릿 매칭 |
| 같은 소환 미션인지 | `[가이드-NNNNN]` 번호 부분 이미지 비교 (같은 미션 ≥0.99, 한 자리만 달라도 ≤0.81) |
| 소환 화면 / 결과 | 하단 탭, '30회' 버튼, '터치하여 닫기' 템플릿 |

### 안전장치
- **같은 소환 미션에서는 30회 뽑기를 1번만 한다.** 미션 번호가 바뀌어야 다시 뽑는다.
- `[반복]` 패널은 문구가 '소환'이어도 뽑지 않는다. 탭했는데 소환 화면이 열리면 그대로 빠져나온다.
- ESC는 **소환 화면에서만** 보낸다. 전투 화면에서 ESC를 보내면 게임 종료창이 뜰 수 있기 때문이다.
  화면이 닫히는 도중에 ESC가 한 번 더 들어가지 않도록 3초 기다린다.
- 사용자가 직접 연 화면(채팅, 상점, 소환 화면 등)은 건드리지 않고 기다린다.
- **MuMu 창을 최소화하면 자동으로 일시정지한다.** 최소화 중에는 ADB 캡처에 이전 화면이 섞여 오작동할 수 있다.
  다른 창 뒤에 두거나 창을 작게 줄이는 것은 괜찮다.
- 로그: `logs/guide_YYYYMMDD.log`. 이상한 화면을 만나면 캡처도 `logs/`에 저장한다.

---

## 설정값
`guide_auto.py` 상단의 `설정` 블록에서 바꾼다.

| 이름 | 기본값 | 의미 |
|---|---|---|
| `INTERVAL_SEC` | 5 | 화면 인식 주기(초) |
| `AFTER_SUMMON_WAIT_SEC` | 10 | 30회 뽑기 후 대기(초) |
| `SERIAL` | "" | ADB 기기. 비우면 게임이 실행 중인 기기를 자동 선택 |
| `ADB_CANDIDATES` | MuMu 기본 경로 | `adb.exe` 탐색 경로 |
| `RESUME_SETTLE_SEC` | 3 | 최소화 해제 후 재개까지 대기(초) |
| `*_TH` | – | 각 판정 기준값 (주석에 실측 점수 범위 기재) |

## 파일 구성
```
guide_auto.py        메인 루프 (단독 실행)
adbtool.py           수동 도구: python adbtool.py cap shot.png / tap X Y / back
templates/           인식용 이미지 조각
  close_text/        닫기 문구 이미지 (여기 넣은 파일은 모두 닫기 문구로 인식)
run_guide.bat        더블클릭 실행
requirements.txt     opencv-python, numpy
.vscode/             VS Code 실행 구성
```

## 다른 해상도에서 쓰려면
템플릿과 좌표가 900x1600 기준이다. 다른 해상도라면 `python adbtool.py cap shot.png`로 화면을 캡처해서
`templates/`의 같은 이름 파일을 새로 잘라 넣고, `guide_auto.py`의 좌표 상수를 고친다.
