"""ADB helper for MuMu Player: screenshot / tap / swipe / back.

CLI usage:
    python adbtool.py cap [out.png]
    python adbtool.py tap X Y
    python adbtool.py swipe X1 Y1 X2 Y2 [ms]
    python adbtool.py back
"""
import subprocess
import sys

import cv2
import numpy as np

ADB = r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
SERIAL = "emulator-5556"


def adb(*args, binary=False):
    out = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "ignore")


def screencap():
    """Return current screen as a BGR numpy image."""
    data = adb("exec-out", "screencap", "-p", binary=True)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("screencap failed")
    return img


def tap(x, y):
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def swipe(x1, y1, x2, y2, ms=300):
    adb("shell", "input", "swipe", *map(str, map(int, (x1, y1, x2, y2, ms))))


def back():
    adb("shell", "input", "keyevent", "4")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "cap":
        cv2.imwrite(sys.argv[2] if len(sys.argv) > 2 else "screen.png", screencap())
    elif cmd == "tap":
        tap(*sys.argv[2:4])
    elif cmd == "swipe":
        swipe(*sys.argv[2:])
    elif cmd == "back":
        back()
