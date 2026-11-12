"""자동 업데이트

GitHub 저장소의 최신 커밋과 설치된 버전(.version 파일)을 비교해서,
새 버전이 있으면 ZIP 으로 내려받아 프로그램 파일을 덮어쓴다 (Git 불필요).

  python updater.py            # 확인 후 새 버전이 있으면 업데이트
  python updater.py --check    # 확인만

- logs/, user_settings.py, .version 등 사용자 파일은 건드리지 않는다.
- .git 폴더가 있는 개발용 폴더에서는 자동 업데이트하지 않는다 (수정 중인 코드 보호).
- 업데이트는 ① 임시 폴더에 전부 풀고 검사 → ② 기존 파일 백업 → ③ 교체 순서로 진행하며,
  교체 중 실패하면 백업으로 전부 되돌린다. 되돌리기도 실패하면 .update_incomplete 표시를 남겨
  run.py 가 프로그램을 실행하지 않게 한다 (신·구 버전 파일이 섞인 상태로 실행 방지).
"""
import io
import json
import os
import posixpath
import py_compile
import runpy
import shutil
import sys
import tempfile
import urllib.request
import zipfile

REPO = "l1539ym-cyber/windrunner-guide-auto"
BRANCH = "main"
BASE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(BASE, ".version")
INCOMPLETE_FILE = os.path.join(BASE, ".update_incomplete")
STAGE_DIR = os.path.join(BASE, ".update_stage")
BACKUP_DIR = os.path.join(BASE, ".update_backup")
KEEP = {"logs", "user_settings.py", ".version", "__pycache__", ".git",
        ".update_incomplete", ".update_stage", ".update_backup"}   # 덮어쓰지 않을 것 (소문자로 비교)
UA = {"User-Agent": "windrunner-guide-auto-updater"}

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class UpdateError(RuntimeError):
    """업데이트 실패 (기존 버전은 그대로 / 또는 되돌림 완료)"""


class BrokenInstall(RuntimeError):
    """업데이트 실패 후 되돌리기도 실패 → 설치 상태를 믿을 수 없음"""


def install_incomplete():
    """지난 업데이트가 중간에 끊겨 파일이 섞였을 수 있으면 True"""
    return os.path.exists(INCOMPLETE_FILE)


def auto_update_enabled():
    """user_settings.py 의 AUTO_UPDATE (없으면 True). guide_auto.py 와 같은 설정을 run.py 에서도 사용"""
    path = os.path.join(BASE, "user_settings.py")
    if not os.path.exists(path):
        return True
    try:
        return bool(runpy.run_path(path).get("AUTO_UPDATE", True))
    except Exception as e:
        print(f"[업데이트] user_settings.py 를 읽지 못함 ({e}) - 기본값(자동 업데이트 켬) 사용", flush=True)
        return True


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


def safe_rel(name, root):
    """ZIP 항목 이름 → 설치 폴더 기준 상대 경로 조각들. 폴더 밖으로 나가는 경로면 UpdateError"""
    if not name.startswith(root):
        raise UpdateError(f"예상하지 못한 ZIP 항목: {name!r}")
    rel = name[len(root):]
    if "\\" in rel or ":" in rel or rel.startswith("/") or "\0" in rel:
        raise UpdateError(f"허용하지 않는 경로: {name!r}")
    norm = posixpath.normpath(rel)
    parts = norm.split("/")
    if norm in (".", "") or norm.startswith("../") or norm == ".." or any(p in ("", ".", "..") for p in parts):
        raise UpdateError(f"설치 폴더 밖을 가리키는 경로: {name!r}")
    dst = os.path.realpath(os.path.join(BASE, *parts))
    base = os.path.realpath(BASE)
    if os.path.commonpath([dst, base]) != base or dst == base:
        raise UpdateError(f"설치 폴더 밖을 가리키는 경로: {name!r}")
    return parts


def _download(sha):
    url = f"https://github.com/{REPO}/archive/{sha}.zip"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _stage(data, stage):
    """ZIP 을 stage 폴더에 전부 풀고 검사 → 교체할 상대 경로 목록"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if not names:
            raise UpdateError("내려받은 ZIP 이 비어 있음")
        root = names[0].split("/")[0] + "/"          # windrunner-guide-auto-<sha>/
        rels = []
        for n in names:
            if n == root or n.endswith("/"):
                if n != root:
                    safe_rel(n, root)
                continue
            parts = safe_rel(n, root)
            if parts[0].lower() in KEEP:
                continue
            dst = os.path.join(stage, *parts)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(n) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            rels.append(parts)
    names = {"/".join(p) for p in rels}
    for need in ("guide_auto.py", "run.py", "updater.py", "requirements.txt"):
        if need not in names:
            raise UpdateError(f"내려받은 파일이 올바르지 않음 ({need} 없음)")
    for parts in rels:                                # 문법 오류가 있는 코드는 설치하지 않음
        if parts[-1].endswith(".py"):
            try:
                py_compile.compile(os.path.join(stage, *parts), cfile=os.path.join(tempfile.gettempdir(),
                                   "windrunner_check.pyc"), doraise=True)
            except py_compile.PyCompileError as e:
                raise UpdateError(f"내려받은 코드 검사 실패: {'/'.join(parts)}: {e.msg}")
    return rels


def _swap(rels, stage, backup):
    """기존 파일을 백업하고 새 파일로 교체. 실패하면 되돌림"""
    done = []        # (dst, 백업 경로 또는 None=새로 생긴 파일)
    try:
        for parts in rels:
            dst = os.path.join(BASE, *parts)
            bak = None
            if os.path.exists(dst):
                bak = os.path.join(backup, *parts)
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(dst, bak)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(stage, *parts), dst)
            done.append((dst, bak))
    except Exception as e:
        problems = []
        for dst, bak in reversed(done):
            try:
                if bak:
                    tmp = dst + ".restore"
                    shutil.copy2(bak, tmp)
                    os.replace(tmp, dst)
                else:
                    os.remove(dst)
            except Exception as e2:
                problems.append(f"{dst}: {e2}")
        if problems:
            raise BrokenInstall(f"교체 실패({e}) 후 되돌리기도 실패: " + "; ".join(problems))
        raise UpdateError(f"파일 교체 실패 - 이전 버전으로 되돌림: {e}")


def apply_update(sha, log=print):
    """해당 커밋의 ZIP 을 받아 프로그램 파일을 교체. 성공하면 True.
    실패하면 UpdateError (이전 버전 그대로) 또는 BrokenInstall (파일이 섞였을 수 있음)"""
    data = _download(sha)
    for d in (STAGE_DIR, BACKUP_DIR):
        shutil.rmtree(d, ignore_errors=True)
    try:
        os.makedirs(STAGE_DIR)
        rels = _stage(data, STAGE_DIR)
        with open(INCOMPLETE_FILE, "w", encoding="utf-8") as f:     # 교체 중 꺼져도 알 수 있게
            f.write(sha)
        try:
            _swap(rels, STAGE_DIR, BACKUP_DIR)
        except UpdateError:
            os.remove(INCOMPLETE_FILE)                                 # 되돌리기 성공 = 이전 버전 정상
            raise
        tmp = VERSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(sha)
        os.replace(tmp, VERSION_FILE)
        os.remove(INCOMPLETE_FILE)
    finally:
        for d in (STAGE_DIR, BACKUP_DIR):
            shutil.rmtree(d, ignore_errors=True)
    return True


def _say(msg):
    print(msg, flush=True)


UPDATED, CURRENT, SKIPPED, FAILED, BROKEN = "updated", "current", "skipped", "failed", "broken"


def check_and_update(log=_say, apply=True):
    """새 버전이 있으면 업데이트 (apply=False 면 확인만).
    반환: UPDATED / CURRENT(최신 또는 확인 불가) / SKIPPED(새 버전 있지만 적용 안 함) /
          FAILED(실패, 이전 버전 그대로) / BROKEN(파일이 섞였을 수 있음 → 실행하면 안 됨)"""
    if is_dev_folder():
        log("[업데이트] 개발용 폴더(.git 있음) - 자동 업데이트 안 함")
        return CURRENT
    try:
        sha, msg, date = remote_info()
    except Exception as e:
        log(f"[업데이트] 최신 버전 확인 실패 (인터넷 연결 확인) - 지금 버전으로 실행: {e}")
        return BROKEN if install_incomplete() else CURRENT
    cur = local_version()
    if sha == cur and not install_incomplete():
        log(f"[업데이트] 최신 버전입니다 ({sha[:7]})")
        return CURRENT
    log(f"[업데이트] 새 버전 발견: {cur[:7] if cur else '알 수 없음'} → {sha[:7]}  \"{msg}\" ({date[:10]})")
    if not apply:
        log("[업데이트] 자동 업데이트가 꺼져 있어 적용하지 않음 (user_settings.py 의 AUTO_UPDATE)")
        return BROKEN if install_incomplete() else SKIPPED
    try:
        apply_update(sha, log)
    except BrokenInstall as e:
        log(f"[업데이트] 업데이트 실패, 이전 버전으로 되돌리지도 못함: {e}")
        return BROKEN
    except Exception as e:
        log(f"[업데이트] 업데이트 실패 - 이전 버전 그대로 실행: {e}")
        return BROKEN if install_incomplete() else FAILED
    log("[업데이트] 업데이트 완료")
    return UPDATED


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("설치된 버전:", local_version(), "/ 개발용 폴더:", is_dev_folder())
        try:
            print("최신 버전:", remote_info())
        except Exception as e:
            print("확인 실패:", e)
    else:
        check_and_update()
