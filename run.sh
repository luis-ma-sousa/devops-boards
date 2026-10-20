#!/usr/bin/env bash
# Start Boards on macOS or Linux:  ./run.sh   (on a Mac you can also double-click run.command)
set -euo pipefail
cd "$(dirname "$0")"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    path="$(command -v "$candidate" 2>/dev/null)" || continue
    # Apple's /usr/bin/python3 is too old and may pop up an installer dialog: skip it.
    if [ "$(uname)" = "Darwin" ] && [ "$path" = "/usr/bin/python3" ]; then continue; fi
    # Ask for an answer instead of trusting the exit code (a broken file can "succeed" silently).
    if [ "$("$path" -c 'import sys; print("ok" if sys.version_info >= (3, 11) else "old")' 2>/dev/null)" = "ok" ]; then
      echo "$path"
      return 0
    fi
  done
  return 1
}

if PYTHON="$(find_python)"; then
  exec "$PYTHON" launch.py "$@"
fi

UV="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; fi
if [ -z "$UV" ]; then
  echo "Python 3.11 or newer was not found on this computer."
  echo "Boards can set it up for you with uv (https://astral.sh/uv, no admin rights needed)."
  answer="y"
  if [ -t 0 ]; then read -r -p "Set it up now? [Y/n] " answer; fi
  case "${answer:-y}" in
    [nN]*) echo "Install Python 3.12 from https://www.python.org/downloads/ and run this again."; exit 1 ;;
  esac
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV="$HOME/.local/bin/uv"
fi
exec "$UV" run --python 3.12 --no-project launch.py "$@"
