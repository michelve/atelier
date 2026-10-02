"""What differs between Windows and macOS, in one place: saved settings and keys, shim and venv paths, ComfyUI's
own Python, starting and stopping a background server.

Standard library only, so scripts outside refkit's venv (nanobanana.py) can import it too.
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"
# Atelier's Windows build is NVIDIA-only (the setup's system check requires it); a Mac has no CUDA.
CUDA = WINDOWS
# macOS: the setup saves user settings here (KEY=value lines) and sources the file from ~/.zprofile.
ENV_FILE = Path.home() / ".config" / "atelier" / "env"
KEYCHAIN_SERVICE = "atelier"   # macOS login Keychain: service "atelier", account = the variable name
SHIM_DIR = Path.home() / ".local" / "bin"


def _env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip().removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if sep and key and not key.startswith("#"):
            parts = shlex.split(value, comments=True)
            values[key.strip()] = parts[0] if parts else ""
    return values


def saved_env(name: str) -> str | None:
    """Process env first; else the value the setup saved for this user (a terminal opened before it was set):
    the registry on Windows, ~/.config/atelier/env elsewhere."""
    if os.environ.get(name):
        return os.environ[name]
    if WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return _env_file().get(name) or None


def secret(name: str) -> str | None:
    """An API key: like saved_env, plus the macOS login Keychain (where the setup stores keys there)."""
    value = saved_env(name)
    if value or not MACOS:
        return value
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None


def shim(name: str) -> Path:
    """A launcher the setup writes to ~/.local/bin: `name.cmd` on Windows, an executable `name` script elsewhere."""
    return SHIM_DIR / (f"{name}.cmd" if WINDOWS else name)


def venv_bin(venv: Path, name: str) -> Path:
    """An executable inside a virtual env: Scripts\\name.exe on Windows, bin/name elsewhere."""
    return Path(venv) / "Scripts" / f"{name}.exe" if WINDOWS else Path(venv) / "bin" / name


def engine_python(comfy_dir: Path) -> Path:
    """ComfyUI's own Python: the portable build's embedded one on Windows, the engine's venv on macOS."""
    return Path(comfy_dir) / "python_embeded" / "python.exe" if WINDOWS else Path(comfy_dir) / "venv" / "bin" / "python"


def torch_device() -> str:
    """The torch device for refkit's own models: cuda, else Apple's mps, else cpu."""
    import torch
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    return "mps" if mps is not None and mps.is_available() else "cpu"


def empty_cache(device: str) -> None:
    import torch
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


def gpu_line() -> str | None:
    """One `refkit status` line about the GPU: VRAM use on NVIDIA, chip + unified memory on a Mac."""
    try:
        if WINDOWS:
            smi = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
            used, total, util = (v.strip() for v in smi.split(","))
            return f"GPU {used}/{total} MiB used, {util}% busy"
        if MACOS:
            def sysctl(key: str) -> str:
                return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=10).stdout.strip()
            return f"GPU {sysctl('machdep.cpu.brand_string')}, {int(sysctl('hw.memsize')) / 2**30:.0f} GB unified memory"
    except Exception:
        return None
    return None


def background(new_group: bool = True) -> dict:
    """Popen keyword arguments for a server that runs without a console window and survives Ctrl+C in ours."""
    if WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW | (subprocess.CREATE_NEW_PROCESS_GROUP if new_group else 0)
        return {"creationflags": flags}
    return {"start_new_session": new_group}


def listening_pids(port: int) -> set[int]:
    """PIDs listening on 127.0.0.1:<port>."""
    if WINDOWS:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        return {int(m.group(1)) for m in re.finditer(rf"127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)", out)}
    out = subprocess.run(["lsof", "-nP", f"-iTCP@127.0.0.1:{port}", "-sTCP:LISTEN", "-t"],
                         capture_output=True, text=True).stdout
    return {int(p) for p in out.split() if p.isdigit()}


def kill_tree(pid: int) -> None:
    """Stop a process and its children."""
    if sys.platform == "win32":   # (not WINDOWS: type checkers narrow on sys.platform only)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        # Our shim execs Python in a session of its own (start_new_session), so its group is just the server;
        # anything else only gets the process itself, never a shell's whole group.
        group = os.getpgid(pid) == pid
        send = (lambda sig: os.killpg(pid, sig)) if group else (lambda sig: os.kill(pid, sig))
        send(signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.5)
            os.kill(pid, 0)   # raises once it is gone
        send(signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
