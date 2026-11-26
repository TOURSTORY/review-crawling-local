"""TOURSTORY Review Crawler v2.0 – 실행 파일 (START.cmd 가 이 파일을 실행)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
REQUIRED = ("pandas", "openpyxl", "selenium")


def _missing():
    return [m for m in REQUIRED if importlib.util.find_spec(m) is None]


def main():
    import tkinter as tk
    from tkinter import messagebox

    missing = _missing()
    if missing:
        root = tk.Tk()
        root.withdraw()
        if messagebox.askyesno("패키지 설치", "필요한 Python 패키지가 없습니다: " + ", ".join(missing)
                               + "\n\n지금 설치할까요? (1~2분)"):
            proc = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(APP_DIR / "requirements.txt")],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                messagebox.showerror("설치 실패", (proc.stderr or proc.stdout)[-1500:])
                return
        else:
            return
        root.destroy()

    try:
        from ui.app import App
        App().run()
    except Exception:
        tb = traceback.format_exc()
        (APP_DIR / "error.log").write_text(tb, encoding="utf-8")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("실행 오류", tb[-1500:] + f"\n\n{APP_DIR / 'error.log'}")


if __name__ == "__main__":
    main()
