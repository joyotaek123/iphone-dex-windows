"""Tkinter 16:9 desktop viewer and input forwarder for iPhone DeX."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Optional

from PIL import Image, ImageTk

from decoder import FrameDecoder
from protocol import Codec, MouseButton, VideoFrameMessage
from transport import DexTransport, UsbDeviceManager


class DexViewerApp:
    def __init__(
        self,
        mode: str,
        host: str,
        port: int,
        codec: Codec,
        fps: int,
        auto_jit: bool = False,
    ) -> None:
        self.mode = mode
        self.host = host
        self.port = port
        self.codec = codec
        self.fps = fps
        self.auto_jit = auto_jit

        self.root = tk.Tk()
        self.root.title("iPhone DeX for Windows — Phase 1 PoC")
        self.root.geometry("1280x768")
        self.root.configure(bg="#0B0F17")

        self._status_var = tk.StringVar(value="Connecting...")
        self._build_ui()

        self._frame_lock = threading.Lock()
        self._latest_image: Optional[Image.Image] = None
        self._photo_image: Optional[ImageTk.PhotoImage] = None
        self._canvas_image_id: Optional[int] = None

        self._video_rect: tuple[int, int, int, int] = (0, 0, 1280, 720)
        self._stream_size: tuple[int, int] = (1920, 1080)
        self._fps_counter = 0
        self._fps_window_start = time.monotonic()
        self._measured_fps = 0.0
        self._rtt_ms = 0.0
        self._last_norm_xy: tuple[float, float] = (0.5, 0.5)
        self._last_move_sent = 0.0
        self._disconnected_msg: Optional[str] = None

        self.decoder = FrameDecoder(on_image=self._on_decoded_image)
        self.transport = DexTransport(
            on_frame=self._on_video_packet,
            on_rtt_ms=self._on_rtt_update,
            on_disconnect=self._on_transport_disconnect,
        )

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        status_bar = tk.Frame(self.root, bg="#111827", height=36)
        status_bar.pack(side=tk.TOP, fill=tk.X)

        label = tk.Label(
            status_bar,
            textvariable=self._status_var,
            fg="#E5E7EB",
            bg="#111827",
            font=("Consolas", 10, "bold"),
            anchor="w",
            padx=12,
            pady=6,
        )
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.canvas = tk.Canvas(self.root, bg="#05080F", highlightthickness=0, cursor="arrow")
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", lambda e: self._on_mouse_button(e, MouseButton.LEFT, True))
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._on_mouse_button(e, MouseButton.LEFT, False))
        self.canvas.bind("<ButtonPress-3>", lambda e: self._on_mouse_button(e, MouseButton.RIGHT, True))
        self.canvas.bind("<ButtonRelease-3>", lambda e: self._on_mouse_button(e, MouseButton.RIGHT, False))
        self.canvas.bind("<ButtonPress-2>", lambda e: self._on_mouse_button(e, MouseButton.MIDDLE, True))
        self.canvas.bind("<ButtonRelease-2>", lambda e: self._on_mouse_button(e, MouseButton.MIDDLE, False))
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        self.root.bind("<KeyPress>", lambda e: self._on_key(e, True))
        self.root.bind("<KeyRelease>", lambda e: self._on_key(e, False))

    def start(self) -> None:
        try:
            if self.mode == "usb":
                if self.auto_jit:
                    _ok, jit_note = UsbDeviceManager.try_enable_jit()
                    self._status_var.set(f"USB Connecting... ({jit_note})")
                ack = self.transport.connect_usb(
                    port=self.port,
                    preferred_codec=self.codec,
                    target_fps=self.fps,
                )
            else:
                ack = self.transport.connect_tcp(
                    host=self.host,
                    port=self.port,
                    preferred_codec=self.codec,
                    target_fps=self.fps,
                )
            self._stream_size = (ack.canvas_width, ack.canvas_height)
            self._update_status_bar()
        except Exception as exc:
            messagebox.showerror("Connection Failed", str(exc))
            self._on_close()
            return

        self.root.after(16, self._ui_tick)
        self.root.mainloop()

    def _on_video_packet(self, frame: VideoFrameMessage) -> None:
        self.decoder.decode(frame)

    def _on_decoded_image(self, image: Image.Image, _meta: VideoFrameMessage) -> None:
        with self._frame_lock:
            self._latest_image = image
            self._fps_counter += 1

    def _on_rtt_update(self, rtt_ms: float) -> None:
        self._rtt_ms = rtt_ms

    def _on_transport_disconnect(self, reason: str) -> None:
        self._disconnected_msg = reason

    def _ui_tick(self) -> None:
        if self._disconnected_msg is not None:
            self._status_var.set(f"DISCONNECTED: {self._disconnected_msg}")
            return

        now = time.monotonic()
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._measured_fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_window_start = now
            self._update_status_bar()

        img_to_draw: Optional[Image.Image] = None
        with self._frame_lock:
            if self._latest_image is not None:
                img_to_draw = self._latest_image
                self._latest_image = None

        if img_to_draw is not None:
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            src_w, src_h = img_to_draw.size
            scale = min(cw / src_w, ch / src_h)
            disp_w = max(1, int(src_w * scale))
            disp_h = max(1, int(src_h * scale))
            vx = (cw - disp_w) // 2
            vy = (ch - disp_h) // 2
            self._video_rect = (vx, vy, disp_w, disp_h)

            resized = img_to_draw.resize((disp_w, disp_h), Image.Resampling.BILINEAR)
            self._photo_image = ImageTk.PhotoImage(resized)
            if self._canvas_image_id is None:
                self._canvas_image_id = self.canvas.create_image(vx, vy, anchor=tk.NW, image=self._photo_image)
            else:
                self.canvas.coords(self._canvas_image_id, vx, vy)
                self.canvas.itemconfigure(self._canvas_image_id, image=self._photo_image)

        self.root.after(16, self._ui_tick)

    def _update_status_bar(self) -> None:
        endpoint = "USB usbmuxd" if self.mode == "usb" else f"TCP {self.host}:{self.port}"
        codec_name = "H264" if self.codec == Codec.H264_ANNEXB else "JPEG"
        nx, ny = self._last_norm_xy
        px = int(nx * self._stream_size[0])
        py = int(ny * self._stream_size[1])
        self._status_var.set(
            f"[{endpoint}] {self._stream_size[0]}x{self._stream_size[1]} [{codec_name}]  |  "
            f"FPS: {self._measured_fps:.1f}  |  RTT: {self._rtt_ms:.1f} ms  |  Cursor: ({px}, {py})"
        )

    def _canvas_to_norm(self, x: int, y: int) -> tuple[float, float]:
        vx, vy, vw, vh = self._video_rect
        nx = max(0.0, min(1.0, (x - vx) / max(1, vw)))
        ny = max(0.0, min(1.0, (y - vy) / max(1, vh)))
        return nx, ny

    def _on_mouse_move(self, event: tk.Event) -> None:
        now = time.monotonic()
        if now - self._last_move_sent < 0.016:  # cap ~60Hz mouse move events
            return
        self._last_move_sent = now
        nx, ny = self._canvas_to_norm(event.x, event.y)
        self._last_norm_xy = (nx, ny)
        self.transport.send_mouse_move(nx, ny)

    def _on_mouse_button(self, event: tk.Event, button: MouseButton, is_down: bool) -> None:
        self.canvas.focus_set()
        nx, ny = self._canvas_to_norm(event.x, event.y)
        self._last_norm_xy = (nx, ny)
        self.transport.send_mouse_button(nx, ny, int(button), is_down)
        self._update_status_bar()

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        nx, ny = self._canvas_to_norm(event.x, event.y)
        delta_y = float(event.delta) / 120.0
        self.transport.send_mouse_scroll(nx, ny, 0.0, delta_y)

    def _on_key(self, event: tk.Event, is_down: bool) -> None:
        modifiers = 0
        state = int(getattr(event, "state", 0))
        if state & 0x0001:
            modifiers |= 1  # Shift
        if state & 0x0004:
            modifiers |= 2  # Ctrl
        if state & 0x20000:
            modifiers |= 4  # Alt

        unicode_char = 0
        if event.char and len(event.char) == 1:
            unicode_char = ord(event.char)

        self.transport.send_key_event(int(event.keycode), is_down, modifiers, unicode_char)

    def _on_close(self) -> None:
        self.transport.close()
        self.decoder.close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
