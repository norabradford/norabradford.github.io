#!/usr/bin/env python3
"""Build and preview the website locally."""

from __future__ import annotations

import argparse
import http.server
import subprocess
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
LOCAL_HOST = "127.0.0.1"


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be a number") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview the built website.")
    parser.add_argument("port", nargs="?", default=8000, type=port_number)
    parser.add_argument(
        "--host",
        default=LOCAL_HOST,
        help="address to listen on (use 0.0.0.0 to test on another device)",
    )
    return parser.parse_args(arguments)


def build_site() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)


def create_server(port: int, host: str = LOCAL_HOST) -> http.server.ThreadingHTTPServer:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    return http.server.ThreadingHTTPServer((host, port), handler)


def main(arguments: Sequence[str] | None = None) -> None:
    options = parse_args(arguments)
    build_site()
    with create_server(options.port, options.host) as server:
        print(f"Preview: http://{options.host}:{options.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nPreview stopped.")


if __name__ == "__main__":
    main()
