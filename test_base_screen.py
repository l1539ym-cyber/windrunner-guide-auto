"""is_base_screen() 자가 점검: python test_base_screen.py
기본 화면 UI 요소를 붙인 가짜 화면으로 채팅 아이콘 종류(말풍선 / 길드 방패)·배경색·어두운 팝업 판정을 확인한다.
(실제 화면 캡처는 개인 정보가 있어 저장소에 넣지 않으므로 템플릿만으로 만든다)"""
import numpy as np

import guide_auto as g

BACKGROUNDS = {"갈색": (60, 90, 110), "초록": (60, 70, 30), "하늘": (230, 200, 150), "회색": (110, 110, 110)}


def screen(bg, chat=None, others=("hud_event", "hud_ranking", "hud_pass", "hud_chapter")):
    s = np.zeros((g.SCREEN_SIZE[1], g.SCREEN_SIZE[0], 3), np.uint8)
    s[:] = bg
    for k in others:
        x1, y1 = g.HUD[k][:2]
        t = g.T("hud/" + k)
        s[y1 + 20:y1 + 20 + t.shape[0], x1 + 20:x1 + 20 + t.shape[1]] = t
    if chat:
        # 아이콘 뒤 원은 반투명 → 흰색 아이콘만 붙이고 나머지는 스테이지 배경색 그대로
        t = g.T("hud/chat/" + chat)
        x, y = g.CHAT_ROI[0] + 28, g.CHAT_ROI[1] + 29
        area = s[y:y + t.shape[0], x:x + t.shape[1]]
        white = g.white_mask(t) > 0
        area[white] = t[white]
    return s


for bg_name, bg in BACKGROUNDS.items():
    for chat in ("bubble", "guild"):
        s = screen(bg, chat)
        assert g.is_base_screen(s), (bg_name, chat, g.hud_summary(s))
        assert g.chat_score(s)[1] == chat, (bg_name, chat, g.chat_score(s))
        dim = (s * 0.35).astype(np.uint8)                  # 팝업이 떠서 어두워진 화면
        assert not g.is_base_screen(dim), ("어두운 팝업", bg_name, chat, g.hud_summary(dim))
        assert not g.is_base_screen(screen(bg, chat, others=("hud_event",))), (bg_name, chat, "나머지 1개")
    s = screen(bg)
    assert not g.is_base_screen(s), ("채팅 아이콘 없음", bg_name, g.hud_summary(s))
print("ok")
