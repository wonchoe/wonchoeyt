#!/usr/bin/env python3
"""Lightweight yt-dlp debug helper."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yt_dlp


def _run(cmd):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return out
    except Exception as e:
        return f"{cmd[0]} unavailable ({e})"


def _print_env():
    print("=== Environment ===")
    print(f"Python: {sys.version.split()[0]}")
    print(f"yt-dlp: {yt_dlp.version.__version__}")
    print(f"Node: {_run(['node', '-v'])}")
    print(f"ffmpeg: {_run(['ffmpeg', '-version']).splitlines()[0] if 'ffmpeg' in _run(['which','ffmpeg']) else 'ffmpeg not found'}")
    print(f"PATH: {os.environ.get('PATH','')}")


def _check_cookies(path: str):
    if not path:
        return
    p = Path(path)
    if not p.exists():
        print(f"Cookies: NOT FOUND at {p}")
        return
    size = p.stat().st_size
    print(f"Cookies: {p} ({size} bytes)")
    try:
        content = p.read_text(errors="ignore")
        critical = ['__Secure-3PSID', '__Secure-1PSID', 'SAPISID', 'SSID']
        found = [c for c in critical if c in content]
        print(f"Cookies critical: {', '.join(found) if found else 'none'}")
    except Exception as e:
        print(f"Cookies read error: {e}")


class _Logger:
    def debug(self, msg):
        print(msg)

    def warning(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--cookies", default="/var/www/ytdl-cookies.txt")
    parser.add_argument("--mode", choices=["audio", "video"], default="audio")
    parser.add_argument("--quality", default=None)
    parser.add_argument("--download", action="store_true", help="Actually download media")
    parser.add_argument("--dump-json", action="store_true")
    parser.add_argument(
        "--js-runtime",
        choices=["node", "deno", "bun", "quickjs"],
        default=None,
        help="Use a JS runtime for YouTube extraction",
    )
    parser.add_argument(
        "--player-client",
        default=None,
        help="YouTube player client override (e.g. android, tv, web, web_safari)",
    )
    args = parser.parse_args()

    _print_env()
    _check_cookies(args.cookies)

    opts = {
        "quiet": False,
        "no_warnings": False,
        "nocheckcertificate": True,
        "noplaylist": True,
        "verbose": True,
        "logger": _Logger(),
        "progress_hooks": [lambda d: print(f"HOOK: {d.get('status')} {d.get('downloaded_bytes',0)}/{d.get('total_bytes') or d.get('total_bytes_estimate')}")],
    }

    if args.cookies and Path(args.cookies).exists():
        opts["cookiefile"] = args.cookies

    if args.mode == "audio":
        opts["format"] = "bestaudio/bestaudio*/best/best*"
        if args.download:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
    else:
        if args.quality:
            opts["format"] = (
                f"bestvideo*[height<={args.quality}]+bestaudio*/"
                f"bestvideo[height<={args.quality}]+bestaudio/"
                f"best*[height<={args.quality}]/"
                f"best[height<={args.quality}]/"
                "best*/best"
            )
        else:
            opts["format"] = "bestvideo*+bestaudio*/bestvideo+bestaudio/best*/best"

    if not args.download:
        opts["skip_download"] = True
        opts["listformats"] = True

    if args.js_runtime:
        opts["js_runtimes"] = {args.js_runtime: {}}

    if args.player_client:
        opts.setdefault("extractor_args", {})
        opts["extractor_args"].setdefault("youtube", {})
        opts["extractor_args"]["youtube"]["player_client"] = [args.player_client]

    if args.dump_json:
        opts["dump_single_json"] = True

    print("=== yt-dlp run ===")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(args.url, download=args.download)


if __name__ == "__main__":
    main()
