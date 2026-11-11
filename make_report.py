"""버그 제보용 파일 묶기

실행하면 바탕화면에 windrunner_bug_report_날짜_시간.zip 을 만든다. 들어가는 것:
  - logs/ 의 최근 3일치 로그 (guide_*.log)
  - logs/ 의 오류 화면 캡처 최근 20장 (*.png)
  - 지금 게임 화면 캡처 1장 (MuMu 가 켜져 있으면)
  - 환경 정보 (Windows/Python/OpenCV 버전, ADB 기기, 화면 해상도, 설정값)
  - 상황설명.txt (제보할 때 적을 내용 양식)

주의: 로그·캡처에는 게임 닉네임이 보일 수 있다. 공개 게시판(GitHub Issues)에 올릴 때는 확인 후 올릴 것.
"""
import datetime as dt
import glob
import os
import platform
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "logs")
sys.stdout.reconfigure(encoding="utf-8")

TEMPLATE = """[윈드러너 자동화 오류 제보]

1. 언제 발생했나요? (날짜/시간, 대략이라도)
   예) 11월 11일 20시 50분쯤

2. 어떤 문제가 있었나요?
   예) 소환 미션인데 뽑기를 안 하고 계속 기다림 / 클리어인데 수령을 안 함 / 엉뚱한 곳을 누름

3. 그때 게임 화면은 어땠나요?
   예) 처음 보는 스테이지(초록 숲 배경), 패배 창, 이벤트 팝업 등

4. 매번 그런가요, 가끔 그런가요?

5. 기타
"""


def desktop():
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)   # CSIDL_DESKTOPDIRECTORY
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def env_info():
    lines = [f"생성 시각: {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Windows: {platform.platform()}",
             f"Python: {sys.version.split()[0]}"]
    try:
        import cv2, numpy
        lines += [f"OpenCV: {cv2.__version__}", f"numpy: {numpy.__version__}"]
    except Exception as e:
        lines.append(f"OpenCV/numpy 불러오기 실패: {e}")
    return lines


def main():
    now = dt.datetime.now()
    out = os.path.join(desktop(), f"windrunner_bug_report_{now:%Y%m%d_%H%M}.zip")
    info = env_info()
    shot_png = None

    # 지금 화면 + ADB 정보 (실패해도 계속)
    try:
        sys.path.insert(0, BASE)
        import guide_auto as ga
        info += [f"ADB: {ga.ADB}", f"기기: {ga.DEV}"]
        try:
            info.append("화면: " + ga.adb("shell", "wm", "size").decode().strip())
        except Exception:
            pass
        img = ga.screencap()
        import cv2
        shot_png = cv2.imencode(".png", img)[1].tobytes()
        state = ga.read_screen(img)[0]
        info.append(f"현재 화면 판정: {state}")
        info.append(f"설정: INTERVAL_SEC={ga.INTERVAL_SEC}, AFTER_SUMMON_WAIT_SEC={ga.AFTER_SUMMON_WAIT_SEC}, "
                    f"RETRY_ON_DEFEAT={ga.RETRY_ON_DEFEAT}, RETRY_LIMIT={ga.RETRY_LIMIT}")
    except SystemExit as e:
        info.append(f"게임 화면 캡처 안 됨: {e}")
    except Exception as e:
        info.append(f"게임 화면 캡처 안 됨: {e!r}")

    logs = sorted(glob.glob(os.path.join(LOG_DIR, "guide_*.log")))[-3:]
    pngs = sorted(glob.glob(os.path.join(LOG_DIR, "*.png")), key=os.path.getmtime)[-20:]

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("상황설명.txt", TEMPLATE.encode("utf-8-sig"))
        z.writestr("환경정보.txt", ("\n".join(info) + "\n").encode("utf-8-sig"))
        for f in logs:
            z.write(f, "logs/" + os.path.basename(f))
        for f in pngs:
            z.write(f, "screens/" + os.path.basename(f))
        if shot_png:
            z.writestr(f"screens/current_{now:%Y%m%d_%H%M%S}.png", shot_png)

    print()
    print("버그 제보 파일을 만들었습니다:")
    print("  " + out)
    print(f"  (로그 {len(logs)}개, 화면 캡처 {len(pngs) + (1 if shot_png else 0)}장)")
    print()
    print("이 파일을 아래 중 한 곳으로 보내 주세요.")
    print("  - 이메일: windrunner-bug.harmonics426@slmail.me  (제목에 [윈드러너 오류])")
    print("  - GitHub: https://github.com/l1539ym-cyber/windrunner-guide-auto/issues/new?template=bug_report.md")
    print("※ 캡처에 게임 닉네임이 보일 수 있습니다. 공개 게시판에 올릴 때는 확인해 주세요.")
    try:
        subprocess.Popen(["explorer", "/select,", out])
    except Exception:
        pass


if __name__ == "__main__":
    main()
