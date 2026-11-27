"""CLI entry point for the iPhone DeX Windows Client."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure sibling modules under src/ are importable when invoked directly.
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from protocol import Codec, DEFAULT_PORT  # noqa: E402
from viewer import DexViewerApp  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="iPhone DeX for Windows Client (Phase 1 PoC)")
    parser.add_argument("--mode", choices=["tcp", "usb"], default="tcp", help="Transport mode (default: tcp)")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP for TCP mode (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"TCP/USB port (default: {DEFAULT_PORT})")
    parser.add_argument("--codec", choices=["jpeg", "h264"], default="jpeg", help="Preferred stream codec")
    parser.add_argument("--fps", type=int, default=30, help="Target frame rate (1-60)")
    parser.add_argument("--auto-jit", action="store_true", help="Attempt pymobiledevice3 JIT activation in USB mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    codec = Codec.H264_ANNEXB if args.codec == "h264" else Codec.JPEG
    app = DexViewerApp(
        mode=args.mode,
        host=args.host,
        port=args.port,
        codec=codec,
        fps=max(1, min(60, args.fps)),
        auto_jit=args.auto_jit,
    )
    app.start()


if __name__ == "__main__":
    main()
