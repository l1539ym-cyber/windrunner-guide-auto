"""윈드러너 키우기 - 가이드 미션 자동 루프 (이미지 컨트롤 / 조건문 기반)

5초마다 화면을 캡처해서 상태를 인식하고 아래 조건대로 행동한다.

  if   MuMu 창 최소화                  → 일시정지 (복원되면 재개)
  elif 패배 화면 ('Defeat' + 재도전)   → '재도전' 탭 (연속 패배 시 제한)
  elif 기본 화면 (채팅 아이콘 + 상단·좌우 UI 가 보이는 전투 화면)
       if   [반복] 패널               → 패널 탭 (모험 코인 즉시 수령, 뽑기 안 함)
       elif [가이드] 클리어 (초록 진행도) → 패널 탭 (보상 수령)
       elif [가이드] ○○ 소환           → 패널 탭 → 소환 화면 30회 비용 확인
                                          뽑기권 아이콘이 확실히 보일 때만 '30회' 탭 → 10초 대기 → 기본 화면까지 빠져나옴
                                          보석이거나 비용을 판별할 수 없으면 뽑지 않고 빠져나옴
       else (진행 중 / 패널 안 보임)   → 대기
  else (채팅·길드·상점·메뉴 등 다른 화면) → 대기 (아무것도 누르지 않음, 기본 화면 복귀 시 재개)

실행:  python guide_auto.py           (Ctrl+C 로 종료)
       python guide_auto.py --dry-run (판정만 출력, 탭하지 않음)

필요: Python 3.10+, opencv-python, numpy  (pip install -r requirements.txt)
      MuMu Player 실행 중, 게임 화면 세로 900x1600
"""
import argparse
import ctypes
import datetime as dt
import glob
import os
import string
import subprocess
import sys
import time
from ctypes import wintypes

import cv2
import numpy as np

# ============================== 설정 ==============================
ADB_PATH = ""                 # adb.exe 전체 경로를 직접 지정 (비우면 아래 후보 + 자동 탐색)
ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    "adb",
]
SERIAL = ""                  # 비워두면 시작할 때 게임 실행 중인 기기 자동 선택 (예: "emulator-5556")
                             # 한 번 고른 기기는 실행 중에 절대 바꾸지 않음 (연결이 끊기면 같은 기기를 기다림)
MUMU_WINDOW_TITLE = ""       # MuMu 를 여러 개 띄울 때: 대상 MuMu 창 제목에 들어 있는 글자 (최소화 감지용)
GAME_PACKAGE = "net.lightcon.windidle"

INTERVAL_SEC = 5             # 화면 인식 주기
ACTION_INTERVAL_SEC = 3      # 방금 탭(수령 등)을 했으면 다음 확인을 더 빨리 (연속 클리어 대응)
AFTER_SUMMON_WAIT_SEC = 10   # 30회 뽑기 후 대기 (오동작 방지)
SUMMON_COOLDOWN_SEC = 15     # 뽑기 후 패널이 클리어로 바뀔 때까지 소환 미션 무시
NO_TICKET_COOLDOWN_SEC = 60  # 소환 화면 비용이 보석(=이미 뽑음)일 때 다시 들어가지 않는 시간

RETRY_ON_DEFEAT = True       # 패배 시 '재도전' 누르기
RETRY_LIMIT = 3              # RETRY_WINDOW_SEC 안에 이만큼 패배하면 더 누르지 않음 (게임이 이전 스테이지로 자동 복귀)
RETRY_WINDOW_SEC = 600

# ---- 자동 복구 (오류가 나면 스스로 해결) ----
ADB_RESTART_AFTER = 3        # ADB 연속 실패 n회 → ADB 서버 재시작
ADB_BACKOFF_AFTER = 6        # ADB 연속 실패 n회 이상 → 천천히 재시도 (MuMu 꺼짐 등)
ADB_BACKOFF_SEC = 30
GAME_CHECK_EVERY = 6         # n주기(약 30초)마다 게임이 화면 맨 앞에 있는지 확인
AUTO_RELAUNCH_GAME = True    # 게임이 꺼졌거나 다른 앱이 앞에 있으면 게임 다시 실행
RELAUNCH_WAIT_SEC = 40       # 게임 실행 후 로딩 대기
STUCK_SEC = 180              # 기본 화면이 아닌 같은 화면이 이 시간 넘게 그대로면 ESC 한 번
EXIT_FAIL_GIVEUP = 3         # 뽑기 후 복귀 실패가 n번 연속이면 복귀 시도 중단
ERROR_RESET_AFTER = 3        # 알 수 없는 오류 n회 연속 → 내부 상태 초기화

KEY_ESC = 111                # Android KEYCODE_ESCAPE (소환 화면 닫기)
MUMU_EXE_NAMES = {"mumunxdevice.exe", "mumuplayer.exe", "nemuplayer.exe"}  # MuMu 화면 창 프로세스
RESUME_SETTLE_SEC = 3        # 최소화 해제 후 화면이 정상 갱신될 때까지 대기

# ---- 판정 기준값 (괄호: 실측 점수 범위) ----
HUD_TH = 0.80            # 채팅 아이콘 흰색 모양 (말풍선·길드 방패 1.00 / 서로 다른 아이콘 ≤0.66 / 어두운 팝업·소환 화면 0.00)
HUD_OTHER_TH = 0.65      # 이벤트·랭킹·패스·챕터 (배경 따라 0.75~1.00 / 소환 화면 등 ≤0.30)
HUD_MIN_OTHERS = 2       # 채팅 아이콘 외 UI 요소 중 최소 개수
GUIDE_LABEL_TH = 0.60    # "[가이드" 주황 글자 (패널 0.89~1.00 / 그 외 ≤0.27)
REPEAT_LABEL_TH = 0.45   # "[반복]" 하늘색 글자 (패널 0.49~1.00 / 그 외 ≤0.35)
CLEAR_GREEN_PX = 200     # 클리어 판정 ①: 진행도 "(30/30)" 초록 글자 픽셀 수 (클리어 ≈810 / 진행 중 0)
BORDER_PINK_TH = 0.30    # 클리어 판정 ②: 패널 왼쪽·오른쪽·아래 테두리의 밝은 분홍 비율 합 (클리어 0.72~2.3 / 진행 중 0.00)
                         #   진행도 숫자가 없는 미션(예: "모험 챕터 476-15 클리어")용. '+N' 표시가 없을 때도 있어 테두리로 판정
BADGE_RED_PX = 600       # 클리어 판정 ③: 패널 오른쪽 위 빨간 "+N" 표시 (클리어 1083~1636 / 진행 중 0)
BADGE_WHITE_PX = 30      #   + 그 안의 흰 글자 "+N" (클리어 60~204)
SUMMON_WORD_TH = 0.75    # 문구 속 '소환' 흰 글자 (소환 0.86~1.00 / 그 외 ≤0.63)
SUMMON_WORD_VMIN = 180
SCREEN_TH = 0.90         # 소환 화면 / 소환 결과 화면 구성요소
GEM_COST_TH = 0.85       # 소환 화면 30회 비용이 보석 아이콘인지 (보석 1.00 / 뽑기권 ≤0.60)
TICKET_COST_TH = 0.85    # 소환 화면 30회 비용이 뽑기권인지 (해당 종류 0.93~1.00 / 다른 종류 뽑기권 ≤0.82 / 보석 ≤0.60 / 빈 영역 ≤0.45)
DEFEAT_TH = 0.80         # 'Defeat' 제목, '재도전' 버튼 (패배 0.94~1.00 / 그 외 ≤0.43)
CLOSE_TEXT_TH = 0.80     # '터치하여 닫기' 등 닫기 문구 (실제 0.90~1.00 / 그 외 ≤0.65)
CLOSE_TEXT_SCALES = tuple(round(0.70 + 0.05 * i, 2) for i in range(17))  # 0.70~1.50배

# 색 범위 (OpenCV HSV, H 0~180)
ORANGE = (10, 24)        # "[가이드-NNNNN]"
CYAN = (88, 104)         # "[반복]"
GREEN = (35, 85)         # 클리어 진행도 "(30/30)"

# ---- 좌표 (900x1600 기준 실측) ----
CHAT_ROI = (0, 1267, 91, 1358)         # 왼쪽 아래 채팅 아이콘 (templates/hud/chat/*.png 중 하나)
HUD = {  # 채팅 아이콘 외 기본 화면 UI 요소: 이름 → 탐색 영역 (x1, y1, x2, y2)
    "hud_event": (781, 255, 893, 331),
    "hud_ranking": (771, 345, 900, 421),
    "hud_pass": (19, 358, 117, 430),
    "hud_chapter": (301, 109, 385, 193),
}
LABEL_ROI = (330, 1150, 520, 1200)     # 패널 라벨 "[가이드"/"[반복]" 탐색 영역
PROGRESS_ROI = (340, 1200, 660, 1245)  # 패널 진행도 글자 줄
BADGE_ROI = (598, 1136, 670, 1176)     # 패널 오른쪽 위 "+N" 표시
BORDER_ROIS = [(236, 1165, 250, 1235),  # 패널 왼쪽 테두리
               (652, 1170, 666, 1235),  # 패널 오른쪽 테두리
               (270, 1248, 620, 1260)]  # 패널 아래 테두리
SUMMON_WORD_OFF = (-7, 31, 253, 86)    # 라벨 기준 미션 문구 영역 ('소환' 글자 탐색)
PANEL_TAP_OFF = (143, 37)              # 라벨 좌상단 → 패널 탭 위치
GEM_COST_ROI = (570, 1125, 650, 1185)  # 소환 화면 30회 버튼 비용 아이콘
TICKET_TPLS = {                        # 30회 비용 뽑기권 아이콘 (아이콘만 자름: 배경이 섞이면 보석·빈 영역도 높게 나옴)
    "캐릭터": "summon_cost_ticket_char",   # 빨강
    "소환수": "summon_cost_ticket_pet",    # 초록
    "탈것": "summon_cost_ticket_mount",    # 금색
}
COST_MARGIN = 12                       # 비용 템플릿 탐색 여유 (픽셀)
COST_CHECKS = 3                        # 비용 판정 확인 횟수 (뽑기 전 연속으로 모두 '뽑기권'이어야 함)
SUMMON_ENTER_TIMEOUT = 12              # 패널 탭 후 소환 화면이 뜰 때까지 기다리는 최대 시간(초)
SUMMON_30_TAP = (687, 1130)            # 소환 화면 '30회' 버튼
RESULT_CLOSE_TAP = (450, 1487)         # 소환 결과 '터치하여 닫기' (결과 화면은 ESC 무반응)
ESC_SETTLE_SEC = 3.0                   # ESC 후 화면 전환 대기 (연속 ESC 방지)
EXIT_MAX_STEPS = 20                    # 뽑기 후 기본 화면 복귀 시도 횟수 (1.5초 간격)
UNKNOWN_FALLBACK = 5                   # 복귀 중 모르는 화면이 이만큼 연속되면 하단 중앙 한 번 탭
SCREEN_SIZE = (900, 1600)              # 지원 해상도 (가로, 세로). 다르면 아무것도 누르지 않고 대기
BAD_RES_WAIT_SEC = 30                  # 해상도가 다를 때 다시 확인 간격(초)
MAX_SAVED_SHOTS = 100                  # logs/ 에 남기는 화면 캡처 최대 개수 (오래된 것부터 삭제)

# ---- 자동 업데이트 ----
AUTO_UPDATE = True           # GitHub 에 새 버전이 올라오면 자동으로 받아서 다시 시작
UPDATE_CHECK_HOURS = 1       # 실행 중 새 버전 확인 주기 (시간). 시작할 때는 항상 확인
# =================================================================

# 개인 설정: 같은 폴더에 user_settings.py 를 만들어 위 값을 덮어쓸 수 있다 (자동 업데이트해도 유지됨)
#   예) user_settings.py 내용:  RETRY_ON_DEFEAT = False
#                               UPDATE_CHECK_HOURS = 2
try:
    from user_settings import *  # noqa: F401,F403
except ImportError:
    pass

import updater  # noqa: E402

EXIT_UPDATE = 3              # 새 버전 발견 시 종료 코드 → run.py 가 업데이트 후 다시 실행
EXIT_CONFIG = 4              # 설치/설정 문제 (adb.exe 없음 등) → run.py 가 천천히 다시 시도

BASE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE, "templates")
LOG_DIR = os.path.join(BASE, "logs")
sys.stdout.reconfigure(encoding="utf-8")

BASE_STATES = ("REPEAT", "GUIDE_CLEAR", "GUIDE_SUMMON", "GUIDE_PROGRESS", "BASE_NO_PANEL")


# ----------------------------- ADB -----------------------------
def fatal(msg):
    """설치·설정 문제: 바로 다시 시작해도 해결되지 않으므로 EXIT_CONFIG 로 종료 (run.py 가 천천히 재시도)"""
    print(msg, flush=True)
    raise SystemExit(EXIT_CONFIG)


def _adb_works(c):
    try:
        subprocess.run([c, "version"], capture_output=True, check=True, timeout=15)
        return True
    except Exception:
        return False


def _drives():
    return [f"{d}:\\" for d in string.ascii_uppercase[2:] if os.path.exists(f"{d}:\\")]


def _running_mumu_dirs():
    """실행 중인 MuMu 프로그램 위치 (MuMu 가 켜져 있으면 설치 위치를 정확히 알 수 있음)"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-Process | Where-Object { $_.Path -match 'mumu|nemu' } | "
                              "Select-Object -ExpandProperty Path -Unique"],
                             capture_output=True, text=True, timeout=20).stdout
        return [os.path.dirname(l.strip()) for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _registry_mumu_dirs():
    """제어판 '프로그램 제거' 목록의 MuMu 설치 위치"""
    dirs = []
    try:
        import winreg
    except ImportError:
        return dirs
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")):
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                k = winreg.OpenKey(root, winreg.EnumKey(root, i))
                name = str(winreg.QueryValueEx(k, "DisplayName")[0]).lower()
            except OSError:
                continue
            if "mumu" not in name and "nemu" not in name:
                continue
            for v in ("InstallLocation", "UninstallString", "DisplayIcon"):
                try:
                    val = str(winreg.QueryValueEx(k, v)[0]).strip()
                except OSError:
                    continue
                val = val.split('"')[1] if val.startswith('"') else val.split(",")[0]
                if val:
                    dirs.append(val if os.path.isdir(val) else os.path.dirname(val))
    return dirs


def _folder_mumu_dirs():
    """모든 드라이브에서 이름에 MuMu 가 들어간 폴더 (기본 위치가 아닌 곳에 설치한 경우)"""
    dirs = []
    for drv in _drives():
        for pat in ("MuMu*", "*/MuMu*", "*/*/MuMu*"):
            dirs.extend(d for d in glob.glob(os.path.join(drv, pat)) if os.path.isdir(d))
    return dirs


def _adb_in(d):
    """폴더 d 와 그 위 두 단계, 아래 세 단계에서 adb.exe 찾기 (MuMu 버전마다 위치가 다름)"""
    d = os.path.abspath(d)
    for up in (d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
        if len(up) <= 3:                       # 드라이브 최상위 전체를 뒤지지 않음
            continue
        for pat in ("adb.exe", "*/adb.exe", "*/*/adb.exe", "*/*/*/adb.exe"):
            yield from sorted(glob.glob(os.path.join(glob.escape(up), pat)))


def find_adb():
    tried = []
    for c in ([ADB_PATH] if ADB_PATH else []) + list(ADB_CANDIDATES):
        if c == "adb" or os.path.exists(c):
            tried.append(c)
            if _adb_works(c):
                return c
    # 기본 경로에 없으면 MuMu 설치 위치를 자동으로 찾음 (실행 중인 MuMu → 설치 정보 → 폴더 이름)
    for finder in (_running_mumu_dirs, _registry_mumu_dirs, _folder_mumu_dirs):
        for d in finder():
            for c in _adb_in(d):
                if c not in tried:
                    tried.append(c)
                    if _adb_works(c):
                        print(f"[자동탐색] adb.exe 를 찾았습니다: {c}", flush=True)
                        return c
    fatal("adb.exe 를 찾을 수 없습니다. (MuMu Player 설치 위치를 자동으로 찾지 못함)\n"
          "  1) MuMu Player 를 켠 상태로 두면 자동으로 다시 찾습니다. (1분마다 다시 시도)\n"
          "  2) 그래도 안 되면 MuMu 설치 폴더 안의 adb.exe 위치를 user_settings.py 에 적으세요.\n"
          "      ADB_PATH = r\"D:\\MuMuPlayer\\nx_main\\adb.exe\"")


def _list_devices():
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=15).stdout
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]


def _is_mumu_serial(d):
    return d.startswith("emulator-") or d.startswith("127.0.0.1:") or d.startswith("localhost:")


def _boot_id(d):
    """기기 부팅마다 바뀌는 고유값. 같은 MuMu 가 emulator-5554 와 127.0.0.1:포트 로 여러 번 잡혀도 같음.
    읽지 못하면 시리얼 그대로 (= 다른 기기로 취급, 안전한 쪽)"""
    try:
        out = subprocess.run([ADB, "-s", d, "shell", "cat /proc/sys/kernel/random/boot_id"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except subprocess.SubprocessError:
        out = ""
    return out or d


def pick_serial():
    """시작할 때 한 번만 호출: 대상 기기 결정"""
    if SERIAL:
        return SERIAL
    for port in (16384, 7555, 5555):        # MuMu 기본 포트 시도 (실패해도 무관)
        try:
            subprocess.run([ADB, "connect", f"127.0.0.1:{port}"], capture_output=True, timeout=5)
        except subprocess.SubprocessError:
            pass
    devs = _list_devices()
    if not devs:
        raise SystemExit("연결된 안드로이드 기기가 없습니다. MuMu Player 를 실행하세요.")
    # emulator-NNNN (로컬 연결)이 127.0.0.1:포트 (네트워크 연결)보다 잘 끊기지 않으므로 우선
    devs.sort(key=lambda d: 0 if d.startswith("emulator-") else 1)
    for d in devs:                           # 게임이 화면에 떠 있는 기기 우선
        try:
            focus = subprocess.run([ADB, "-s", d, "shell", "dumpsys window | grep mCurrentFocus"],
                                   capture_output=True, text=True, timeout=10).stdout
        except subprocess.SubprocessError:
            continue
        if GAME_PACKAGE in focus:
            return d
    uniq = {}                                # 같은 기기의 여러 연결은 하나로 (emulator- 가 앞이라 그쪽이 남음)
    for d in devs:
        uniq.setdefault(_boot_id(d), d)
    devs = list(uniq.values())
    mumu = [d for d in devs if _is_mumu_serial(d)]
    if len(devs) == 1 or len(mumu) == 1:     # 후보가 하나뿐일 때만 (게임은 나중에 자동 실행됨)
        return devs[0] if len(devs) == 1 else mumu[0]
    fatal("게임이 실행 중인 기기를 찾지 못했고, 연결된 기기가 여러 대입니다: " + ", ".join(devs) + "\n"
          "  엉뚱한 기기를 조작하지 않도록 멈춥니다 (1분마다 다시 확인). 게임을 켜 두거나,\n"
          "  user_settings.py 에 SERIAL = \"기기이름\" 을 적어 대상 기기를 지정하세요.")


class AdbError(RuntimeError):
    """MuMu 와 ADB 통신이 안 됨"""


ADB = DEV = None
_reconnected = False                         # 재연결이 있었음 → 다음 행동 전에 게임·화면을 다시 확인


def _run_adb(args):
    return subprocess.run([ADB, "-s", DEV, *args], capture_output=True, check=True, timeout=20).stdout


def reconnect():
    """같은 기기(DEV)에 다시 연결. 다른 기기로는 절대 바꾸지 않음 (없으면 AdbError → 나중에 다시 시도)"""
    global _reconnected
    if ":" in DEV:                           # 127.0.0.1:16384 같은 네트워크 연결은 다시 connect
        try:
            subprocess.run([ADB, "connect", DEV], capture_output=True, timeout=5)
        except subprocess.SubprocessError:
            pass
    try:
        devs = _list_devices()
    except subprocess.SubprocessError as e:
        raise AdbError(f"ADB 기기 목록 확인 실패: {e}")
    if DEV not in devs:
        raise AdbError(f"대상 기기 {DEV} 가 연결돼 있지 않음 - 다시 연결될 때까지 기다림 "
                       f"(다른 기기로 바꾸지 않음{', 현재 연결: ' + ', '.join(devs) if devs else ''})")
    _reconnected = True


def consume_reconnected():
    global _reconnected
    r, _reconnected = _reconnected, False
    return r


def restart_adb_server():
    """ADB 서버를 껐다 켜고 같은 기기에 다시 연결"""
    subprocess.run([ADB, "kill-server"], capture_output=True, timeout=20)
    time.sleep(2)
    subprocess.run([ADB, "start-server"], capture_output=True, timeout=30)
    reconnect()


def adb(*args, retry=False):
    """ADB 명령 실행.
    retry=True (화면 캡처·상태 조회처럼 두 번 실행해도 안전한 명령): 실패하면 같은 기기에 다시 연결 후 한 번 더.
    retry=False (터치·키 입력 등): 실패해도 다시 보내지 않음. 타임아웃이 났어도 이미 눌렸을 수 있으므로
    다음 주기에 화면을 새로 읽고 행동을 다시 정한다."""
    try:
        return _run_adb(args)
    except subprocess.SubprocessError as e:
        first = e
    try:
        reconnect()
    except AdbError as e:
        raise AdbError(f"{' '.join(args[:3])} 실패 ({DEV}): {e}")
    if not retry:
        raise AdbError(f"{' '.join(args[:3])} 실패 ({DEV}, 다시 보내지 않음): "
                       f"{getattr(first, 'stderr', b'') or first}")
    try:
        return _run_adb(args)
    except subprocess.SubprocessError as e:
        raise AdbError(f"{' '.join(args[:3])} 실패 ({DEV}): {getattr(e, 'stderr', b'') or e}")


def game_in_front():
    out = adb("shell", "dumpsys window | grep mCurrentFocus", retry=True).decode("utf-8", "ignore")
    return GAME_PACKAGE in out


def launch_game():
    adb("shell", "monkey", "-p", GAME_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")


class ResolutionError(RuntimeError):
    """지원하지 않는 화면 크기"""


def screencap(check_size=True):
    img = cv2.imdecode(np.frombuffer(adb("exec-out", "screencap", "-p", retry=True), np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        raise AdbError("화면 캡처 실패 (빈 이미지)")
    if check_size and (img.shape[1], img.shape[0]) != SCREEN_SIZE:
        raise ResolutionError(f"{img.shape[1]}x{img.shape[0]}")
    return img


def tap(x, y):
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def key(code):
    adb("shell", "input", "keyevent", str(code))


# --------------------------- 이미지 인식 ---------------------------
_tpl = {}


def T(name):
    if name not in _tpl:
        img = cv2.imdecode(np.fromfile(os.path.join(TPL_DIR, name + ".png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"템플릿 없음: templates/{name}.png")
        _tpl[name] = img
    return _tpl[name]


def match(img, name):
    """(점수, 좌상단 좌표)"""
    _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(img, T(name), cv2.TM_CCOEFF_NORMED))
    return score, loc


def match_in(img, roi, name):
    """영역 안에서만 매칭 → (점수, 화면 기준 좌상단 좌표)"""
    x1, y1, x2, y2 = roi
    sc, (x, y) = match(img[y1:y2, x1:x2], name)
    return sc, (x + x1, y + y1)


def _grow(roi, m):
    x1, y1, x2, y2 = roi
    return (max(0, x1 - m), max(0, y1 - m), x2 + m, y2 + m)


def summon_cost(s):
    """소환 화면 30회 버튼 비용 → ("ticket" | "gem" | "unknown", 설명)
    뽑기권은 '보석이 아님'이 아니라 캐릭터/소환수/탈것 뽑기권 아이콘 중 하나와 직접 일치할 때만 인정한다.
    (비용 영역이 가려졌거나 아이콘이 아직 안 그려진 경우 = unknown → 뽑지 않음)"""
    roi = _grow(GEM_COST_ROI, COST_MARGIN)
    gem = match_in(s, roi, "summon_cost_gem")[0]
    if gem >= GEM_COST_TH:
        return "gem", f"보석 {gem:.2f}"
    ticket, kind = max((match_in(s, roi, tpl)[0], k) for k, tpl in TICKET_TPLS.items())
    why = f"뽑기권({kind}) {ticket:.2f} / 보석 {gem:.2f}"
    return ("ticket" if ticket >= TICKET_COST_TH else "unknown"), why


def white_mask(img, vmin=200):
    """흰 글자만 남김 (반투명 패널 뒤 배경색 영향 제거)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return (((hsv[..., 2] > vmin) & (hsv[..., 1] < 60)) * 255).astype(np.uint8)


def hue_mask(img, hue, smin=120, vmin=150):
    """특정 색 글자만 남김 (배경이 바뀌어도 글자 색은 같음)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]
    return (((h >= hue[0]) & (h <= hue[1]) & (hsv[..., 1] > smin) & (hsv[..., 2] > vmin)) * 255).astype(np.uint8)


def mask_match(img, roi, tpl_name, hue):
    """색 마스크끼리 매칭 → (점수, 화면 기준 좌상단 좌표)"""
    x1, y1, x2, y2 = roi
    m = hue_mask(img[y1:y2, x1:x2], hue)
    t = hue_mask(T(tpl_name), hue)
    _, sc, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(m, t, cv2.TM_CCOEFF_NORMED))
    return sc, (x + x1, y + y1)


# 닫기 문구 ('터치하여 닫기' 등) - 화면 전체, 여러 배율 -----------------
_close_tpls = None


def _soft(mask):
    return cv2.GaussianBlur(mask, (7, 7), 0)


def close_templates():
    """templates/close_text/*.png 전부 = 닫기 문구. 배율별로 미리 만들어 둠"""
    global _close_tpls
    if _close_tpls is None:
        d = os.path.join(TPL_DIR, "close_text")
        _close_tpls = []
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            img = cv2.imdecode(np.fromfile(os.path.join(d, f), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            m = white_mask(img)
            for k in CLOSE_TEXT_SCALES:
                _close_tpls.append((f, k, _soft(cv2.resize(m, None, fx=k, fy=k))))
    return _close_tpls


def find_close_text(s):
    sw = _soft(white_mask(s))
    best = None
    for name, k, tk in close_templates():
        if tk.shape[0] >= sw.shape[0] or tk.shape[1] >= sw.shape[1]:
            continue
        _, sc, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(sw, tk, cv2.TM_CCOEFF_NORMED))
        if sc >= CLOSE_TEXT_TH and (best is None or sc > best[2]):
            best = ((x + tk.shape[1] // 2, y + tk.shape[0] // 2), name, sc)
    return best


# 채팅 아이콘 - 흰색 모양만 비교 -------------------------------------
# 마지막 채팅 채널에 따라 아이콘이 바뀌고 (일반: 말풍선 / 길드: 방패), 아이콘 뒤 원은 반투명이라
# 스테이지 배경색이 비친다. 그래서 흰색 아이콘 모양만 비교한다.
# 팝업이 떠서 화면이 어두워지면 흰색이 사라지므로 '기본 화면 아님'으로 판정된다.
_chat_tpls = None


def chat_templates():
    """templates/hud/chat/*.png 전부 = 채팅 아이콘 (흰색 마스크로 미리 만들어 둠)"""
    global _chat_tpls
    if _chat_tpls is None:
        d = os.path.join(TPL_DIR, "hud", "chat")
        _chat_tpls = []
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            img = cv2.imdecode(np.fromfile(os.path.join(d, f), np.uint8), cv2.IMREAD_COLOR)
            if img is not None and cv2.countNonZero(white_mask(img)):
                _chat_tpls.append((os.path.splitext(f)[0], white_mask(img)))
        if not _chat_tpls:
            raise SystemExit("템플릿 없음: templates/hud/chat/*.png")
    return _chat_tpls


def chat_score(s):
    """채팅 아이콘 → (점수, 가장 비슷한 아이콘 이름)"""
    x1, y1, x2, y2 = CHAT_ROI
    m = white_mask(s[y1:y2, x1:x2])
    best = (0.0, "-")
    for name, t in chat_templates():
        sc = cv2.minMaxLoc(cv2.matchTemplate(m, t, cv2.TM_CCOEFF_NORMED))[1]
        if np.isfinite(sc) and sc > best[0]:
            best = (float(sc), name)
    return best


# 화면 판정 ---------------------------------------------------------
def hud_scores(s):
    """기본 화면 판정 요소별 점수 {이름: 점수} (채팅은 'chat')"""
    sc = {"chat": chat_score(s)[0]}
    sc.update({k: match_in(s, roi, "hud/" + k)[0] for k, roi in HUD.items()})
    return sc


def hud_summary(s):
    """로그·버그 제보용: 기본 화면 판정 점수 한 줄"""
    sc, name = chat_score(s)
    parts = [f"채팅({name}) {sc:.2f}/{HUD_TH:.2f}"]
    parts += [f"{k[4:]} {match_in(s, roi, 'hud/' + k)[0]:.2f}" for k, roi in HUD.items()]
    return ", ".join(parts) + f" (나머지 기준 {HUD_OTHER_TH:.2f}, {HUD_MIN_OTHERS}개 이상)"


def is_base_screen(s):
    """기본(전투) 화면: 채팅 아이콘 + 이벤트/랭킹/패스/챕터 중 2개 이상"""
    sc = hud_scores(s)
    others = sum(v >= HUD_OTHER_TH for k, v in sc.items() if k != "chat")
    return sc["chat"] >= HUD_TH and others >= HUD_MIN_OTHERS


def badge_pixels(s):
    """패널 오른쪽 위 빨간 '+N' 표시: (빨간 픽셀 수, 흰 글자 픽셀 수)"""
    x1, y1, x2, y2 = BADGE_ROI
    hsv = cv2.cvtColor(s[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = ((h <= 8) | (h >= 172)) & (sat > 150) & (v > 180)
    white = (v > 220) & (sat < 50)
    return int(red.sum()), int(white.sum())


def border_pink(s):
    """클리어 패널의 밝은 분홍 테두리: 왼쪽·오른쪽·아래 테두리의 분홍 비율 합 (진행 중 패널은 0)"""
    total = 0.0
    for x1, y1, x2, y2 in BORDER_ROIS:
        hsv = cv2.cvtColor(s[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        total += float((((h >= 145) | (h <= 3)) & (sat > 70) & (v > 190)).mean())
    return total


def read_panel(s):
    """기본 화면 중앙 하단 미션 패널 판정"""
    g, (lx, ly) = mask_match(s, LABEL_ROI, "guide_label_orange", ORANGE)
    r, (rx, ry) = mask_match(s, LABEL_ROI, "repeat_label_cyan", CYAN)
    if g < GUIDE_LABEL_TH and r >= REPEAT_LABEL_TH:
        return "REPEAT", {"tap": (rx + PANEL_TAP_OFF[0], ry + PANEL_TAP_OFF[1])}
    if g < GUIDE_LABEL_TH:
        return "BASE_NO_PANEL", {}
    tap_xy = (lx + PANEL_TAP_OFF[0], ly + PANEL_TAP_OFF[1])
    x1, y1, x2, y2 = PROGRESS_ROI
    green = int((hue_mask(s[y1:y2, x1:x2], GREEN, 100, 150) > 0).sum())
    if green >= CLEAR_GREEN_PX:
        return "GUIDE_CLEAR", {"tap": tap_xy, "why": f"진행도 초록 {green}px"}
    border = border_pink(s)
    if border >= BORDER_PINK_TH:                           # 챕터 클리어 등 진행도 숫자가 없는 미션
        return "GUIDE_CLEAR", {"tap": tap_xy, "why": f"분홍 테두리 {border:.2f}"}
    red, white = badge_pixels(s)
    if red >= BADGE_RED_PX and white >= BADGE_WHITE_PX:
        return "GUIDE_CLEAR", {"tap": tap_xy, "why": f"+N 표시 빨강 {red}px"}
    tx1, ty1, tx2, ty2 = (lx + SUMMON_WORD_OFF[0], ly + SUMMON_WORD_OFF[1],
                          lx + SUMMON_WORD_OFF[2], ly + SUMMON_WORD_OFF[3])
    sw = cv2.minMaxLoc(cv2.matchTemplate(white_mask(s[ty1:ty2, tx1:tx2], SUMMON_WORD_VMIN),
                                         white_mask(T("guide_summon_word"), SUMMON_WORD_VMIN),
                                         cv2.TM_CCOEFF_NORMED))[1]
    if sw >= SUMMON_WORD_TH:          # 캐릭터 / 소환수 / 탈것 소환 공통
        return "GUIDE_SUMMON", {"tap": tap_xy}
    return "GUIDE_PROGRESS", {}


def read_screen(s):
    """현재 화면 상태 판별 → (state, info)"""
    # 1) 패배 (기본 화면 위에 겹쳐 뜸)
    if match(s, "defeat_title")[0] >= DEFEAT_TH:
        sc, (x, y) = match(s, "defeat_retry_btn")
        if sc >= DEFEAT_TH:
            h, w = T("defeat_retry_btn").shape[:2]
            return "DEFEAT", {"tap": (x + w // 2, y + h // 2)}
    # 2) 소환 결과 / 소환 화면
    if match(s, "summon_result_close")[0] >= SCREEN_TH:
        return "SUMMON_RESULT", {}
    if match(s, "summon_char_tab")[0] >= SCREEN_TH and match(s, "summon_30_btn")[0] >= SCREEN_TH:
        cost, why = summon_cost(s)
        return "SUMMON_SCREEN", {"cost": cost, "cost_why": why}
    # 3) 기본 화면 → 패널 판정
    if is_base_screen(s):
        return read_panel(s)
    # 4) '신규' 획득 연출 등 닫기 문구 화면 (무거운 검사라 마지막에)
    c = find_close_text(s)
    if c:
        return "CLOSE_TEXT", {"tap": c[0], "name": c[1], "score": c[2]}
    return "OTHER", {}


# ------------------------- MuMu 창 최소화 감지 -------------------------
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _exe_name(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(h)


def _window_title(hwnd):
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def mumu_windows():
    found = []

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _exe_name(hwnd) in MUMU_EXE_NAMES:
            found.append(hwnd)
        return True

    _user32.EnumWindows(_EnumProc(cb), 0)
    return found


def target_windows():
    """대상 MuMu 창 (MUMU_WINDOW_TITLE 이 있으면 제목으로 거름)"""
    wins = mumu_windows()
    if MUMU_WINDOW_TITLE:
        wins = [h for h in wins if MUMU_WINDOW_TITLE.lower() in _window_title(h).lower()]
    return wins


def mumu_minimized():
    """True=최소화됨, False=화면에 있음, None=창을 못 찾음.
    창이 여러 개이고 대상 창을 특정할 수 없으면(MUMU_WINDOW_TITLE 미설정) 하나라도 최소화돼 있을 때
    최소화로 본다 (대상 창이 최소화됐는데 모르고 조작하는 것보다 잠시 멈추는 편이 안전)."""
    wins = target_windows()
    if not wins:
        return None
    return any(_user32.IsIconic(h) for h in wins)


# ------------------------------ 로그 ------------------------------
def log(msg):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, f"guide_{dt.date.today():%Y%m%d}.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def prune_shots(keep=None):
    """logs/ 의 화면 캡처가 너무 많아지지 않게 오래된 것부터 삭제"""
    keep = MAX_SAVED_SHOTS if keep is None else keep
    shots = sorted(glob.glob(os.path.join(LOG_DIR, "*.png")), key=os.path.getmtime)
    for f in shots[:max(0, len(shots) - keep)]:
        try:
            os.remove(f)
        except OSError:
            pass


def save_shot(img, tag):
    os.makedirs(LOG_DIR, exist_ok=True)
    prune_shots(MAX_SAVED_SHOTS - 1)
    p = os.path.join(LOG_DIR, f"{tag}_{dt.datetime.now():%Y%m%d_%H%M%S}.png")
    cv2.imencode(".png", img)[1].tofile(p)
    return p


# ------------------------------ 동작 ------------------------------
class Bot:
    def __init__(self, dry):
        self.dry = dry
        self.cnt = {"guide": 0, "repeat": 0, "summon": 0, "retry": 0}
        self.acted = False
        self.last_state = None
        self.window_warned = False
        self.exit_pending = False        # 스크립트가 뽑기를 했고 아직 기본 화면으로 못 돌아옴
        self.summon_block_until = 0      # 이 시각까지 가이드 소환 미션 무시
        self.defeats = []                # 최근 패배 시각들
        self.other_since = None          # 기본 화면이 아닌 상태가 시작된 시각
        # 자동 복구용
        self.tick_n = 0
        self.adb_fail = 0                # ADB 연속 실패 횟수
        self.err_fail = 0                # 알 수 없는 오류 연속 횟수
        self.not_front = 0               # 게임이 맨 앞이 아닌 것을 연속으로 본 횟수
        self.exit_fail = 0               # 뽑기 후 복귀 연속 실패 횟수
        self.stuck_img = None            # 멈춘 화면 감지용 작은 이미지
        self.stuck_since = 0
        self.stuck_escaped = False
        self.next_update_check = time.time() + UPDATE_CHECK_HOURS * 3600   # 시작 때는 run.py 가 확인함
        self.bad_res = None              # 지원하지 않는 해상도를 본 경우 그 크기 (안내 한 번만)

    # 입력 -----------------------------------------------------------
    def tap(self, xy, why):
        log(f"  ▶ {why} : tap {xy}" + ("  [dry-run]" if self.dry else ""))
        self.acted = True
        if not self.dry:
            tap(*xy)

    def esc(self, why):
        log(f"  ▶ {why} : ESC" + ("  [dry-run]" if self.dry else ""))
        if not self.dry:
            key(KEY_ESC)

    def look(self):
        """화면 캡처. MuMu 창이 최소화돼 있으면 복원될 때까지 일시정지 후 캡처."""
        m = mumu_minimized()
        if m is None and not self.window_warned:
            log("  ! MuMu 창을 찾지 못함 - 최소화 감지 없이 진행 (MUMU_EXE_NAMES 확인)")
            self.window_warned = True
        if m:
            log("⏸ MuMu 창 최소화 감지 - 일시정지 (창을 복원하면 자동 재개)")
            while mumu_minimized():
                time.sleep(1)
            log(f"▶ MuMu 창 복원 - {RESUME_SETTLE_SEC}초 후 재개")
            time.sleep(RESUME_SETTLE_SEC)
            self.last_state = None
        s = screencap()
        if self.bad_res:
            log(f"▶ 화면 크기 정상 ({SCREEN_SIZE[0]}x{SCREEN_SIZE[1]}) - 재개")
            self.bad_res = None
        return s

    # 뽑기 -----------------------------------------------------------
    def escape_to_base(self):
        """뽑기 후 기본 화면까지 빠져나옴.
        결과창 → '터치하여 닫기' / '신규' 등 → 닫기 문구 위치 탭 / 소환 화면 → ESC.
        기본 화면에서는 ESC 를 보내지 않음 (종료창 위험)."""
        unknown = 0
        for _ in range(EXIT_MAX_STEPS):
            s = self.look()
            state, info = read_screen(s)
            if state == "SUMMON_RESULT":
                self.tap(RESULT_CLOSE_TAP, "소환 결과 닫기")
                unknown = 0
            elif state == "CLOSE_TEXT":
                self.tap(info["tap"], f"닫기 문구 탭 ('신규' 등, {info['name']} {info['score']:.2f})")
                unknown = 0
            elif state == "SUMMON_SCREEN":
                self.esc("소환 화면 빠져나오기")
                unknown = 0
                time.sleep(ESC_SETTLE_SEC)
            elif state == "OTHER":
                unknown += 1           # 전환 애니메이션일 수 있음 - 다시 확인
                if unknown == UNKNOWN_FALLBACK:
                    log("  ! 모르는 화면이 계속됨 - 화면 저장: " + save_shot(s, "unknown_after_summon"))
                    self.tap(RESULT_CLOSE_TAP, "하단 중앙 탭 (닫기 문구 기본 위치)")
                    unknown = 0
            else:                      # 기본 화면 / 패배 화면
                self.exit_pending = False
                return True
            time.sleep(1.5)
        log("  ! 기본 화면 복귀 실패 - 다음 주기에 다시 시도")
        return False

    def wait_summon_screen(self):
        """패널 탭 후 소환 화면이 뜰 때까지 반복 확인 → (state, info) 또는 시간 초과 시 (None, {})"""
        deadline = time.time() + SUMMON_ENTER_TIMEOUT
        state = None
        while True:
            time.sleep(1.0)
            state, info = read_screen(self.look())
            if state in ("SUMMON_SCREEN", "SUMMON_RESULT", "CLOSE_TEXT"):
                return state, info
            if time.time() >= deadline:
                return state, {}

    def confirm_ticket(self, info):
        """뽑기 직전 확인: 비용이 COST_CHECKS 번 연속 '뽑기권'이어야 True"""
        for i in range(COST_CHECKS):
            if i:
                time.sleep(0.5)
                state, info = read_screen(self.look())
                if state != "SUMMON_SCREEN":
                    log(f"  ! 뽑기 직전 화면이 바뀜({state}) - 뽑지 않음")
                    return False
            if info["cost"] != "ticket":
                return False
        return True

    def do_summon(self, panel_xy):
        self.tap(panel_xy, "가이드 소환 미션 → 소환 화면 이동")
        if self.dry:
            return
        self.exit_pending = True           # 지금부터 화면 전환은 봇이 시작한 것 → 반드시 기본 화면까지 복귀
        state, info = self.wait_summon_screen()
        if state != "SUMMON_SCREEN":
            log(f"  ! {SUMMON_ENTER_TIMEOUT}초 안에 소환 화면이 열리지 않음({state}) - 복귀 후 다음 주기에 다시 시도")
            self.escape_to_base()
            return
        if info["cost"] == "gem":
            # 뽑기권이 없음 = 이 미션의 30회는 이미 뽑았음 → 보석을 쓰지 않도록 누르지 않음
            log(f"  30회 비용이 보석({info['cost_why']}) → 이미 뽑은 미션으로 판단, 뽑지 않음 "
                f"({NO_TICKET_COOLDOWN_SEC}초간 재진입 안 함)")
            self.summon_block_until = time.time() + NO_TICKET_COOLDOWN_SEC
            self.escape_to_base()
            return
        if not self.confirm_ticket(info):
            log(f"  ! 30회 비용을 뽑기권으로 확인하지 못함({info['cost_why']}) - 보석 사용 방지를 위해 뽑지 않음, "
                "화면 저장: " + save_shot(self.look(), "summon_cost_unknown"))
            self.summon_block_until = time.time() + NO_TICKET_COOLDOWN_SEC
            self.escape_to_base()
            return
        self.tap(SUMMON_30_TAP, f"30회 뽑기 (뽑기권 확인: {info['cost_why']})")
        self.cnt["summon"] += 1
        self.summon_block_until = time.time() + SUMMON_COOLDOWN_SEC
        log(f"  {AFTER_SUMMON_WAIT_SEC}초 대기 (오동작 방지)")
        time.sleep(AFTER_SUMMON_WAIT_SEC)
        self.escape_to_base()

    # 패배 -----------------------------------------------------------
    def on_defeat(self, xy):
        now = time.time()
        self.defeats = [t for t in self.defeats if now - t < RETRY_WINDOW_SEC]
        if not RETRY_ON_DEFEAT:
            return
        if len(self.defeats) >= RETRY_LIMIT:
            if self.last_state != "DEFEAT_LIMIT":
                log(f"  ! {RETRY_WINDOW_SEC // 60}분 안에 {RETRY_LIMIT}번 패배 - 재도전 안 함 (게임이 이전 스테이지로 자동 복귀)")
            self.last_state = "DEFEAT_LIMIT"
            return
        self.defeats.append(now)
        self.tap(xy, f"패배 → 재도전 ({len(self.defeats)}/{RETRY_LIMIT})")
        self.cnt["retry"] += 1
        time.sleep(2)

    # 한 주기 ---------------------------------------------------------
    # 자동 복구 ---------------------------------------------------------
    def heal(self, what, shot=None):
        """복구 동작 기록 (+ 그 순간 화면 저장)"""
        msg = f"  [자동복구] {what}"
        if shot is not None:
            msg += " - 화면 저장: " + save_shot(shot, "autoheal")
        log(msg)

    def on_ok(self):
        if self.adb_fail:
            log(f"  [자동복구] ADB 연결 회복 (연속 실패 {self.adb_fail}회 후)")
        self.adb_fail = 0
        self.err_fail = 0

    def on_adb_fail(self, e):
        """ADB 오류: 재연결 → ADB 서버 재시작 → MuMu 상태 확인 + 천천히 재시도"""
        self.adb_fail += 1
        log(f"ADB 오류 {self.adb_fail}회 연속: {e}")
        if self.adb_fail == ADB_RESTART_AFTER:
            self.heal("ADB 서버 재시작")
            try:
                restart_adb_server()
            except Exception as e2:
                log(f"  ADB 서버 재시작 실패: {e2}")
        if self.adb_fail >= ADB_BACKOFF_AFTER:
            if mumu_minimized() is None:
                log(f"  ! MuMu Player 창이 보이지 않음 - MuMu 를 켜 주세요. {ADB_BACKOFF_SEC}초마다 다시 확인")
            else:
                log(f"  ! MuMu 는 켜져 있지만 연결 안 됨 - {ADB_BACKOFF_SEC}초마다 다시 시도")
            if self.adb_fail % ADB_BACKOFF_AFTER == 0:   # 가끔씩 서버 재시작도 다시 시도
                try:
                    restart_adb_server()
                except Exception:
                    pass
            return ADB_BACKOFF_SEC
        return None

    def on_error(self, e):
        """알 수 없는 오류: n회 연속이면 화면 저장 + 내부 상태 초기화"""
        self.err_fail += 1
        log(f"오류 {self.err_fail}회 연속: {e!r}")
        if self.err_fail >= ERROR_RESET_AFTER:
            shot = None
            try:
                shot = screencap(check_size=False)
            except Exception:
                pass
            self.heal("오류가 계속되어 내부 상태 초기화", shot)
            self.exit_pending = False
            self.summon_block_until = 0
            self.last_state = None
            self.err_fail = 0

    def check_game_front(self):
        """게임이 꺼졌거나 다른 앱이 앞에 있으면 (2번 연속 확인 후) 게임 다시 실행.
        게임이 맨 앞이 아니면 True (= 이번 주기에는 아무것도 누르지 않음)"""
        if game_in_front():
            self.not_front = 0
            return False
        self.not_front += 1
        log(f"  ! 게임이 화면 맨 앞에 없음 ({self.not_front}회) - 이번 주기는 누르지 않음")
        if self.not_front >= 2 and AUTO_RELAUNCH_GAME and not self.dry:
            self.heal("게임 다시 실행", screencap(check_size=False))
            launch_game()
            log(f"  게임 로딩 {RELAUNCH_WAIT_SEC}초 대기")
            time.sleep(RELAUNCH_WAIT_SEC)
            self.not_front = 0
            self.last_state = None
        return True

    def check_stuck(self, state, s):
        """기본 화면이 아닌 같은 화면이 STUCK_SEC 넘게 그대로면 ESC 한 번 (멈춘 팝업 닫기)"""
        if state != "OTHER":
            self.stuck_img, self.stuck_escaped = None, False
            return
        small = cv2.resize(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY), (45, 80)).astype(np.int16)
        if self.stuck_img is None or np.abs(small - self.stuck_img).mean() > 6:
            self.stuck_img, self.stuck_since, self.stuck_escaped = small, time.time(), False
            return
        if not self.stuck_escaped and time.time() - self.stuck_since > STUCK_SEC:
            self.heal(f"같은 화면이 {STUCK_SEC // 60}분 넘게 멈춰 있음 → ESC", s)
            self.esc("멈춘 화면 닫기")
            self.stuck_escaped = True      # 같은 화면에서는 한 번만

    def check_update(self, state):
        """UPDATE_CHECK_HOURS 마다 새 버전 확인. 있으면 기본 화면일 때(뽑기 등 동작 중이 아닐 때) 종료 코드 3 으로
        끝내서 run.py 가 업데이트 후 다시 실행하게 함"""
        if not AUTO_UPDATE or self.dry or time.time() < self.next_update_check:
            return
        if state not in BASE_STATES or self.exit_pending:
            return                    # 안전한 순간까지 미룸
        self.next_update_check = time.time() + UPDATE_CHECK_HOURS * 3600
        new = updater.update_available()
        if new:
            sha, msg, date = new
            log(f"[업데이트] 새 버전 발견 ({sha[:7]} \"{msg}\", {date[:10]}) - 업데이트 후 다시 시작합니다")
            raise SystemExit(EXIT_UPDATE)

    # 한 주기 ---------------------------------------------------------
    def tick(self):
        self.tick_n += 1
        reconnected = consume_reconnected()
        if reconnected:
            log("  [자동복구] ADB 재연결됨 - 게임과 화면을 다시 확인한 뒤 진행")
            self.last_state = None
        if reconnected or self.tick_n % GAME_CHECK_EVERY == 0:
            if self.check_game_front():
                return
        if self.exit_pending:          # 지난번 뽑기 후 복귀를 못 끝냈으면 그것부터
            if self.escape_to_base():
                self.exit_fail = 0
            else:
                self.exit_fail += 1
                if self.exit_fail >= EXIT_FAIL_GIVEUP:
                    self.heal(f"뽑기 후 복귀가 {self.exit_fail}번 연속 실패 - 복귀 시도 중단 (멈춘 화면 처리에 맡김)",
                              screencap(check_size=False))
                    self.exit_pending = False
                    self.exit_fail = 0
                return
        try:
            s = self.look()
        except ResolutionError:
            if self.check_game_front():    # 게임이 꺼져 MuMu 홈 화면(가로)이 보임 → 해상도 안내 대신 게임 다시 실행
                return
            raise
        state, info = read_screen(s)
        self.check_stuck(state, s)
        self.check_update(state)

        if state != self.last_state and not (state == "DEFEAT" and self.last_state == "DEFEAT_LIMIT"):
            waiting = state in ("OTHER", "SUMMON_SCREEN", "SUMMON_RESULT", "CLOSE_TEXT", "BASE_NO_PANEL")
            log(f"상태: {state}" + ("  → 대기" if waiting else ""))
            self.last_state = state

        # 기본 화면이 아닌 상태가 오래 계속되면 한 번 화면 저장 (버그 제보용)
        if state in ("OTHER", "CLOSE_TEXT", "BASE_NO_PANEL"):
            if self.other_since is None:
                self.other_since = time.time()
            elif time.time() - self.other_since > 120:
                log("  ! 2분 넘게 기본 화면이 아님 - 화면 저장: " + save_shot(s, "long_wait"))
                log("    기본 화면 판정 점수: " + hud_summary(s))
                self.other_since = time.time() + 10 ** 9      # 다음 기본 화면 전까지 다시 저장 안 함
        else:
            self.other_since = None

        if state == "DEFEAT":
            self.on_defeat(info["tap"])
        elif state == "REPEAT":
            # [반복] 은 '소환' 문구여도 탭만 하면 모험 코인 지급 → 절대 뽑기 하지 않음
            self.tap(info["tap"], "[반복] 미션 수령 (모험 코인)")
            self.cnt["repeat"] += 1
            if not self.dry:
                time.sleep(1.5)
                if read_screen(self.look())[0] in ("SUMMON_SCREEN", "SUMMON_RESULT"):
                    log("  ! [반복] 탭 후 소환 화면이 열림 - 뽑지 않고 복귀")
                    self.exit_pending = True
                    self.escape_to_base()
        elif state == "GUIDE_CLEAR":
            self.tap(info["tap"], f"가이드 클리어 → 보상 수령 ({info['why']})")
            self.cnt["guide"] += 1
            self.summon_block_until = 0
        elif state == "GUIDE_SUMMON":
            if time.time() < self.summon_block_until:
                return
            self.do_summon(info["tap"])
        # 그 외 (GUIDE_PROGRESS / BASE_NO_PANEL / 채팅·길드·상점 등 OTHER / 사용자가 연 소환·결과 화면)
        # → 아무것도 누르지 않고 다음 주기까지 대기

        if state in ("REPEAT", "GUIDE_CLEAR", "GUIDE_SUMMON", "DEFEAT"):
            log(f"  누적: 가이드 {self.cnt['guide']} / 반복 {self.cnt['repeat']} / "
                f"30회 뽑기 {self.cnt['summon']} / 재도전 {self.cnt['retry']}")

    def on_bad_resolution(self, size):
        """지원하지 않는 해상도: 아무것도 누르지 않고 안내만 (오류 반복·화면 저장 없이) 천천히 다시 확인"""
        if self.bad_res != size:
            log(f"  ! 화면 크기가 {size} 입니다. 이 프로그램은 {SCREEN_SIZE[0]}x{SCREEN_SIZE[1]} (세로) 에서만 동작합니다. "
                "MuMu 오른쪽 위 ⋮ → 디바이스 설정 → 화면 → 해상도 설정에서 900 x 1600 으로 바꾸세요. "
                f"바꿀 때까지 아무것도 누르지 않고 {BAD_RES_WAIT_SEC}초마다 다시 확인합니다.")
            self.bad_res = size
        self.exit_pending = False
        self.last_state = None
        return BAD_RES_WAIT_SEC

    def run(self):
        log(f"시작 - 기기 {DEV}, {INTERVAL_SEC}초 주기" + (" (dry-run)" if self.dry else ""))
        try:
            while True:
                wait = None
                self.acted = False
                try:
                    self.tick()
                    if self.acted:
                        wait = ACTION_INTERVAL_SEC
                    self.on_ok()
                except ResolutionError as e:
                    wait = self.on_bad_resolution(str(e))
                    self.on_ok()
                except (AdbError, subprocess.SubprocessError) as e:
                    wait = self.on_adb_fail(e)
                except Exception as e:
                    self.on_error(e)
                time.sleep(wait or INTERVAL_SEC)
        except KeyboardInterrupt:
            log(f"종료 - 가이드 {self.cnt['guide']} / 반복 {self.cnt['repeat']} / "
                f"30회 뽑기 {self.cnt['summon']} / 재도전 {self.cnt['retry']}")


def init_adb():
    global ADB, DEV
    ADB = find_adb()
    DEV = pick_serial()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="윈드러너 키우기 가이드 미션 자동 루프")
    ap.add_argument("--dry-run", action="store_true", help="판정만 출력하고 탭/ESC 하지 않음")
    a = ap.parse_args()
    init_adb()
    Bot(a.dry_run).run()
