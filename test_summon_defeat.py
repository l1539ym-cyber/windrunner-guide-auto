"""소환 중 패배 처리 자가 점검: python test_summon_defeat.py
소환 화면을 오가는 동안 패배 창이 뜨면 그 자리에서 '재도전'을 누르는지, 뽑기 후 결과 화면이 뜨면
10초를 다 기다리지 않고 빠져나오는지 확인한다. (가짜 시계 + 템플릿으로 만든 가짜 화면, 실제 입력 없음)"""
import numpy as np

import guide_auto as g


# ---- 가짜 화면 ----
def blank():
    s = np.zeros((g.SCREEN_SIZE[1], g.SCREEN_SIZE[0], 3), np.uint8)
    s[:] = (0, 61, 102)
    return s


def paste(s, name, x, y):
    t = g.T(name)
    s[y:y + t.shape[0], x:x + t.shape[1]] = t
    return s


def summon_screen():
    s = blank()
    paste(s, "summon_char_tab", 275, 1415)
    paste(s, "summon_30_btn", 620, 1088)
    return paste(s, "summon_cost_ticket_pet", 585, 1136)


def defeat_screen(over_summon):
    s = summon_screen() if over_summon else blank()
    paste(s, "defeat_title", 350, 600)
    return paste(s, "defeat_retry_btn", 520, 1130)


def result_screen():
    return paste(blank(), "summon_result_close", 365, 1470)


def base_screen():
    s = blank()
    for k, (x1, y1, _, _) in g.HUD.items():
        paste(s, "hud/" + k, x1 + 20, y1 + 20)
    t = g.T("hud/chat/bubble")
    x, y = g.CHAT_ROI[0] + 28, g.CHAT_ROI[1] + 29
    white = g.white_mask(t) > 0
    s[y:y + t.shape[0], x:x + t.shape[1]][white] = t[white]
    return s


SCREENS = {"소환": summon_screen(), "패배(소환 위)": defeat_screen(True), "패배": defeat_screen(False),
           "결과": result_screen(), "기본": base_screen()}
assert g.read_screen(SCREENS["소환"])[0] == "SUMMON_SCREEN"
assert g.read_screen(SCREENS["패배(소환 위)"])[0] == "DEFEAT"
assert g.read_screen(SCREENS["결과"])[0] == "SUMMON_RESULT"
assert g.read_screen(SCREENS["기본"])[0] == "BASE_NO_PANEL"
RETRY_XY = g.read_screen(SCREENS["패배"])[1]["tap"]


# ---- 가짜 시계 / 입력 ----
class Clock:
    t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, sec):
        self.t += sec


def run(script):
    """script: [(이 시각(초) 부터, 화면 이름), ...]. 30회 뽑기 탭 시각을 0초로 친다.
    → (입력 기록 [(시각, 입력)], 30회 탭 후 기본 화면 복귀까지 걸린 시간)"""
    clock = Clock()
    g.time = clock
    events = []
    t0 = {}
    g.tap = lambda x, y: events.append((clock.t - t0.get("summon", clock.t), ("tap", (x, y))))
    g.key = lambda code: events.append((clock.t - t0.get("summon", clock.t), ("key", code)))
    g.log = lambda msg: None
    g.save_shot = lambda img, tag: "(저장 생략)"

    def look(self):
        clock.t += 0.3                                        # 캡처에 걸리는 시간
        if "summon" not in t0:
            return SCREENS["소환"]                            # 30회 탭 전: 소환 화면
        now = clock.t - t0["summon"]
        name = [n for at, n in script if now >= at][-1]
        return SCREENS[name]

    g.Bot.look = look
    bot = g.Bot(False)
    orig_tap = bot.tap

    def tap(xy, why):
        if xy == g.SUMMON_30_TAP and "summon" not in t0:
            t0["summon"] = clock.t
        orig_tap(xy, why)

    bot.tap = tap
    bot.do_summon((490, 1201))
    assert not bot.exit_pending, "기본 화면까지 복귀하지 못함"
    return events, clock.t - t0["summon"]


def taps(events, xy):
    return [t for t, (kind, v) in events if kind == "tap" and v == xy]


# 1) 뽑기 연출 중(4~9초) 소환 화면 위에 패배 창 → 그 자리에서 재도전, 결과 화면 뜨면 바로 복귀
ev, took = run([(0, "소환"), (4, "패배(소환 위)"), (6.5, "결과"), (8, "소환"), (12, "기본")])
assert len(taps(ev, RETRY_XY)) == 1 and 4 <= taps(ev, RETRY_XY)[0] < 6.5, ev
assert len(taps(ev, g.SUMMON_30_TAP)) == 1, "30회를 두 번 누름"
assert not any(kind == "key" and 4 <= t < 6.5 for t, (kind, _) in ev), "패배 창에 ESC 를 보냄"

# 2) 결과 화면이 2초에 뜸 → 최소 3초는 기다리고, 10초를 다 기다리지 않고 닫기
ev, took = run([(0, "소환"), (2, "결과"), (6, "소환"), (9, "기본")])
close = taps(ev, g.RESULT_CLOSE_TAP)
assert close and g.AFTER_SUMMON_MIN_SEC <= close[0] < g.AFTER_SUMMON_WAIT_SEC, (close, ev)

# 3) 소환 화면을 ESC 로 빠져나왔더니 기본 화면 위에 패배 창 → 재도전 후 복귀 완료
ev, took = run([(0, "소환"), (4, "결과"), (6, "소환"), (9, "패배"), (13, "기본")])
assert len(taps(ev, RETRY_XY)) == 1 and 9 <= taps(ev, RETRY_XY)[0] < 13, ev

# 4) 재도전 끄기(RETRY_ON_DEFEAT=False) → 패배 창이 있어도 누르지 않고, 닫힐 때까지 기다렸다가 복귀
g.RETRY_ON_DEFEAT = False
ev, took = run([(0, "소환"), (4, "결과"), (6, "소환"), (9, "패배"), (19, "기본")])
assert not taps(ev, RETRY_XY), ev
assert not any(kind == "key" and 9 <= t < 19 for t, (kind, _) in ev), "패배 창에 ESC 를 보냄"
print("ok")
