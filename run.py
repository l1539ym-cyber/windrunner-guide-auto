"""실행 관리자 (run_guide.bat 이 부르는 프로그램)

  1) 시작할 때 새 버전이 있으면 자동 업데이트
  2) guide_auto.py 실행
  3) guide_auto.py 가
       - 종료 코드 3 (실행 중 새 버전 발견) → 업데이트 후 바로 다시 실행
       - 오류로 종료 (MuMu 꺼짐 등)       → 10초 후 다시 실행
       - 정상 종료 (Ctrl+C)              → 끝
"""
import os
import subprocess
import sys
import time

import updater

BASE = os.path.dirname(os.path.abspath(__file__))
EXIT_UPDATE = 3
SCRIPT = os.environ.get("WINDRUNNER_SCRIPT", "guide_auto.py")   # 테스트용으로 바꿀 수 있음

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def pip_install():
    """업데이트로 필요한 부품이 바뀌었을 수 있으니 확인 (이미 있으면 금방 끝남)"""
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                    "-r", os.path.join(BASE, "requirements.txt")])


def main():
    if updater.check_and_update():
        pip_install()
    while True:
        try:
            code = subprocess.call([sys.executable, os.path.join(BASE, SCRIPT), *sys.argv[1:]], cwd=BASE)
        except KeyboardInterrupt:
            break
        if code == 0:
            break
        if code == EXIT_UPDATE:
            print("\n[업데이트] 새 버전을 적용하고 다시 시작합니다...", flush=True)
            if updater.check_and_update():
                pip_install()
            continue
        print(f"\n[자동 재시작] 프로그램이 오류로 멈춤 (코드 {code}). 10초 후 다시 시작합니다. "
              "완전히 끄려면 이 창을 닫으세요.", flush=True)
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
