"""자동 업데이트

GitHub 저장소의 최신 커밋과 설치된 버전(.version 파일)을 비교해서,
새 버전이 있으면 ZIP 으로 내려받아 프로그램 파일을 덮어쓴다 (Git 불필요).

  python updater.py            # 확인 후 새 버전이 있으면 업데이트
  python updater.py --check    # 확인만

- logs/, user_settings.py, .version 등 사용자 파일은 건드리지 않는다.
- .git 폴더가 있는 개발용 폴더에서는 자동 업데이트하지 않는다 (수정 중인 코드 보호).
"""
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

REPO = "l1539ym-cyber/windrunner-guide-auto"
BRANCH = "main"
BASE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(BASE, ".version")
KEEP = {"logs", "user_settings.py", ".version", "__pycache__", ".git"}   # 덮어쓰지 않을 것
UA = {"User-Agent": "windrunner-guide-auto-updater"}

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def is_dev_folder():
    return os.path.isdir(os.path.join(BASE, ".git"))


def local_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def remote_info(timeout=10):
    """GitHub 최신 커밋 → (sha, 커밋 메시지 첫 줄, 날짜)"""
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    msg = d["commit"]["message"].splitlines()[0]
    return d["sha"], msg, d["commit"]["committer"]["date"]


def update_available():
    """새 버전이 있으면 (sha, 메시지, 날짜), 없거나 확인 실패면 None"""
    if is_dev_folder():
        return None
    try:
        sha, msg, date = remote_info()
    except Exception:
        return None
    return (sha, msg, date) if sha != local_version() else None


def apply_update(sha, log=print):
    """해당 커밋의 ZIP 을 받아 프로그램 파일을 덮어씀. 성공하면 True"""
    url = f"https://github.com/{REPO}/archive/{sha}.zip"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        root = names[0].split("/")[0] + "/"          # windrunner-guide-auto-<sha>/
        files = [n for n in names if n.startswith(root) and not n.endswith("/")]
        if not any(n.endswith("guide_auto.py") for n in files):
            raise RuntimeError("내려받은 파일이 올바르지 않음")
        for n in files:
            rel = n[len(root):]
            if rel.split("/")[0] in KEEP:
                continue
            dst = os.path.join(BASE, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp"
            with z.open(n) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(tmp, dst)
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(sha)
    return True


def check_and_update(log=print):
    """시작할 때 호출: 새 버전이 있으면 업데이트. 업데이트했으면 True"""
    if is_dev_folder():
        log("[업데이트] 개발용 폴더(.git 있음) - 자동 업데이트 안 함")
        return False
    try:
        sha, msg, date = remote_info()
    except Exception as e:
        log(f"[업데이트] 최신 버전 확인 실패 (인터넷 연결 확인) - 지금 버전으로 실행: {e}")
        return False
    cur = local_version()
    if sha == cur:
        log(f"[업데이트] 최신 버전입니다 ({sha[:7]})")
        return False
    log(f"[업데이트] 새 버전 발견: {cur[:7] if cur else '알 수 없음'} → {sha[:7]}  \"{msg}\" ({date[:10]})")
    try:
        apply_update(sha, log)
    except Exception as e:
        log(f"[업데이트] 업데이트 실패 - 지금 버전으로 실행: {e}")
        return False
    log("[업데이트] 업데이트 완료")
    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("설치된 버전:", local_version(), "/ 개발용 폴더:", is_dev_folder())
        try:
            print("최신 버전:", remote_info())
        except Exception as e:
            print("확인 실패:", e)
    else:
        check_and_update()
