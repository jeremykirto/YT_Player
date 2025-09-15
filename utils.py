# utils.py
import sys
from pathlib import Path

def shutil_which(cmd: str) -> str | None:
    try:
        from shutil import which
        return which(cmd)
    except Exception:
        return None

def locate_ffmpeg_exe() -> str | None:
    exe_name = "ffmpeg.exe" if sys.platform.startswith('win') else "ffmpeg"
    path = shutil_which(exe_name)
    if path:
        return path
    candidate = Path.cwd() / exe_name
    if candidate.exists():
        return str(candidate)
    return None
