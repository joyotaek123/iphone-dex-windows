"""Network transport (TCP & USB usbmuxd) plus Phase 2 Auto-JIT hooks via pymobiledevice3."""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional

from protocol import (
    Codec,
    DEFAULT_PORT,
    HelloAckMessage,
    MsgType,
    PacketStreamReader,
    ProtocolError,
    VideoFrameMessage,
    pack_hello,
    pack_key_event,
    pack_mouse_button,
    pack_mouse_move,
    pack_mouse_scroll,
    pack_ping,
    unpack_hello_ack,
    unpack_ping_pong,
    unpack_video_frame,
)


class UsbDeviceManager:
    """Detects iPhones over USB via pymobiledevice3/usbmuxd and opens TCP tunnels."""

    @staticmethod
    def is_available() -> bool:
        try:
            import pymobiledevice3  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def list_devices() -> list[str]:
        try:
            from pymobiledevice3.usbmux import list_devices
        except ImportError as exc:
            raise RuntimeError(
                "pymobiledevice3 is not installed. Run: python -m pip install pymobiledevice3"
            ) from exc

        devices = list_devices()
        return [d.serial for d in devices if getattr(d, "connection_type", "") == "USB"]

    @staticmethod
    def connect_usbmux_tcp(port: int = DEFAULT_PORT, udid: Optional[str] = None) -> socket.socket:
        try:
            from pymobiledevice3.usbmux import list_devices
        except ImportError as exc:
            raise RuntimeError(
                "pymobiledevice3 is not installed. Run: python -m pip install pymobiledevice3"
            ) from exc

        devices = [d for d in list_devices() if getattr(d, "connection_type", "") == "USB"]
        if not devices:
            raise RuntimeError("No iPhone detected over USB (usbmuxd). Check USB cable & Trust prompt.")

        target = devices[0]
        if udid:
            matched = [d for d in devices if d.serial == udid]
            if not matched:
                raise RuntimeError(f"iPhone with UDID {udid} not found on USB.")
            target = matched[0]

        return target.connect(port)

    @staticmethod
    def try_enable_jit(bundle_id: str = "com.iphonedex.host", udid: Optional[str] = None) -> tuple[bool, str]:
        """Hook for Phase 2 iOS 17+ JIT activation using pymobiledevice3."""
        if not UsbDeviceManager.is_available():
            return False, "pymobiledevice3 not installed (JIT activation skipped)"
        # Phase 2 will attach to running tunneld/DVT debugserver to enable JIT on target bundle_id.
        return False, f"Auto-JIT hook ready for {bundle_id} (Phase 2)"


class DexTransport:
    """Manages a persistent IDEX v1 binary TCP session with the iOS Host."""

    def __init__(
        self,
        on_frame: Optional[Callable[[VideoFrameMessage], None]] = None,
        on_rtt_ms: Optional[Callable[[float], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_frame = on_frame
        self._on_rtt_ms = on_rtt_ms
        self._on_disconnect = on_disconnect

        self._sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None
        self.ack: Optional[HelloAckMessage] = None

    def connect_tcp(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        preferred_codec: Codec = Codec.JPEG,
        target_fps: int = 30,
        timeout: float = 5.0,
    ) -> HelloAckMessage:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self._start_session(sock, preferred_codec=preferred_codec, target_fps=target_fps)

    def connect_usb(
        self,
        port: int = DEFAULT_PORT,
        udid: Optional[str] = None,
        preferred_codec: Codec = Codec.JPEG,
        target_fps: int = 30,
    ) -> HelloAckMessage:
        sock = UsbDeviceManager.connect_usbmux_tcp(port=port, udid=udid)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self._start_session(sock, preferred_codec=preferred_codec, target_fps=target_fps)

    def _start_session(
        self,
        sock: socket.socket,
        preferred_codec: Codec,
        target_fps: int,
    ) -> HelloAckMessage:
        self._sock = sock
        reader = PacketStreamReader()

        # Perform synchronous HELLO -> HELLO_ACK handshake.
        sock.settimeout(5.0)
        sock.sendall(
            pack_hello(
                client_width=1920,
                client_height=1080,
                target_fps=target_fps,
                preferred_codec=preferred_codec,
            )
        )

        ack_msg: Optional[HelloAckMessage] = None
        while ack_msg is None:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Host closed connection during handshake.")
            for msg_type, _flags, payload in reader.feed(chunk):
                if msg_type == MsgType.HELLO_ACK:
                    ack_msg = unpack_hello_ack(payload)
                    break

        if ack_msg.status != 0:
            raise ConnectionError(f"Host rejected handshake with status={ack_msg.status}")

        self.ack = ack_msg
        sock.settimeout(None)
        self._running = True

        self._recv_thread = threading.Thread(target=self._recv_loop, args=(sock, reader), daemon=True)
        self._recv_thread.start()

        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()
        return ack_msg

    def _recv_loop(self, sock: socket.socket, reader: PacketStreamReader) -> None:
        reason = "Disconnected"
        try:
            while self._running:
                chunk = sock.recv(65536)
                if not chunk:
                    reason = "Host closed connection"
                    break
                for msg_type, flags, payload in reader.feed(chunk):
                    if msg_type == MsgType.VIDEO_FRAME:
                        frame = unpack_video_frame(payload, flags)
                        if self._on_frame:
                            self._on_frame(frame)
                    elif msg_type == MsgType.PONG:
                        sent_us = unpack_ping_pong(payload)
                        rtt_ms = max(0.0, (time.monotonic_ns() // 1000 - sent_us) / 1000.0)
                        if self._on_rtt_ms:
                            self._on_rtt_ms(rtt_ms)
        except (OSError, ProtocolError) as exc:
            if self._running:
                reason = str(exc)
        finally:
            was_running = self._running
            self._running = False
            if was_running and self._on_disconnect:
                self._on_disconnect(reason)

    def _ping_loop(self) -> None:
        while self._running:
            time.sleep(1.0)
            if not self._running:
                break
            try:
                now_us = time.monotonic_ns() // 1000
                self._send_raw(pack_ping(now_us))
            except OSError:
                break

    def _send_raw(self, data: bytes) -> None:
        sock = self._sock
        if not self._running or sock is None:
            return
        with self._send_lock:
            sock.sendall(data)

    def send_mouse_move(self, norm_x: float, norm_y: float) -> None:
        self._send_raw(pack_mouse_move(norm_x, norm_y))

    def send_mouse_button(self, norm_x: float, norm_y: float, button: int, is_down: bool) -> None:
        self._send_raw(pack_mouse_button(norm_x, norm_y, button, 1 if is_down else 0))

    def send_mouse_scroll(self, norm_x: float, norm_y: float, delta_x: float, delta_y: float) -> None:
        self._send_raw(pack_mouse_scroll(norm_x, norm_y, delta_x, delta_y))

    def send_key_event(self, key_code: int, is_down: bool, modifiers: int, unicode_char: int) -> None:
        self._send_raw(pack_key_event(key_code, 1 if is_down else 0, modifiers, unicode_char))

    def close(self) -> None:
        self._running = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
