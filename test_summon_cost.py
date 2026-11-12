"""summon_cost() / 소환 화면 판정 자가 점검: python test_summon_cost.py
30회 비용 자리에 각 아이콘을 붙인 가짜 화면으로 뽑기권 종류 / 보석 / 빈 영역 판정과
캐릭터·소환수·탈것 소환 화면 인식을 확인한다.
(실제 화면 캡처는 개인 정보가 있어 저장소에 넣지 않으므로 템플릿만으로 만든다)"""
import numpy as np

import guide_auto as g


def screen(tpl=None):
    s = np.zeros((g.SCREEN_SIZE[1], g.SCREEN_SIZE[0], 3), np.uint8)
    s[:] = (0, 61, 102)                                    # 30회 버튼 비용 줄의 갈색
    s[1100:1200, 560:570] = (30, 170, 250)                 # 버튼 주황 테두리 (빈 영역도 무늬가 있게)
    if tpl is not None:
        t = g.T(tpl)
        s[1136:1136 + t.shape[0], 585:585 + t.shape[1]] = t
    return s


for kind, tpl in g.TICKET_TPLS.items():
    cost, why = g.summon_cost(screen(tpl))
    assert cost == "ticket" and f"({kind})" in why, (kind, cost, why)
assert g.summon_cost(screen("summon_cost_gem"))[0] == "gem"
assert g.summon_cost(screen())[0] == "unknown", g.summon_cost(screen())


# 소환 화면 판정: 30회 버튼 + 아래 탭 줄 '캐릭터' 글자 (소환수·탈것 탭이 선택돼 있어도 같은 자리)
def summon_screen(tpl, tab=True, btn=True):
    s = screen(tpl)
    for on, name, (x, y) in ((tab, "summon_char_tab", (275, 1415)), (btn, "summon_30_btn", (620, 1088))):
        if on:
            t = g.T(name)
            s[y:y + t.shape[0], x:x + t.shape[1]] = t
    return s


x1, y1, x2, y2 = g.SUMMON_BTN_ROI
assert x1 <= g.SUMMON_30_TAP[0] <= x2 and y1 <= g.SUMMON_30_TAP[1] <= y2, "30회 탭 위치가 버튼 영역 밖"
for kind, tpl in g.TICKET_TPLS.items():
    state, info = g.read_screen(summon_screen(tpl))
    assert state == "SUMMON_SCREEN" and info["cost"] == "ticket" and f"({kind})" in info["cost_why"], (kind, state, info)
state, info = g.read_screen(summon_screen("summon_cost_gem"))
assert state == "SUMMON_SCREEN" and info["cost"] == "gem", (state, info)
assert g.read_screen(summon_screen("summon_cost_ticket_pet", tab=False))[0] != "SUMMON_SCREEN"
assert g.read_screen(summon_screen("summon_cost_ticket_pet", btn=False))[0] != "SUMMON_SCREEN"
print("ok")
