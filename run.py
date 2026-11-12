"""실행 관리자 (run_guide.bat 이 부르는 프로그램)

  1) 시작할 때 새 버전이 있으면 자동 업데이트 (user_settings.py 의 AUTO_UPDATE=False 또는 --dry-run 이면 확인만)
  2) 업데이트했으면 필요한 부품(pip) 설치 → 성공을 확인한 뒤에만 실행
  3) guide_auto.py 실행
  4) guide_auto.py 가
       - 종료 코드 3 (실행 중 새 버전 발견) → 업데이트 후 바로 다시 실행
       - 종료 코드 4 (adb.exe 없음 등)    → 1분 후 다시 실행
       - 오류로 종료 (MuMu 꺼짐 등)       → 10초 후 다시 실행
     오류로 다시 시작할 때도 10분에 한 번은 새 버전을 확인 (오류를 고친 업데이트를 받을 수 있게)
       - 정상 종료 (Ctrl+C)              → 끝
"""
import os
import subprocess
import sys
import time

import updater

BASE = os.path.dirname(os.path.abspath(__file__))
EXIT_UPDATE = 3
EXIT_CONFIG = 4
ERROR_UPDATE_CHECK_SEC = 600
SCRIPT = os.environ.get("WINDRUNNER_SCRIPT", "guide_auto.py")   # 테스트용으로 바꿀 수 있음
INSTALL_HINT = ("README 2단계의 설치 명령(PowerShell 한 줄)을 다시 붙여넣으면 최신 버전으로 다시 설치됩니다. "
                "(logs/, user_settings.py 는 유지)")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def pip_install(tries=2):
    """업데이트로 필요한 부품이 바뀌었을 수 있으니 설치하고, 실제로 불러와지는지 확인. 성공하면 True"""
    for i in range(tries):
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "-r", os.path.join(BASE, "requirements.txt")])
        if r.returncode == 0:
            ok = subprocess.run([sys.executable, "-c", "import cv2, numpy"]).returncode == 0
            if ok:
                return True
            print("[업데이트] 부품 설치는 끝났지만 불러오기(import cv2, numpy) 실패", flush=True)
        else:
            print(f"[업데이트] 부품 설치(pip) 실패 (코드 {r.returncode})", flush=True)
        if i + 1 < tries:
            print("[업데이트] 5초 후 부품 설치를 다시 시도합니다...", flush=True)
            time.sleep(5)
    return False


def update(dry):
    """업데이트 확인/적용. 계속 실행해도 되면 True"""
    apply = updater.auto_update_enabled() and not dry
    status = updater.check_and_update(apply=apply)
    if status == updater.BROKEN:
        print("\n[업데이트] 지난 업데이트가 중간에 실패해 프로그램 파일이 섞였을 수 있어 실행하지 않습니다.\n  "
              + INSTALL_HINT, flush=True)
        return False
    if status == updater.UPDATED and not pip_install():
        print("\n[업데이트] 새 버전에 필요한 부품을 설치하지 못해 실행하지 않습니다. 인터넷 연결을 확인하고 "
              "run_guide.bat 을 다시 실행하세요.\n  계속 안 되면 " + INSTALL_HINT, flush=True)
        return False
    return True


def main():
    dry = "--dry-run" in sys.argv[1:]
    if not update(dry):
        return 1
    last_check = time.time()
    while True:
        try:
            code = subprocess.call([sys.executable, os.path.join(BASE, SCRIPT), *sys.argv[1:]], cwd=BASE)
        except KeyboardInterrupt:
            break
        if code == 0:
            break
        if code == EXIT_UPDATE:
            print("\n[업데이트] 새 버전을 적용하고 다시 시작합니다...", flush=True)
            if not update(dry):
                return 1
            continue
        wait = 60 if code == EXIT_CONFIG else 10
        print(f"\n[자동 재시작] 프로그램이 오류로 멈춤 (코드 {code}). {wait}초 후 다시 시작합니다. "
              "완전히 끄려면 이 창을 닫으세요.", flush=True)
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            break
        if time.time() - last_check >= ERROR_UPDATE_CHECK_SEC:   # 오류를 고친 새 버전이 있을 수 있음
            last_check = time.time()
            if not update(dry):
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
