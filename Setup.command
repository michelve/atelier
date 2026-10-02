#!/bin/bash
# Atelier setup on macOS: double-click it in Finder, or run ./Setup.command in Terminal.
# Installs Homebrew (it brings the Xcode Command Line Tools) and PowerShell 7 if they're missing, then opens the
# setup screen (setup/install.ps1). Safe to run again: finished steps are skipped. Arguments pass through
# (./Setup.command -Status, -All, -Step 5, -Engine ~/AtelierEngine).
cd "$(dirname "$0")" || exit 1
pause() { read -r -p "Press Return to close. " _; }

translated="$(sysctl -n sysctl.proc_translated 2>/dev/null)"
if [ "$(uname -m)" != "arm64" ] || [ "$translated" = "1" ]; then
  echo "Atelier needs Apple Silicon and a native (arm64) Terminal; this one runs as $(uname -m)."
  echo "In Finder, Get Info on Terminal, untick \"Open using Rosetta\", then run Setup.command again."
  pause; exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  if [ ! -x /opt/homebrew/bin/brew ]; then
    echo "Homebrew is required - installing it (it asks for your password once)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
      echo "Homebrew install failed; see https://brew.sh and run Setup.command again."; pause; exit 1; }
  fi
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
# New terminals find Homebrew's tools too (what Homebrew's installer asks you to add by hand).
if ! grep -qs 'brew shellenv' "$HOME/.zprofile"; then
  printf '\neval "$(/opt/homebrew/bin/brew shellenv)"\n' >> "$HOME/.zprofile"
fi

if ! command -v pwsh >/dev/null 2>&1; then
  echo "PowerShell 7 is required - installing it with Homebrew..."
  brew install powershell || { echo "Could not install PowerShell 7."; pause; exit 1; }
fi

# caffeinate keeps the Mac awake while packages and models download.
caffeinate -i pwsh -NoProfile -File "./setup/install.ps1" "$@"
status=$?
[ "$status" -ne 0 ] && pause
exit "$status"
