"""윈드러너 키우기 - 가이드 미션 자동 루프 (이미지 컨트롤 / 조건문 기반)

5초마다 화면을 캡처해서 상태를 인식하고 아래 조건대로 행동한다.

  if   MuMu 창 최소화                  → 일시정지 (복원되면 재개)
  elif 패배 화면 ('Defeat' + 재도전)   → '재도전' 탭 (연속 패배 시 제한)
  elif 기본 화면 (채팅 아이콘 + 상단·좌우 UI 가 보이는 전투 화면)
       if   [반복] 패널               → 패널 탭 (모험 코인 즉시 수령, 뽑기 안 함)
       elif [가이드] 클리어 (초록 진행도) → 패널 탭 (보상 수령)
       elif [가이드] ○○ 소환           → 패널 탭 → 소환 화면 30회 비용 확인
                                          뽑기권이면 '30회' 탭 → 10초 대기 → 기본 화면까지 빠져나옴
                                          보석이면 (이미 뽑았음) 뽑지 않고 빠져나옴
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
import os
import subprocess
import sys
import time
from ctypes import wintypes

import cv2
import numpy as np

# ============================== 설정 ==============================
ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    "adb",
]
SERIAL = ""                  # 비워두면 게임 실행 중인 기기 자동 선택 (예: "emulator-5556")
GAME_PACKAGE = "net.lightcon.windidle"

INTERVAL_SEC = 5             # 화면 인식 주기
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
HUD_TH = 0.80            # 채팅 아이콘 (기본 화면 0.96~1.00 / 메뉴·미션창·채팅창 등 ≤0.52)
HUD_OTHER_TH = 0.65      # 이벤트·랭킹·패스·챕터 (배경 따라 0.75~1.00 / 소환 화면 등 ≤0.30)
HUD_MIN_OTHERS = 2       # 채팅 아이콘 외 UI 요소 중 최소 개수
GUIDE_LABEL_TH = 0.60    # "[가이드" 주황 글자 (패널 0.89~1.00 / 그 외 ≤0.27)
REPEAT_LABEL_TH = 0.45   # "[반복]" 하늘색 글자 (패널 0.49~1.00 / 그 외 ≤0.35)
CLEAR_GREEN_PX = 200     # 클리어 판정 ①: 진행도 "(30/30)" 초록 글자 픽셀 수 (클리어 ≈810 / 진행 중 0)
BADGE_RED_PX = 600       # 클리어 판정 ②: 패널 오른쪽 위 빨간 "+N" 표시 (클리어 1083~1636 / 진행 중 0)
BADGE_WHITE_PX = 30      #   + 그 안의 흰 글자 "+N" (클리어 60~204)
                         # ② 는 진행도 숫자가 없는 미션(예: "모험 챕터 470-12 클리어")용
SUMMON_WORD_TH = 0.75    # 문구 속 '소환' 흰 글자 (소환 0.86~1.00 / 그 외 ≤0.63)
SUMMON_WORD_VMIN = 180
SCREEN_TH = 0.90         # 소환 화면 / 소환 결과 화면 구성요소
GEM_COST_TH = 0.85       # 소환 화면 30회 비용이 보석 아이콘인지 (보석 1.00 / 뽑기권 ≤0.60)
DEFEAT_TH = 0.80         # 'Defeat' 제목, '재도전' 버튼 (패배 0.94~1.00 / 그 외 ≤0.43)
CLOSE_TEXT_TH = 0.80     # '터치하여 닫기' 등 닫기 문구 (실제 0.90~1.00 / 그 외 ≤0.65)
CLOSE_TEXT_SCALES = tuple(round(0.70 + 0.05 * i, 2) for i in range(17))  # 0.70~1.50배

# 색 범위 (OpenCV HSV, H 0~180)
ORANGE = (10, 24)        # "[가이드-NNNNN]"
CYAN = (88, 104)         # "[반복]"
GREEN = (35, 85)         # 클리어 진행도 "(30/30)"

# ---- 좌표 (900x1600 기준 실측) ----
HUD = {  # 기본 화면 UI 요소: 이름 → 탐색 영역 (x1, y1, x2, y2)
    "hud_chat": (0, 1267, 91, 1358),
    "hud_event": (781, 255, 893, 331),
    "hud_ranking": (771, 345, 900, 421),
    "hud_pass": (19, 358, 117, 430),
    "hud_chapter": (301, 109, 385, 193),
}
LABEL_ROI = (330, 1150, 520, 1200)     # 패널 라벨 "[가이드"/"[반복]" 탐색 영역
PROGRESS_ROI = (340, 1200, 660, 1245)  # 패널 진행도 글자 줄
BADGE_ROI = (598, 1136, 670, 1176)     # 패널 오른쪽 위 "+N" 표시
SUMMON_WORD_OFF = (-7, 31, 253, 86)    # 라벨 기준 미션 문구 영역 ('소환' 글자 탐색)
PANEL_TAP_OFF = (143, 37)              # 라벨 좌상단 → 패널 탭 위치
GEM_COST_ROI = (570, 1125, 650, 1185)  # 소환 화면 30회 버튼 비용 아이콘
SUMMON_30_TAP = (687, 1130)            # 소환 화면 '30회' 버튼
RESULT_CLOSE_TAP = (450, 1487)         # 소환 결과 '터치하여 닫기' (결과 화면은 ESC 무반응)
ESC_SETTLE_SEC = 3.0                   # ESC 후 화면 전환 대기 (연속 ESC 방지)
EXIT_MAX_STEPS = 20                    # 뽑기 후 기본 화면 복귀 시도 횟수 (1.5초 간격)
UNKNOWN_FALLBACK = 5                   # 복귀 중 모르는 화면이 이만큼 연속되면 하단 중앙 한 번 탭
# =================================================================

BASE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE, "templates")
LOG_DIR = os.path.join(BASE, "logs")
sys.stdout.reconfigure(encoding="utf-8")

BASE_STATES = ("REPEAT", "GUIDE_CLEAR", "GUIDE_SUMMON", "GUIDE_PROGRESS", "BASE_NO_PANEL")


# ----------------------------- ADB -----------------------------
def find_adb():
    for c in ADB_CANDIDATES:
        if c == "adb" or os.path.exists(c):
            try:
                subprocess.run([c, "version"], capture_output=True, check=True)
                return c
            except Exception:
                pass
    raise SystemExit("adb.exe 를 찾을 수 없습니다. ADB_CANDIDATES 경로를 확인하세요.")


ADB = find_adb()


def pick_serial():
    if SERIAL:
        return SERIAL
    for port in (16384, 7555, 5555):        # MuMu 기본 포트 시도 (실패해도 무관)
        subprocess.run([ADB, "connect", f"127.0.0.1:{port}"], capture_output=True, timeout=5)
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    devs = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
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
    return devs[0]


DEV = pick_serial()


def _run_adb(args):
    return subprocess.run([ADB, "-s", DEV, *args], capture_output=True, check=True, timeout=20).stdout


class AdbError(RuntimeError):
    """MuMu 와 ADB 통신이 안 됨"""


def reconnect():
    """기기를 다시 찾아 연결"""
    global DEV
    try:
        new = pick_serial()
    except SystemExit as e:
        raise AdbError(str(e))
    if new != DEV:
        log(f"  [자동복구] ADB 기기 다시 연결: {DEV} → {new}")
        DEV = new


def restart_adb_server():
    """ADB 서버를 껐다 켜고 기기 다시 연결"""
    subprocess.run([ADB, "kill-server"], capture_output=True, timeout=20)
    time.sleep(2)
    subprocess.run([ADB, "start-server"], capture_output=True, timeout=30)
    reconnect()


def adb(*args, binary=False):
    """ADB 명령 실행. 실패하면 (연결이 끊긴 경우) 기기를 다시 찾아 연결한 뒤 한 번 더 시도."""
    try:
        return _run_adb(args)
    except subprocess.SubprocessError:
        reconnect()
        try:
            return _run_adb(args)
        except subprocess.SubprocessError as e:
            raise AdbError(f"{' '.join(args[:3])} 실패 ({DEV}): {getattr(e, 'stderr', b'') or e}")


def game_in_front():
    out = adb("shell", "dumpsys window | grep mCurrentFocus").decode("utf-8", "ignore")
    return GAME_PACKAGE in out


def launch_game():
    adb("shell", "monkey", "-p", GAME_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")


def screencap():
    img = cv2.imdecode(np.frombuffer(adb("exec-out", "screencap", "-p", binary=True), np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        raise AdbError("화면 캡처 실패 (빈 이미지)")
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


# 화면 판정 ---------------------------------------------------------
def is_base_screen(s):
    """기본(전투) 화면: 채팅 아이콘 + 이벤트/랭킹/패스/챕터 중 2개 이상"""
    hits = {k: match_in(s, roi, "hud/" + k)[0] >= (HUD_TH if k == "hud_chat" else HUD_OTHER_TH)
            for k, roi in HUD.items()}
    others = sum(v for k, v in hits.items() if k != "hud_chat")
    return hits["hud_chat"] and others >= HUD_MIN_OTHERS


def badge_pixels(s):
    """패널 오른쪽 위 빨간 '+N' 표시: (빨간 픽셀 수, 흰 글자 픽셀 수)"""
    x1, y1, x2, y2 = BADGE_ROI
    hsv = cv2.cvtColor(s[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = ((h <= 8) | (h >= 172)) & (sat > 150) & (v > 180)
    white = (v > 220) & (sat < 50)
    return int(red.sum()), int(white.sum())


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
    red, white = badge_pixels(s)
    if red >= BADGE_RED_PX and white >= BADGE_WHITE_PX:    # 챕터 클리어 등 진행도 숫자가 없는 미션
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
        gem = match_in(s, GEM_COST_ROI, "summon_cost_gem")[0] >= GEM_COST_TH
        return "SUMMON_SCREEN", {"gem_cost": gem}
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


def mumu_windows():
    found = []

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _exe_name(hwnd) in MUMU_EXE_NAMES:
            found.append(hwnd)
        return True

    _user32.EnumWindows(_EnumProc(cb), 0)
    return found


def mumu_minimized():
    """True=최소화됨, False=화면에 있음, None=창을 못 찾음"""
    wins = mumu_windows()
    if not wins:
        return None
    return all(_user32.IsIconic(h) for h in wins)


# ------------------------------ 로그 ------------------------------
def log(msg):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, f"guide_{dt.date.today():%Y%m%d}.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_shot(img, tag):
    os.makedirs(LOG_DIR, exist_ok=True)
    p = os.path.join(LOG_DIR, f"{tag}_{dt.datetime.now():%Y%m%d_%H%M%S}.png")
    cv2.imencode(".png", img)[1].tofile(p)
    return p


# ------------------------------ 동작 ------------------------------
class Bot:
    def __init__(self, dry):
        self.dry = dry
        self.cnt = {"guide": 0, "repeat": 0, "summon": 0, "retry": 0}
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

    # 입력 -----------------------------------------------------------
    def tap(self, xy, why):
        log(f"  ▶ {why} : tap {xy}" + ("  [dry-run]" if self.dry else ""))
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
        return screencap()

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

    def do_summon(self, panel_xy):
        self.tap(panel_xy, "가이드 소환 미션 → 소환 화면 이동")
        if self.dry:
            return
        time.sleep(2.5)
        state, info = read_screen(self.look())
        if state != "SUMMON_SCREEN":
            log(f"  ! 소환 화면이 아님({state}) - 다음 주기에 다시 시도")
            if state in ("SUMMON_RESULT", "CLOSE_TEXT"):
                self.exit_pending = True
                self.escape_to_base()
            return
        if info["gem_cost"]:
            # 뽑기권이 없음 = 이 미션의 30회는 이미 뽑았음 → 보석을 쓰지 않도록 누르지 않음
            log(f"  30회 비용이 보석 → 이미 뽑은 미션으로 판단, 뽑지 않음 ({NO_TICKET_COOLDOWN_SEC}초간 재진입 안 함)")
            self.summon_block_until = time.time() + NO_TICKET_COOLDOWN_SEC
            self.exit_pending = True
            self.escape_to_base()
            return
        self.tap(SUMMON_30_TAP, "30회 뽑기 (뽑기권)")
        self.cnt["summon"] += 1
        self.exit_pending = True
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
                shot = screencap()
            except Exception:
                pass
            self.heal("오류가 계속되어 내부 상태 초기화", shot)
            self.exit_pending = False
            self.summon_block_until = 0
            self.last_state = None
            self.err_fail = 0

    def check_game_front(self):
        """게임이 꺼졌거나 다른 앱이 앞에 있으면 (2번 연속 확인 후) 게임 다시 실행. 실행했으면 True"""
        if game_in_front():
            self.not_front = 0
            return False
        self.not_front += 1
        log(f"  ! 게임이 화면 맨 앞에 없음 ({self.not_front}회)")
        if self.not_front >= 2 and AUTO_RELAUNCH_GAME and not self.dry:
            self.heal("게임 다시 실행", screencap())
            launch_game()
            log(f"  게임 로딩 {RELAUNCH_WAIT_SEC}초 대기")
            time.sleep(RELAUNCH_WAIT_SEC)
            self.not_front = 0
            self.last_state = None
            return True
        return False

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

    # 한 주기 ---------------------------------------------------------
    def tick(self):
        self.tick_n += 1
        if self.tick_n % GAME_CHECK_EVERY == 0:
            if self.check_game_front():
                return
        if self.exit_pending:          # 지난번 뽑기 후 복귀를 못 끝냈으면 그것부터
            if self.escape_to_base():
                self.exit_fail = 0
            else:
                self.exit_fail += 1
                if self.exit_fail >= EXIT_FAIL_GIVEUP:
                    self.heal(f"뽑기 후 복귀가 {self.exit_fail}번 연속 실패 - 복귀 시도 중단 (멈춘 화면 처리에 맡김)",
                              self.look())
                    self.exit_pending = False
                    self.exit_fail = 0
                return
        s = self.look()
        state, info = read_screen(s)
        self.check_stuck(state, s)

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

    def run(self):
        log(f"시작 - 기기 {DEV}, {INTERVAL_SEC}초 주기" + (" (dry-run)" if self.dry else ""))
        try:
            while True:
                wait = None
                try:
                    self.tick()
                    self.on_ok()
                except (AdbError, subprocess.SubprocessError) as e:
                    wait = self.on_adb_fail(e)
                except Exception as e:
                    self.on_error(e)
                time.sleep(wait or INTERVAL_SEC)
        except KeyboardInterrupt:
            log(f"종료 - 가이드 {self.cnt['guide']} / 반복 {self.cnt['repeat']} / "
                f"30회 뽑기 {self.cnt['summon']} / 재도전 {self.cnt['retry']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="윈드러너 키우기 가이드 미션 자동 루프")
    ap.add_argument("--dry-run", action="store_true", help="판정만 출력하고 탭/ESC 하지 않음")
    Bot(ap.parse_args().dry_run).run()
