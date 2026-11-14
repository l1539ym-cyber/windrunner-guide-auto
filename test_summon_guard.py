"""소환 화면 방치 / 엉뚱한 탭 방지 자가 점검: python test_summon_guard.py
2026-11-12 제보: 클리어 보상을 연달아 누르다 다음 미션(소환)이 눌려 소환 화면이 열렸는데, 사용자가 연 화면으로
보고 2~16분 동안 기다림 (그동안 게임은 절전 잠금 화면으로 바뀜). 복귀 중 모르는 화면에서 하단 중앙을 눌러
메뉴·캐릭터 목록·강화 화면이 열림. 화면 판정은 각본대로 돌려주고 (가짜 시계, 실제 입력 없음) 봇의 행동만 확인한다."""
import guide_auto as g

STATES = {
    "클리어": ("GUIDE_CLEAR", {"tap": (490, 1201), "why": "test"}),
    "소환미션": ("GUIDE_SUMMON", {"tap": (490, 1201)}),
    "진행중": ("GUIDE_PROGRESS", {}),
    "소환": ("SUMMON_SCREEN", {"cost": "ticket", "cost_why": "test"}),
    "결과": ("SUMMON_RESULT", {}),
    "모름": ("OTHER", {}),
}


class Clock:
    t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, sec):
        self.t += sec


def setup(script):
    """script: [(시작 후 이 시각(초) 부터, 화면 이름), ...] → (bot, 입력 기록, 시계)"""
    clock = Clock()
    start = clock.t
    g.time = clock
    g.log = lambda msg: None
    g.save_shot = lambda img, tag: "(저장 생략)"
    g.game_in_front = lambda: True
    g.AUTO_UPDATE = False
    events = []
    g.tap = lambda x, y: events.append((round(clock.t - start, 1), "tap", (x, y)))
    g.key = lambda code: events.append((round(clock.t - start, 1), "key", code))

    def screen_now():
        now = clock.t - start
        return [n for at, n in script if now >= at][-1]

    g.Bot.look = lambda self: (clock.sleep(0.3), screen_now())[1]
    g.read_screen = lambda name: STATES[name]
    return g.Bot(False), events, clock, start


def run_ticks(bot, clock, start, until):
    while clock.t - start < until:
        bot.acted = False
        bot.tick()
        clock.sleep(g.ACTION_INTERVAL_SEC if bot.acted else g.INTERVAL_SEC)


def taps(events, xy=None):
    return [(t, v) for t, k, v in events if k == "tap" and (xy is None or v == xy)]


def escs(events):
    return [t for t, k, _ in events if k == "key" and _ == g.KEY_ESC]


# 1) 클리어 수령 직후 다음 미션(소환)이 눌려 소환 화면이 열림 → 뽑지 않고 바로 복귀
bot, ev, clock, start = setup([(0, "클리어"), (1.5, "소환"), (12, "진행중")])
g.ESC_SETTLE_SEC = 3.0
run_ticks(bot, clock, start, 30)
assert len(taps(ev, (490, 1201))) == 1, ev
assert not taps(ev, g.SUMMON_30_TAP), "봇이 잘못 연 소환 화면에서 30회를 누름"
assert escs(ev) and escs(ev)[0] < 10, f"소환 화면을 빠져나오지 않음 (방치) {ev}"

# 2) 클리어로 보였지만 다시 보니 다음 미션으로 바뀌는 중 → 누르지 않음
bot, ev, clock, start = setup([(0, "클리어"), (0.5, "진행중")])
run_ticks(bot, clock, start, 4)
assert not taps(ev), f"바뀌는 중인 패널을 누름 {ev}"

# 3) 사용자가 직접 연 소환 화면 → 바로 건드리지 않고, 조작 없이 90초 넘게 그대로면 복귀
bot, ev, clock, start = setup([(0, "소환"), (200, "진행중")])
run_ticks(bot, clock, start, 60)
assert not ev, f"사용자가 연 소환 화면을 바로 닫음 {ev}"
run_ticks(bot, clock, start, 120)
assert escs(ev) and g.SUMMON_IDLE_SEC <= escs(ev)[0] < g.SUMMON_IDLE_SEC + 15, ev
assert not taps(ev, g.SUMMON_30_TAP)

# 4) 사용자가 계속 뽑는 중 (소환 ↔ 결과가 바뀜) → 끼어들지 않음
script = [(t, "소환" if (t // 40) % 2 == 0 else "결과") for t in range(0, 400, 40)]
bot, ev, clock, start = setup(script)
run_ticks(bot, clock, start, 390)
assert not ev, f"사용자가 뽑는 중인데 끼어듦 {ev}"

# 5) 복귀 중 모르는 화면(채팅창·메뉴 등)이 계속됨 → 아무 곳이나 누르지 않고 ESC 한 번만
bot, ev, clock, start = setup([(0, "모름")])
bot.exit_pending = True
bot.escape_to_base()
assert not taps(ev), f"모르는 화면에서 짐작으로 탭함 {ev}"
assert len(escs(ev)) == 1, ev
print("ok")
