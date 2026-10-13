"""Run both local services, including from Project Manager. Ctrl+C stops both."""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == 'nt':
        # The venv Python launcher can create another Python process on Windows.
        # Stop only the process tree created by this supervisor.
        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5173, help='Frontend port assigned by the launcher')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.port == 8000:
        parser.error('--port must be between 1 and 65535 and different from backend port 8000')
    python = ROOT / 'backend/.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    node = shutil.which('node')
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    if not python.exists() or not node or not vite.exists():
        sys.exit('Install backend and frontend dependencies first; see README.md.')
    for port in (8000, args.port):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                sys.exit(f'Port {port} is already in use. Stop the existing service before starting.')
    children = []
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        children.append(subprocess.Popen([str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT / 'backend', creationflags=flags))
        # The launcher probes the frontend. Expose it only after the API is ready.
        deadline = time.monotonic() + 20
        while True:
            if children[0].poll() is not None:
                sys.exit(f'Backend exited before becoming ready (code {children[0].returncode}).')
            try:
                with urlopen('http://127.0.0.1:8000/api/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, OSError):
                pass
            if time.monotonic() >= deadline:
                sys.exit('Backend did not become ready within 20 seconds. See the backend logs above.')
            time.sleep(0.2)
        children.append(subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port', str(args.port), '--strictPort'], cwd=ROOT / 'frontend', creationflags=flags))
        print(f'Field Navigator: http://127.0.0.1:{args.port}  |  API: http://127.0.0.1:8000/docs', flush=True)
        print('Press Ctrl+C to stop both services.', flush=True)
        # Wake periodically without busy polling; propagate early service exits.
        while all(child.poll() is None for child in children):
            try:
                children[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        sys.exit('A service stopped unexpectedly. See the service logs above.')
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            stop_child(child)


if __name__ == '__main__':
    main()
