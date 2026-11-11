"""윈드러너 키우기 - 가이드 미션 자동 루프 (이미지 컨트롤 / 조건문 기반)

5초마다 화면을 캡처해서 중하단 가이드 패널 상태를 인식하고 아래 조건대로 행동한다.

  if   [반복] 미션 패널이 떠 있음      → 패널 탭 (모험 코인 즉시 수령, 뽑기 안 함)
  elif 가이드 미션 클리어(분홍 테두리)  → 패널 탭 (보상 수령)
  elif 가이드 미션 = ○○ 소환(뽑기)     → 패널 탭 → 소환 화면에서 '30회' 탭
                                        → 10초 대기 → 기본 화면까지 빠져나옴
                                          (결과창/'신규' 화면: '터치하여 닫기' 글자를 찾아 탭,
                                           소환 화면: ESC)
  elif 가이드 미션 진행 중              → 대기
  else (채팅/길드/상점 등 다른 화면)     → 대기 (아무것도 누르지 않음, 기본 화면 복귀 시 재개)

실행:  python guide_auto.py           (Ctrl+C 로 종료)
       python guide_auto.py --dry-run (판정만 출력, 탭하지 않음)

필요: Python 3.10+, opencv-python, numpy  (pip install -r requirements.txt)
      MuMu Player 실행 중, 게임 화면 세로 900x1600
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
import time

import cv2
import numpy as np

# ============================== 설정 ==============================
ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    "adb",
]
SERIAL = ""                  # 비워두면 게임 실행 중인 기기 자동 선택 (예: "emulator-5556")
GAME_PACKAGE = "net.lightcon.windidle"

INTERVAL_SEC = 5             # 화면 인식 주기
AFTER_SUMMON_WAIT_SEC = 10   # 30회 뽑기 후 대기 (오동작 방지)

KEY_ESC = 111                # Android KEYCODE_ESCAPE (소환 화면 닫기)

MUMU_EXE_NAMES = {"mumunxdevice.exe", "mumuplayer.exe", "nemuplayer.exe"}  # MuMu 화면 창 프로세스
RESUME_SETTLE_SEC = 3        # 최소화 해제 후 화면이 정상 갱신될 때까지 대기

# 판정 기준값
LABEL_TH = 0.60          # "[가이드" 글자 (패널 0.69~1.0 / 다른 화면 ≤0.35)
REPEAT_TH = 0.80         # "[반복]" 글자 (패널 0.95~1.0 / 다른 화면 ≤0.43)
PINK_TH = 0.10           # 클리어 판정: 패널 분홍 픽셀 비율 (클리어≈27~50% / 진행 중≈0%)
SUMMON_WORD_TH = 0.75    # 패널 문구 속 '소환' 글자(흰 글자 마스크) (소환 0.86~1.0 / 그 외 ≤0.63)
SUMMON_WORD_VMIN = 180   # '소환' 글자 마스크 밝기 기준 (어두운 배경에서 글자가 덜 밝게 찍힘)
SCREEN_TH = 0.90         # 소환 화면 / 소환 결과 화면 구성요소
CLOSE_TEXT_TH = 0.80     # '터치하여 닫기' 등 닫기 문구 (흰 글자 마스크+흐림) (실제 0.90~1.00 / 그 외 ≤0.65)
CLOSE_TEXT_SCALES = tuple(round(0.70 + 0.05 * i, 2) for i in range(17))  # 0.70~1.50배 (화면마다 글자 크기 다름)
EXIT_MAX_STEPS = 20      # 뽑기 후 기본 화면 복귀 시도 횟수 (1.5초 간격)
UNKNOWN_FALLBACK = 5     # 복귀 중 모르는 화면이 이만큼 연속되면 하단 중앙을 한 번 탭 (닫기 문구 위치)

# 좌표 (900x1600 기준 실측)
PANEL_OFF = (-109, -19, 315, 94)       # "[가이드" 라벨 좌상단 기준 패널 영역
GEM_COLS = (10, 95)                    # 패널 안 보석 아이콘 열 (분홍이라 판정 제외)
SUMMON_WORD_OFF = (-7, 31, 253, 86)    # 라벨 기준 미션 문구 영역 ('소환' 글자 탐색)
ID_WIDTH = 150                         # 라벨 기준 "[가이드-NNNNN]" 번호 영역 너비
SAME_MISSION_TH = 0.92                 # 번호 이미지 일치도 이상이면 같은 미션 (같은 미션 ≥0.99 / 한 자리만 달라도 ≤0.81)
ESC_SETTLE_SEC = 3.0                   # ESC 후 화면 전환을 기다리는 시간 (연속 ESC 방지)
SUMMON_30_TAP = (687, 1130)            # 소환 화면 '30회' 버튼
RESULT_CLOSE_TAP = (450, 1487)         # 소환 결과 '터치하여 닫기' (결과 화면은 ESC 무반응)
# =================================================================

BASE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE, "templates")
LOG_DIR = os.path.join(BASE, "logs")
sys.stdout.reconfigure(encoding="utf-8")


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
    for d in devs:                           # 게임이 화면에 떠 있는 기기 우선
        focus = subprocess.run([ADB, "-s", d, "shell", "dumpsys window | grep mCurrentFocus"],
                               capture_output=True, text=True, timeout=10).stdout
        if GAME_PACKAGE in focus:
            return d
    return devs[0]


DEV = pick_serial()


def adb(*args, binary=False):
    r = subprocess.run([ADB, "-s", DEV, *args], capture_output=True, check=True, timeout=20)
    return r.stdout


def screencap():
    img = cv2.imdecode(np.frombuffer(adb("exec-out", "screencap", "-p", binary=True), np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("화면 캡처 실패")
    return img


def tap(x, y):
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def key(code):
    adb("shell", "input", "keyevent", str(code))


# --------------------------- 이미지 인식 ---------------------------
_tpl = {}


def T(name):
    if name not in _tpl:
        img = cv2.imread(os.path.join(TPL_DIR, name + ".png"))
        if img is None:
            raise SystemExit(f"템플릿 없음: templates/{name}.png")
        _tpl[name] = img
    return _tpl[name]


def match(img, name):
    """(점수, 좌상단 좌표)"""
    _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(img, T(name), cv2.TM_CCOEFF_NORMED))
    return score, loc


_close_tpls = None


def _soft(mask):
    """가는 글자 획을 살짝 번지게 해서 글자 크기 차이에 덜 민감하게 함"""
    return cv2.GaussianBlur(mask, (7, 7), 0)


def close_templates():
    """templates/close_text/*.png 전부 = 닫기 문구 ('터치하여 닫기', '화면을 눌러 돌아가기' 등).
    배율별로 미리 만들어 둠 → [(파일명, 배율, 템플릿)]"""
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
    """화면 전체에서 닫기 문구를 찾음 → (탭 좌표, 파일명, 점수) 또는 None"""
    sw = _soft(white_mask(s))
    best = None
    for name, k, tk in close_templates():
        if tk.shape[0] >= sw.shape[0] or tk.shape[1] >= sw.shape[1]:
            continue
        _, sc, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(sw, tk, cv2.TM_CCOEFF_NORMED))
        if sc >= CLOSE_TEXT_TH and (best is None or sc > best[2]):
            best = ((x + tk.shape[1] // 2, y + tk.shape[0] // 2), name, sc)
    return best


def read_screen(s):
    """현재 화면 상태 판별 → (state, info)"""
    # 소환 결과 / 소환 화면
    if match(s, "summon_result_close")[0] >= SCREEN_TH:
        return "SUMMON_RESULT", {}
    if match(s, "summon_char_tab")[0] >= SCREEN_TH and match(s, "summon_30_btn")[0] >= SCREEN_TH:
        return "SUMMON_SCREEN", {}

    # [반복] 패널
    rs, (rx, ry) = match(s, "repeat_label")
    if rs >= REPEAT_TH:
        return "REPEAT", {"tap": (rx + 145, ry + 37)}

    # [가이드] 패널
    a, la = match(s, "guide_label")
    b, lb = match(s, "guide_label_done")
    score, (lx, ly) = (a, la) if a >= b else (b, lb)
    if score < LABEL_TH:
        # 기본 화면이 아님 → '신규' 획득 연출 등 닫기 문구가 있는 화면인지 확인 (무거운 검사라 마지막에)
        c = find_close_text(s)
        if c:
            return "CLOSE_TEXT", {"tap": c[0], "name": c[1], "score": c[2]}
        return "UNKNOWN", {}
    x1, y1, x2, y2 = lx + PANEL_OFF[0], ly + PANEL_OFF[1], lx + PANEL_OFF[2], ly + PANEL_OFF[3]
    hsv = cv2.cvtColor(s[max(y1, 0):y2, max(x1, 0):x2], cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    pink = ((h >= 150) | (h <= 5)) & (sat > 60) & (v > 150)
    pink[:, GEM_COLS[0]:GEM_COLS[1]] = False
    ratio = float(pink.mean())
    center = ((x1 + x2) // 2 + 40, (y1 + y2) // 2)
    if ratio >= PINK_TH:
        return "GUIDE_CLEAR", {"tap": center, "pink": ratio}
    tx1, ty1, tx2, ty2 = (lx + SUMMON_WORD_OFF[0], ly + SUMMON_WORD_OFF[1],
                          lx + SUMMON_WORD_OFF[2], ly + SUMMON_WORD_OFF[3])
    st = cv2.minMaxLoc(cv2.matchTemplate(white_mask(s[ty1:ty2, tx1:tx2], SUMMON_WORD_VMIN),
                                         white_mask(T("guide_summon_word"), SUMMON_WORD_VMIN),
                                         cv2.TM_CCOEFF_NORMED))[1]
    if st >= SUMMON_WORD_TH:          # 캐릭터 / 소환수 / 탈것 소환 공통
        # "[가이드-22549]" 번호 부분 이미지 = 미션 식별용 (같은 미션 중복 뽑기 방지)
        id_img = s[ly - 3: ly + 27, lx - 5: lx + ID_WIDTH].copy()
        return "GUIDE_SUMMON", {"tap": center, "id_img": id_img}
    return "GUIDE_PROGRESS", {}


def white_mask(img, vmin=200):
    """흰 글자만 남김 (반투명 패널 뒤 배경색 영향 제거)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return (((hsv[..., 2] > vmin) & (hsv[..., 1] < 60)) * 255).astype(np.uint8)


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
    cv2.imwrite(p, img)
    return p


# ------------------------- MuMu 창 최소화 감지 -------------------------
# MuMu 를 최소화하면 ADB 캡처에 실제와 다른(이전) 화면이 섞여 오작동함 → 최소화 중엔 일시정지
import ctypes
from ctypes import wintypes

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
    """MuMu 안드로이드 화면 창 핸들 목록 (보이는 최상위 창만)"""
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


# ------------------------------ 동작 ------------------------------
class Bot:
    def __init__(self, dry):
        self.dry = dry
        self.cnt = {"guide": 0, "repeat": 0, "summon": 0}
        self.summoned_id = None    # 30회 뽑기를 이미 한 가이드 미션의 번호 이미지 (같은 미션 재뽑기 방지)
        self.last_state = None
        self.window_warned = False
        self.exit_pending = False  # 스크립트가 뽑기를 했고 아직 기본 화면으로 못 돌아옴

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

    def tap(self, xy, why):
        log(f"  ▶ {why} : tap {xy}" + ("  [dry-run]" if self.dry else ""))
        if not self.dry:
            tap(*xy)

    def esc(self, why):
        log(f"  ▶ {why} : ESC" + ("  [dry-run]" if self.dry else ""))
        if not self.dry:
            key(KEY_ESC)

    def escape_to_battle(self):
        """뽑기 후 기본(전투) 화면까지 빠져나옴.
        결과창 → '터치하여 닫기' 탭 / '신규' 등 닫기 문구 화면 → 문구 위치 탭 / 소환 화면 → ESC.
        전투 화면에서는 ESC 를 보내지 않음 (종료창 위험). 실패하면 exit_pending 을 유지해 다음 주기에 이어서 시도."""
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
                time.sleep(ESC_SETTLE_SEC)   # 닫히는 중에 ESC 가 한 번 더 들어가 전투 화면에 닿지 않도록
            elif state == "UNKNOWN":
                unknown += 1           # 전환 애니메이션일 수 있음 - 다시 확인
                if unknown == UNKNOWN_FALLBACK:
                    log("  ! 모르는 화면이 계속됨 - 화면 저장: " + save_shot(s, "unknown_after_summon"))
                    self.tap(RESULT_CLOSE_TAP, "하단 중앙 탭 (닫기 문구 기본 위치)")
                    unknown = 0
            else:
                self.exit_pending = False
                return True
            time.sleep(1.5)
        log("  ! 기본 화면 복귀 실패 - 다음 주기에 다시 시도")
        return False

    def same_summon_mission(self, id_img):
        if self.summoned_id is None or self.summoned_id.shape != id_img.shape:
            return False
        sc = float(cv2.matchTemplate(id_img, self.summoned_id, cv2.TM_CCOEFF_NORMED)[0][0])
        if sc < SAME_MISSION_TH:
            log(f"  새 소환 미션 (직전 뽑기 미션 번호와 일치도 {sc:.2f} < {SAME_MISSION_TH})")
        return sc >= SAME_MISSION_TH

    def do_summon(self, panel_xy, id_img):
        self.tap(panel_xy, "가이드 뽑기 미션 → 소환 화면 이동")
        if self.dry:
            return
        time.sleep(2.5)
        s = self.look()
        state, info = read_screen(s)
        if state != "SUMMON_SCREEN":
            log(f"  ! 소환 화면이 아님({state}) - 뽑기 생략")
            self.escape_to_battle()
            return
        self.tap(SUMMON_30_TAP, "30회 뽑기")
        self.summoned_id = id_img
        self.exit_pending = True
        self.cnt["summon"] += 1
        log(f"  {AFTER_SUMMON_WAIT_SEC}초 대기 (오동작 방지)")
        time.sleep(AFTER_SUMMON_WAIT_SEC)
        self.escape_to_battle()

    def tick(self):
        if self.exit_pending:          # 지난번 뽑기 후 복귀를 못 끝냈으면 그것부터
            if not self.escape_to_battle():
                return
        s = self.look()
        state, info = read_screen(s)
        if state != self.last_state and not (state == "GUIDE_SUMMON" and self.last_state == "GUIDE_SUMMON_WAIT"):
            waiting = state in ("UNKNOWN", "SUMMON_SCREEN", "SUMMON_RESULT", "CLOSE_TEXT")
            log(f"상태: {state}" + ("  → 기본 화면이 아님, 대기" if waiting else ""))
            self.last_state = state

        if state == "REPEAT":
            # [반복] 은 '소환' 문구여도 탭만 하면 모험 코인 지급 → 절대 뽑기 하지 않음
            self.tap(info["tap"], "[반복] 미션 수령 (모험 코인)")
            self.cnt["repeat"] += 1
            if not self.dry:
                time.sleep(1.5)
                if read_screen(self.look())[0] in ("SUMMON_SCREEN", "SUMMON_RESULT"):
                    log("  ! [반복] 탭 후 소환 화면이 열림 - 뽑지 않고 복귀")
                    self.escape_to_battle()
        elif state == "GUIDE_CLEAR":
            self.tap(info["tap"], f"가이드 클리어 → 보상 수령 (분홍 {info['pink']*100:.0f}%)")
            self.cnt["guide"] += 1
        elif state == "GUIDE_SUMMON":
            if self.same_summon_mission(info["id_img"]):
                # 이 미션에서 이미 30회 뽑음 → 1회만. 다시 뽑지 않고 클리어 표시 대기
                if self.last_state != "GUIDE_SUMMON_WAIT":
                    log("  이 소환 미션은 이미 30회 뽑음 - 클리어 표시 대기 (재뽑기 안 함)")
                self.last_state = "GUIDE_SUMMON_WAIT"
                return
            self.do_summon(info["tap"], info["id_img"])
        # 그 외 (GUIDE_PROGRESS / 채팅·길드·상점 등 UNKNOWN / 사용자가 직접 연 소환·결과 화면)
        # → 아무것도 누르지 않고 다음 주기까지 대기. 기본 화면으로 돌아오면 자동으로 이어서 동작.
        if state in ("REPEAT", "GUIDE_CLEAR", "GUIDE_SUMMON"):
            log(f"  누적: 가이드 {self.cnt['guide']} / 반복 {self.cnt['repeat']} / 30회 뽑기 {self.cnt['summon']}")

    def run(self):
        log(f"시작 - 기기 {DEV}, {INTERVAL_SEC}초 주기" + (" (dry-run)" if self.dry else ""))
        try:
            while True:
                try:
                    self.tick()
                except subprocess.SubprocessError as e:
                    log(f"ADB 오류: {e} - 재시도")
                except Exception as e:
                    log(f"오류: {e}")
                time.sleep(INTERVAL_SEC)
        except KeyboardInterrupt:
            log(f"종료 - 가이드 {self.cnt['guide']} / 반복 {self.cnt['repeat']} / 30회 뽑기 {self.cnt['summon']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="윈드러너 키우기 가이드 미션 자동 루프")
    ap.add_argument("--dry-run", action="store_true", help="판정만 출력하고 탭/ESC 하지 않음")
    Bot(ap.parse_args().dry_run).run()
