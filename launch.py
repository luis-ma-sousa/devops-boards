"""Start Boards on any computer (Windows, macOS or Linux).

Creates a private Python environment in .venv on the first run, installs what the app needs,
starts the server and opens the browser. Uses only the standard library, so it runs before
anything is installed.

    python launch.py                 start and open the browser
    python launch.py --port 8600     use another port (the next free one is picked automatically)
    python launch.py --no-browser    do not open the browser (e.g. on a server)
    python launch.py --smoke         start, check the app answers, stop (used by CI)
"""

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

MIN_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = VENV / ".boards-requirements"


def say(message):
    print("[boards] " + message, flush=True)


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_quiet(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def python_works(python):
    check = "import sys; print('ok' if sys.version_info >= %r else 'old')" % (MIN_PYTHON,)
    try:
        result = subprocess.run([str(python), "-c", check], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.stdout.strip() == "ok"


def ensure_venv():
    python = venv_python()
    if python.exists() and python_works(python):
        return python
    if VENV.exists():
        say("Rebuilding the .venv folder (it was broken or used an old Python).")
        shutil.rmtree(VENV)
    say("First run: creating a private Python environment in .venv ...")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    return python


def ensure_requirements(python):
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if MARKER.exists() and MARKER.read_text(encoding="ascii").strip() == wanted:
        return
    if not run_quiet([str(python), "-m", "pip", "--version"]):
        subprocess.check_call([str(python), "-m", "ensurepip", "--upgrade"])
    say("Installing what the app needs (only when requirements.txt changes, about a minute) ...")
    subprocess.check_call([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                           "-r", str(REQUIREMENTS)])
    MARKER.write_text(wanted, encoding="ascii")


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def pick_port(start):
    for port in range(start, start + 50):
        if port_is_free(port):
            return port
    raise SystemExit("No free port found between %d and %d." % (start, start + 49))


def network_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outgoing interface
            address = sock.getsockname()[0]
        return None if address.startswith("127.") else address
    except OSError:
        return None


def wait_until_ready(url, process, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("The app stopped while starting (exit code %s). See the messages above."
                             % process.returncode)
        try:
            with urllib.request.urlopen(url + "/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit("The app did not start within %d seconds." % timeout)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(description="Start Boards.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8501)))
    parser.add_argument("--no-browser", action="store_true", default=bool(os.environ.get("BOARDS_NO_BROWSER")))
    parser.add_argument("--smoke", action="store_true", help="start, check the app answers, then stop")
    args = parser.parse_args()

    if sys.version_info < MIN_PYTHON:
        raise SystemExit("Boards needs Python %d.%d or newer (this is %s). Install it from "
                         "https://www.python.org/downloads/ and run this again."
                         % (MIN_PYTHON + (sys.version.split()[0],)))

    python = ensure_venv()
    ensure_requirements(python)
    port = pick_port(args.port)
    url = "http://localhost:%d" % port

    say("Starting ...")
    process = subprocess.Popen([str(python), "-m", "streamlit", "run", str(ROOT / "app.py"),
                                "--server.port", str(port), "--server.headless", "true",
                                "--browser.gatherUsageStats", "false", "--server.fileWatcherType", "none"],
                               cwd=str(ROOT))
    try:
        wait_until_ready(url, process, timeout=120)
        if args.smoke:
            with urllib.request.urlopen(url, timeout=10) as response:
                assert response.status == 200, response.status
            say("Smoke test passed: the app answered at " + url)
            return 0
        say("Boards is running at " + url)
        address = network_address()
        if address:
            say("People on the same network can open http://%s:%d" % (address, port))
        if not args.no_browser:
            webbrowser.open(url)
        say("Keep this window open while you use the app. Press Ctrl+C to stop it.")
        return process.wait()
    except KeyboardInterrupt:
        say("Stopping ...")
        return 0
    finally:
        stop(process)


if __name__ == "__main__":
    sys.exit(main())
