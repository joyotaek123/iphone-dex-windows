"""Local Mock iOS Host Simulator for Phase 1 Windows testing (implements PROTOCOL.md)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SRC = REPO_ROOT / "windows-client" / "src"
if str(CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(CLIENT_SRC))

from protocol import (  # noqa: E402
    Codec,
    DEFAULT_PORT,
    MsgType,
    PacketStreamReader,
    ProtocolError,
    pack_hello_ack,
    pack_pong,
    pack_video_frame,
    unpack_hello,
    unpack_key_event,
    unpack_mouse_button,
    unpack_mouse_move,
    unpack_mouse_scroll,
    unpack_ping_pong,
)

CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
TASKBAR_HEIGHT = 64

ACCENT_COLORS = [
    (46, 133, 250),
    (20, 184, 143),
    (232, 107, 61),
    (158, 92, 245),
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "consola.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class DesktopState:
    win_x: int = 420
    win_y: int = 180
    win_w: int = 1080
    win_h: int = 580
    title_h: int = 56
    button_clicks: int = 0
    total_remote_clicks: int = 0
    accent_index: int = 0
    typed_text: str = ""
    cursor_x: int = 960
    cursor_y: int = 540
    dragging: bool = False
    drag_offset_x: int = 0
    drag_offset_y: int = 0
    ripple_until: float = 0.0
    ripple_x: int = 960
    ripple_y: int = 540
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def increment_btn_rect(self) -> tuple[int, int, int, int]:
        return (self.win_x + 36, self.win_y + 274, self.win_x + 326, self.win_y + 346)

    @property
    def color_btn_rect(self) -> tuple[int, int, int, int]:
        return (self.win_x + 350, self.win_y + 274, self.win_x + 640, self.win_y + 346)

    def _norm_to_px(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        x = int(max(0.0, min(1.0, norm_x)) * CANVAS_WIDTH)
        y = int(max(0.0, min(1.0, norm_y)) * CANVAS_HEIGHT)
        return x, y

    def handle_mouse_move(self, norm_x: float, norm_y: float) -> None:
        with self.lock:
            px, py = self._norm_to_px(norm_x, norm_y)
            self.cursor_x = px
            self.cursor_y = py
            if self.dragging:
                new_x = max(0, min(CANVAS_WIDTH - self.win_w, px - self.drag_offset_x))
                new_y = max(0, min(CANVAS_HEIGHT - TASKBAR_HEIGHT - self.win_h, py - self.drag_offset_y))
                self.win_x = new_x
                self.win_y = new_y

    def handle_mouse_button(self, norm_x: float, norm_y: float, button: int, action: int) -> str:
        with self.lock:
            px, py = self._norm_to_px(norm_x, norm_y)
            self.cursor_x = px
            self.cursor_y = py
            if action == 1:  # Down
                self.total_remote_clicks += 1
                self.ripple_x = px
                self.ripple_y = py
                self.ripple_until = time.monotonic() + 0.25

                # Titlebar hit-test
                if (
                    self.win_x <= px <= self.win_x + self.win_w
                    and self.win_y <= py <= self.win_y + self.title_h
                ):
                    self.dragging = True
                    self.drag_offset_x = px - self.win_x
                    self.drag_offset_y = py - self.win_y
                    return f"drag_start({px},{py})"

                ix1, iy1, ix2, iy2 = self.increment_btn_rect
                if ix1 <= px <= ix2 and iy1 <= py <= iy2:
                    self.button_clicks += 1
                    return f"increment_button(clicks={self.button_clicks})"

                cx1, cy1, cx2, cy2 = self.color_btn_rect
                if cx1 <= px <= cx2 and cy1 <= py <= cy2:
                    self.accent_index = (self.accent_index + 1) % len(ACCENT_COLORS)
                    return f"color_button(idx={self.accent_index})"

                return f"desktop_click({px},{py})"
            else:
                self.dragging = False
                return f"mouse_up({px},{py})"

    def handle_key(self, key_code: int, action: int, unicode_char: int) -> None:
        if action != 1:
            return
        with self.lock:
            if key_code == 8 or unicode_char == 8:
                self.typed_text = self.typed_text[:-1]
            elif key_code == 13 or unicode_char == 13:
                self.typed_text += "\n"
            elif unicode_char >= 32:
                self.typed_text += chr(unicode_char)
                self.typed_text = self.typed_text[-140:]


class DesktopRenderer:
    def __init__(self) -> None:
        self._font_title = _load_font(22)
        self._font_body = _load_font(20)
        self._font_counter = _load_font(42)
        self._font_btn = _load_font(24)
        self._font_mono = _load_font(20)

        # Pre-render static wallpaper + grid for fast 30 FPS compositing.
        base = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), (15, 25, 45))
        draw = ImageDraw.Draw(base)
        for y in range(0, CANVAS_HEIGHT, 60):
            draw.line([(0, y), (CANVAS_WIDTH, y)], fill=(22, 36, 62), width=1)
        for x in range(0, CANVAS_WIDTH, 60):
            draw.line([(x, 0), (x, CANVAS_HEIGHT)], fill=(22, 36, 62), width=1)
        draw.text(
            (48, 34),
            "iPhone DeX Desktop (1920x1080) — Local Mock iOS Host",
            font=self._font_title,
            fill=(130, 155, 195),
        )
        self._base_wallpaper = base

    def render_jpeg(self, state: DesktopState, quality: int = 72) -> bytes:
        with state.lock:
            wx, wy, ww, wh = state.win_x, state.win_y, state.win_w, state.win_h
            th = state.title_h
            accent = ACCENT_COLORS[state.accent_index]
            clicks = state.button_clicks
            total_clicks = state.total_remote_clicks
            typed = state.typed_text
            cx, cy = state.cursor_x, state.cursor_y
            ix1, iy1, ix2, iy2 = state.increment_btn_rect
            cx1, cy1, cx2, cy2 = state.color_btn_rect
            show_ripple = time.monotonic() < state.ripple_until
            rx, ry = state.ripple_x, state.ripple_y

        img = self._base_wallpaper.copy()
        draw = ImageDraw.Draw(img)

        # Window drop shadow + body
        draw.rounded_rectangle([wx + 6, wy + 10, wx + ww + 6, wy + wh + 10], radius=16, fill=(7, 11, 20))
        draw.rounded_rectangle(
            [wx, wy, wx + ww, wy + wh],
            radius=16,
            fill=(28, 33, 46),
            outline=(75, 90, 115),
            width=2,
        )

        # Window titlebar
        draw.rounded_rectangle([wx, wy, wx + ww, wy + th], radius=16, fill=accent)
        draw.rectangle([wx, wy + th - 16, wx + ww, wy + th], fill=accent)
        for idx, dot_color in enumerate([(239, 68, 68), (245, 158, 11), (34, 197, 94)]):
            dx = wx + 22 + idx * 24
            dy = wy + 21
            draw.ellipse([dx, dy, dx + 14, dy + 14], fill=dot_color)
        draw.text((wx + 106, wy + 14), "PoC App — DeX Counter & Notes", font=self._font_title, fill=(255, 255, 255))

        # Body & counter
        draw.text(
            (wx + 36, wy + 84),
            "Drag titlebar from Windows mouse, click buttons below, or type on your PC keyboard.",
            font=self._font_body,
            fill=(205, 213, 225),
        )
        draw.text((wx + 36, wy + 165), f"Button Clicks: {clicks}", font=self._font_counter, fill=(255, 255, 255))

        # Interactive buttons
        draw.rounded_rectangle([ix1, iy1, ix2, iy2], radius=12, fill=accent)
        draw.text((ix1 + 70, iy1 + 20), "+1 Counter", font=self._font_btn, fill=(255, 255, 255))

        draw.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=(60, 68, 84))
        draw.text((cx1 + 65, cy1 + 20), "Switch Color", font=self._font_btn, fill=(255, 255, 255))

        # Keyboard output box
        draw.rounded_rectangle(
            [wx + 36, wy + 382, wx + ww - 36, wy + 522],
            radius=12,
            fill=(15, 20, 30),
            outline=(55, 68, 92),
            width=1,
        )
        display_text = typed if typed else "(waiting for keyboard input...)"
        draw.text((wx + 54, wy + 402), f"Typed from PC: {display_text}", font=self._font_mono, fill=(142, 235, 173))

        # Taskbar
        ty = CANVAS_HEIGHT - TASKBAR_HEIGHT
        draw.rectangle([0, ty, CANVAS_WIDTH, CANVAS_HEIGHT], fill=(10, 15, 26))
        draw.line([(0, ty), (CANVAS_WIDTH, ty)], fill=(45, 58, 82), width=1)
        draw.rounded_rectangle([24, ty + 12, 194, ty + 52], radius=10, fill=(46, 133, 250))
        draw.text((44, ty + 19), "iPhone DeX", font=self._font_body, fill=(255, 255, 255))
        draw.text(
            (224, ty + 20),
            f"Remote Clicks: {total_clicks}  |  Cursor: ({cx}, {cy})",
            font=self._font_mono,
            fill=(210, 220, 235),
        )
        clock_str = time.strftime("%H:%M:%S")
        draw.text((CANVAS_WIDTH - 140, ty + 19), clock_str, font=self._font_title, fill=(255, 255, 255))

        # Click ripple & cursor
        if show_ripple:
            draw.ellipse([rx - 26, ry - 26, rx + 26, ry + 26], outline=(56, 189, 248), width=4)
        draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 255, 255), outline=(0, 0, 0), width=3)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


class MockIosHostServer:
    """TCP server simulating /ios-host over localhost for Windows PoC verification."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, verbose: bool = True) -> None:
        self.host = host
        self.requested_port = port
        self.verbose = verbose
        self.state = DesktopState()
        self.renderer = DesktopRenderer()

        self._server_sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._accept_thread: Optional[threading.Thread] = None
        self.port: int = port

    def start(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.requested_port))
        sock.listen(4)
        sock.settimeout(0.5)
        self._server_sock = sock
        self.port = sock.getsockname()[1]

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        if self.verbose:
            print(f"[Mock iOS Host] Listening on {self.host}:{self.port}")
        return self.port

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)

    def _accept_loop(self) -> None:
        assert self._server_sock is not None
        while not self._stop_event.is_set():
            try:
                client, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            if self.verbose:
                print(f"[Mock iOS Host] Client connected from {addr}")
            self._serve_client(client)

    def _serve_client(self, client: socket.socket) -> None:
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.settimeout(0.5)
        reader = PacketStreamReader()
        send_lock = threading.Lock()
        client_done = threading.Event()
        negotiated_fps = 30

        # Wait for HELLO
        hello_done = False
        while not self._stop_event.is_set() and not hello_done:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                client.close()
                return
            if not chunk:
                client.close()
                return
            try:
                for msg_type, _flags, payload in reader.feed(chunk):
                    if msg_type == MsgType.HELLO:
                        hello = unpack_hello(payload)
                        negotiated_fps = max(1, min(60, hello.target_fps))
                        ack_pkt = pack_hello_ack(
                            canvas_width=CANVAS_WIDTH,
                            canvas_height=CANVAS_HEIGHT,
                            actual_fps=negotiated_fps,
                            active_codec=Codec.JPEG,
                            status=0,
                        )
                        with send_lock:
                            client.sendall(ack_pkt)
                        hello_done = True
                        break
            except ProtocolError:
                client.close()
                return

        def stream_frames() -> None:
            frame_seq = 0
            interval = 1.0 / negotiated_fps
            while not self._stop_event.is_set() and not client_done.is_set():
                t0 = time.monotonic()
                jpeg_bytes = self.renderer.render_jpeg(self.state, quality=72)
                ts_us = time.monotonic_ns() // 1000
                pkt = pack_video_frame(
                    frame_seq=frame_seq,
                    timestamp_us=ts_us,
                    codec=Codec.JPEG,
                    width=CANVAS_WIDTH,
                    height=CANVAS_HEIGHT,
                    frame_data=jpeg_bytes,
                    is_keyframe=True,
                )
                frame_seq += 1
                try:
                    with send_lock:
                        client.sendall(pkt)
                except OSError:
                    client_done.set()
                    break
                elapsed = time.monotonic() - t0
                if elapsed < interval:
                    time.sleep(interval - elapsed)

        streamer = threading.Thread(target=stream_frames, daemon=True)
        streamer.start()

        try:
            while not self._stop_event.is_set() and not client_done.is_set():
                try:
                    chunk = client.recv(8192)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                for msg_type, _flags, payload in reader.feed(chunk):
                    if msg_type == MsgType.MOUSE_MOVE:
                        mv = unpack_mouse_move(payload)
                        self.state.handle_mouse_move(mv.norm_x, mv.norm_y)
                    elif msg_type == MsgType.MOUSE_BUTTON:
                        btn = unpack_mouse_button(payload)
                        event_desc = self.state.handle_mouse_button(
                            btn.norm_x, btn.norm_y, btn.button, btn.action
                        )
                        if self.verbose and btn.action == 1:
                            print(f"[Mock iOS Host] Click -> {event_desc}")
                    elif msg_type == MsgType.MOUSE_SCROLL:
                        _scroll = unpack_mouse_scroll(payload)
                    elif msg_type == MsgType.KEY_EVENT:
                        key = unpack_key_event(payload)
                        self.state.handle_key(key.key_code, key.action, key.unicode_char)
                        if self.verbose and key.action == 1:
                            print(f"[Mock iOS Host] Key -> code={key.key_code} char={key.unicode_char}")
                    elif msg_type == MsgType.PING:
                        ts = unpack_ping_pong(payload)
                        with send_lock:
                            client.sendall(pack_pong(ts))
        except (OSError, ProtocolError):
            pass
        finally:
            client_done.set()
            streamer.join(timeout=1.0)
            try:
                client.close()
            except OSError:
                pass
            if self.verbose:
                print("[Mock iOS Host] Client disconnected")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock iOS Host Simulator (Phase 1 PoC)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = MockIosHostServer(host=args.host, port=args.port, verbose=True)
    server.start()
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping Mock iOS Host...")
        server.stop()


if __name__ == "__main__":
    main()
