"""핫딜 팝업 / 돌파 버튼 / 모드 전환 자가 점검: python test_hotdeal_mode.py
템플릿으로 만든 가짜 화면 + 가짜 시계로 확인한다 (실제 입력 없음).
  - 핫딜: 공통 요소 4가지가 모두 있어야만 인식, 제목이 좌우로 움직여도 인식, 구매 버튼은 절대 누르지 않음,
          닫기 성공 시 캡처 1장, 실패가 계속돼도 오류 캡처는 1장만 + 계속 재시도, 닫히면 복귀 기록
  - 돌파: 클리어 모드에서만 누름, 분홍 원이 없으면 누르지 않음
  - 모드: mode.txt 저장/읽기"""
import os
import tempfile

import cv2
import numpy as np

import guide_auto as g

REAL_LOAD_MODE = g.load_mode
g.load_mode = lambda: "idle"     # 폴더의 mode.txt 와 상관없이 방치 모드로 점검


# ---- 가짜 화면 ----
def blank(color=(40, 70, 110)):
    s = np.zeros((g.SCREEN_SIZE[1], g.SCREEN_SIZE[0], 3), np.uint8)
    s[:] = color
    return s


def paste(s, name, x, y):
    t = g.T(name)
    s[y:y + t.shape[0], x:x + t.shape[1]] = t
    return s


def base_screen():
    s = blank()
    for k, (x1, y1, _, _) in g.HUD.items():
        paste(s, "hud/" + k, x1 + 20, y1 + 20)
    t = g.T("hud/chat/bubble")
    x, y = g.CHAT_ROI[0] + 28, g.CHAT_ROI[1] + 29
    white = g.white_mask(t) > 0
    s[y:y + t.shape[0], x:x + t.shape[1]][white] = t[white]
    return s


BLUE = (235, 165, 40)     # BGR, OpenCV H≈101 (구매 버튼 파랑)


def hotdeal_screen(dx=0, won=True, pkg=True):
    s = blank((30, 60, 100))
    paste(s, "hotdeal/hotdeal_word", 156 + dx, 653)
    if pkg:
        paste(s, "hotdeal/support_package", 546 + dx, 653)
    paste(s, "hotdeal/timer_clock", 352, 713)
    cv2.rectangle(s, (337, 964), (562, 1031), BLUE, -1)
    if won:
        paste(s, "hotdeal/won_sign", 382, 984)
    return s


def breakthrough_screen(pink=True):
    s = base_screen()
    if pink:
        cv2.circle(s, (453, 314), 34, (200, 50, 240), -1)      # BGR, OpenCV H≈155 (분홍 원)
    paste(s, "breakthrough_text", 425, 332)
    return s


assert cv2.cvtColor(np.uint8([[BLUE]]), cv2.COLOR_BGR2HSV)[0, 0, 0] in range(95, 111)

# 1) 핫딜 인식
for dx in (-80, 0, 80):                                   # 캐릭터 이름 길이에 따라 제목이 좌우로 움직임
    st, info = g.read_screen(hotdeal_screen(dx))
    assert st == "HOTDEAL", (dx, st)
assert g.read_screen(hotdeal_screen(won=False))[0] != "HOTDEAL", "₩ 없이 핫딜로 인식"
assert g.read_screen(hotdeal_screen(pkg=False))[0] != "HOTDEAL", "'지원 패키지' 없이 핫딜로 인식"
assert g.read_screen(base_screen())[0] == "BASE_NO_PANEL"
info = g.read_screen(hotdeal_screen())[1]
assert not g.tap_hits_button(info["tap"], info["btn"]), "닫기 위치가 구매 버튼 근처"
assert g.tap_hits_button((450, 1000), info["btn"]), "구매 버튼 위를 막지 못함"


# ---- 가짜 시계 / 입력 ----
class Clock:
    t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, sec):
        self.t += sec


def make_bot(screens):
    """screens(clock) → 지금 화면. → (bot, 탭 기록, 저장한 캡처 태그)"""
    clock = Clock()
    g.time = clock
    taps, shots = [], []
    g.tap = lambda x, y: taps.append((x, y))
    g.key = lambda code: taps.append(("key", code))
    g.log = lambda msg: None
    g.save_shot = lambda img, tag: shots.append(tag) or tag
    g.Bot.look = lambda self: screens(clock)
    g.Bot.check_mode = lambda self: None
    bot = g.Bot(False)
    g.consume_reconnected = lambda: False
    g.game_in_front = lambda: True
    g.updater.update_available = lambda: None
    return bot, taps, shots, clock


HD, BASE = hotdeal_screen(), base_screen()

# 2) 핫딜 닫기 성공: 탭 1번 → 기본 화면, 캡처는 발견 1장뿐
bot, taps, shots, clock = make_bot(lambda c: HD if not taps else BASE)
bot.tick()
assert taps == [g.HOTDEAL_CLOSE_TAP], taps
assert shots == ["hotdeal"], shots
assert bot.hotdeal_tries == 0 and bot.cnt["hotdeal"] == 1

# 3) 핫딜이 안 닫힘: 여러 주기 동안 계속 탭하지만 오류 캡처는 1장만, 사라지면 복귀 기록
gone = {"at": None}
bot, taps, shots, clock = make_bot(lambda c: BASE if gone["at"] and c.t >= gone["at"] else HD)
for _ in range(5):
    bot.tick()
    clock.t += g.INTERVAL_SEC
assert len(taps) == 5 and all(t == g.HOTDEAL_CLOSE_TAP for t in taps), taps
assert shots == ["hotdeal", "hotdeal_error"], shots
assert bot.hotdeal_failed and bot.hotdeal_tries == 5
gone["at"] = clock.t                                       # 시간이 지나 핫딜이 저절로 사라짐
bot.tick()
assert bot.hotdeal_tries == 0 and not bot.hotdeal_failed and bot.cnt["hotdeal"] == 1
assert shots == ["hotdeal", "hotdeal_error"], "복귀 후 캡처를 더 남김"

# 4) 구매 버튼이 닫기 위치를 덮는 이상한 화면 → 누르지 않음
bot, taps, shots, clock = make_bot(lambda c: HD)
bot.on_hotdeal(HD, {"tap": (450, 1000), "btn": (337, 964, 562, 1031), "why": ""})
bot.on_hotdeal(HD, {"tap": (450, 1000), "btn": (337, 964, 562, 1031), "why": ""})
assert taps == [] and shots == ["hotdeal_error"], (taps, shots)

# 5) 돌파: 클리어 모드에서만, 분홍 원이 있을 때만
BT = breakthrough_screen()
assert g.find_breakthrough(BT), "돌파 버튼을 못 찾음"
assert g.find_breakthrough(breakthrough_screen(pink=False)) is None, "분홍 원 없이 돌파로 인식"
assert g.find_breakthrough(BASE) is None
for mode, want in (("idle", 0), ("clear", 1)):
    bot, taps, shots, clock = make_bot(lambda c: BT)
    bot.mode = mode
    bot.tick()
    assert len(taps) == want, (mode, taps)
    if want:
        x, y = taps[0]
        assert abs(x - 453) < 15 and abs(y - 314) < 15, taps
# 클리어 모드는 계속 누름 (횟수 제한 없음)
bot, taps, shots, clock = make_bot(lambda c: BT)
bot.mode = "clear"
for _ in range(10):
    bot.tick()
    clock.t += g.INTERVAL_SEC
assert len(taps) == 10, taps

# 7) 소환권 보상 미션 클리어: 패널에 빨강·노랑·초록 소환권 카드 무늬 → 클리어, 무늬가 없으면 진행 중
CARD_BGR = {"노랑": (40, 170, 235), "빨강": (40, 40, 220), "초록": (110, 200, 120)}


def guide_panel(card=None):
    s = base_screen()
    s[1145:1258, 238:665] = (60, 50, 45)                      # 어두운 반투명 패널
    paste(s, "guide_label_orange", 345, 1162)
    if card:
        for x in range(240, 665, 40):                         # 카드 무늬 (줄무늬로 흉내)
            s[1146:1256, x:x + 22] = CARD_BGR[card]
        paste(s, "guide_label_orange", 345, 1162)
    return s


for name in CARD_BGR:
    s = guide_panel(name)
    assert g.read_screen(s)[0] == "GUIDE_CLEAR", name
    assert g.card_pattern(s) and g.card_pattern(s)[0] == name, (name, g.card_pattern(s))
assert g.read_screen(guide_panel())[0] == "GUIDE_PROGRESS"
sky = guide_panel()
sky[1146:1256, 240:665] = (230, 170, 90)                      # 파란 하늘이 비치는 진행 중 패널
paste(sky, "guide_label_orange", 345, 1162)
assert g.read_screen(sky)[0] == "GUIDE_PROGRESS" and g.card_pattern(sky) is None, "파란 배경을 소환권 무늬로 봄"
# 노란 와플 스테이지 (2026-11-16 제보): 배경이 패널 안팎에 똑같이 노랑 → 카드 무늬 아님
waffle = base_screen()
waffle[1100:1300, 100:800] = (60, 140, 200)                   # 노란 와플 배경 (패널 바깥까지)
waffle[1145:1258, 238:665] = (40, 110, 160)                   # 반투명 패널 너머로 비치는 와플
paste(waffle, "guide_label_orange", 345, 1162)
assert g.card_pattern(waffle) is None, ("노란 배경을 소환권 무늬로 봄", g.card_pattern(waffle))
assert g.read_screen(waffle)[0] == "GUIDE_PROGRESS", g.read_screen(waffle)

# 6) mode.txt 저장/읽기
d = tempfile.mkdtemp()
g.MODE_FILE = os.path.join(d, "mode.txt")
g.load_mode = REAL_LOAD_MODE
assert g.load_mode() == g.DEFAULT_MODE
g.save_mode("clear")
assert g.load_mode() == "clear"
with open(g.MODE_FILE, "w", encoding="utf-8") as f:
    f.write("이상한 값")
assert g.load_mode() == g.DEFAULT_MODE
print("ok")
