"""ACEVO Telemetry Coach — web UI + live analysis server."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACEVO Telemetry Coach")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--mode",
        choices=("auto", "demo", "live"),
        default="auto",
        help="auto: live if game is up else demo. demo: always synthetic. live: shared memory only.",
    )
    parser.add_argument("--hz", type=float, default=15.0)
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Legacy console telemetry monitor instead of the web app.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cli:
        from telemetry.live import LiveSharedMemoryClient

        client = LiveSharedMemoryClient()
        client.run_forever(hz=args.hz)
        return 0

    import os

    os.environ["ACEVO_MODE"] = args.mode
    os.environ["TELEMETRY_HZ"] = str(args.hz)

    try:
        import uvicorn
    except ImportError:
        print("Install deps: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    uvicorn.run("server.app:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
