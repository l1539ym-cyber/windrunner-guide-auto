"""summon_cost() 자가 점검: python test_summon_cost.py
30회 비용 자리에 각 아이콘을 붙인 가짜 화면으로 뽑기권 종류 / 보석 / 빈 영역 판정을 확인한다.
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
print("ok")
