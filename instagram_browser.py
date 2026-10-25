#!/usr/bin/env python3
"""Manual Instagram browser login and a standalone download check."""

import argparse
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from downloaders.instagram_browser import (
    BrowserDownloadError, PAUSED_FILE, READY_FILE, download_with_browser,
    has_session, launch_context, page_problem, profile_lock, profile_path,
)


@contextmanager
def remote_desktop(port):
    """Expose the temporary desktop only on container loopback for port-forward."""
    executables = ["Xvfb", "x11vnc", "websockify"]
    missing = [name for name in executables if not shutil.which(name)]
    web = Path("/usr/share/novnc")
    if missing or not (web / "vnc.html").is_file():
        raise RuntimeError("Для віддаленого входу потрібні xvfb, x11vnc, novnc і websockify. Оновіть Docker-образ бота.")
    processes = []
    previous_display = os.environ.get("DISPLAY")
    read_fd, write_fd = os.pipe()
    try:
        processes.append(subprocess.Popen([
            "Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x900x24", "-nolisten", "tcp",
        ], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        os.close(write_fd)
        write_fd = None
        if not select.select([read_fd], [], [], 10)[0]:
            raise RuntimeError("Не вдалося запустити віртуальний екран для входу.")
        display = ":" + os.read(read_fd, 32).decode().strip()
        if display == ":":
            raise RuntimeError("Віртуальний екран завершив роботу.")
        os.environ["DISPLAY"] = display
        # Ask the OS for a free VNC port. The web endpoint itself is fixed by --port.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            vnc_port = sock.getsockname()[1]
        processes.append(subprocess.Popen([
            "x11vnc", "-display", display, "-listen", "127.0.0.1", "-rfbport", str(vnc_port),
            "-nopw", "-forever", "-shared", "-noxdamage", "-quiet",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        processes.append(subprocess.Popen([
            "websockify", f"--web={web}", f"127.0.0.1:{port}", f"127.0.0.1:{vnc_port}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        deadline = time.monotonic() + 10
        while True:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("Не вдалося запустити noVNC. Перевірте, чи порт не зайнятий.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5), socket.create_connection(("127.0.0.1", vnc_port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("noVNC не запустився вчасно.") from None
                time.sleep(0.1)
        print(f"Відкрийте http://127.0.0.1:{port}/vnc.html?autoconnect=1&resize=scale", flush=True)
        print("Для Kubernetes спочатку запустіть kubectl port-forward у другому терміналі.", flush=True)
        yield
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if previous_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = previous_display


def login(remote=False, port=6080):
    profile = profile_path()
    with profile_lock(profile), remote_desktop(port) if remote else nullcontext(), sync_playwright() as playwright:
        context = launch_context(playwright, profile, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
            while True:
                input("Увійдіть у браузері, пройдіть 2FA/перевірки. Залиште вікно відкритим і натисніть Enter тут: ")
                page = context.pages[-1]
                if has_session(context) and page_problem(page) not in {"challenge", "login"}:
                    break
                print("Вхід ще не завершений. Завершіть перевірки в браузері та повторіть.", flush=True)
            (profile / READY_FILE).touch(mode=0o600)
            (profile / PAUSED_FILE).unlink(missing_ok=True)
        finally:
            context.close()
    print(f"Вхід збережений у {profile}. Бот використовуватиме цей профіль після звичайних спроб.")


def main():
    load_dotenv(Path(__file__).with_name(".env"), override=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, help="Override INSTAGRAM_BROWSER_PROFILE")
    commands = parser.add_subparsers(dest="command", required=True)
    login_parser = commands.add_parser("login", help="Open Chromium for manual login")
    login_parser.add_argument("--remote", action="store_true", help="Open the browser through local noVNC")
    login_parser.add_argument("--port", type=int, default=6080)
    check_parser = commands.add_parser("check", help="Download one post directly through the browser")
    check_parser.add_argument("url")
    check_parser.add_argument("--anonymous", action="store_true", help="Test without touching the saved profile")
    check_parser.add_argument("--output", type=Path, default=Path("downloads"))
    commands.add_parser("status", help="Show the profile path and whether a manual login was saved")
    args = parser.parse_args()
    if args.profile:
        os.environ["INSTAGRAM_BROWSER_PROFILE"] = str(args.profile)
    try:
        if args.command == "login":
            login(args.remote, args.port)
        elif args.command == "status":
            profile = profile_path()
            print(f"Профіль: {profile}")
            print(f"Ручний вхід збережено: {(profile / READY_FILE).is_file()}")
            print(f"Потрібен повторний вхід: {(profile / PAUSED_FILE).exists()}")
            print("Для повної перевірки запустіть check із посиланням на допис.")
        else:
            args.output.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="instagram-browser-check-", dir=args.output))
            try:
                files = download_with_browser(args.url, directory, anonymous=args.anonymous)
                for file in files:
                    print(f"Збережено: {file} ({file.stat().st_size} bytes)")
            except Exception:
                shutil.rmtree(directory)
                raise
    except KeyboardInterrupt:
        print("Вхід або перевірку зупинено.", file=sys.stderr)
        return 130
    except EOFError:
        print("Для ручного входу потрібен інтерактивний термінал. Використайте kubectl exec -it.", file=sys.stderr)
        return 1
    except PlaywrightError:
        print("Не вдалося відкрити або зберегти браузер. Перевірте встановлення Chromium, DISPLAY і доступність профілю.", file=sys.stderr)
        return 1
    except OSError:
        print("Не вдалося запустити потрібну програму або записати профіль/файл. Перевірте встановлення та права доступу.", file=sys.stderr)
        return 1
    except (BrowserDownloadError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
