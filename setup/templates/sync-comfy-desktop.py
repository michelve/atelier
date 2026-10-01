"""Keep Comfy Desktop's record of the tracked portable install (<engine>\\ComfyUI) in step with the real version.

Desktop only reads the version it stored, so after an out-of-app update (update-tools.ps1) it keeps offering an
"Update" that would replace the portable package. Run after every ComfyUI update; no-op when Desktop isn't set up.
"""
import json
import os
import subprocess
from pathlib import Path


def saved_env(name: str) -> str | None:
    """Process env first; else the user-level value saved in the registry (a terminal opened before it was set)."""
    if os.environ.get(name):
        return os.environ[name]
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return None

# Engine folder: ATELIER_ENGINE, else <atelier repo>\engine (this file is <repo>\setup\templates\...).
ENGINE = Path(saved_env("ATELIER_ENGINE") or Path(__file__).resolve().parents[2] / "engine")
REPO = ENGINE / "ComfyUI" / "ComfyUI"
RECORDS = Path.home() / "AppData" / "Roaming" / "Comfy Desktop" / "installations.json"

if RECORDS.exists():
    git = lambda *a: subprocess.check_output(["git", "-C", str(REPO), *a], text=True).strip()  # noqa: E731
    tag, commit = git("describe", "--tags", "--abbrev=0"), git("rev-parse", "HEAD")
    ahead = int(git("rev-list", "--count", f"{tag}..HEAD"))
    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    for r in records:
        if r.get("sourceId") == "portable" and str(r.get("installPath", "")).lower() == str(REPO.parent).lower():
            r.update(version=tag, comfyVersionTag=tag, updateInfoByChannel={"stable": {"installedTag": tag}},
                     comfyVersion={"commit": commit, "baseTag": tag, "commitsAhead": ahead, "baseTagVerified": True})
            print(f"Comfy Desktop record -> {tag} ({commit[:8]}, +{ahead})")
    RECORDS.write_text(json.dumps(records, indent=2), encoding="utf-8")
