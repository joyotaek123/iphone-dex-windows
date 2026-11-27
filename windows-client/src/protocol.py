"""Binary protocol implementation matching PROTOCOL.md (IDEX v1, Big-Endian)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Iterator

MAGIC = b"IDEX"
VERSION = 0x01
HEADER_SIZE = 12
MAX_PAYLOAD_LENGTH = 16_777_216
DEFAULT_PORT = 29480

HEADER_STRUCT = struct.Struct(">4sBBHI")
HELLO_STRUCT = struct.Struct(">HHBBH")
HELLO_ACK_STRUCT = struct.Struct(">HHBBH")
VIDEO_FRAME_STRUCT = struct.Struct(">IQBBHH")
MOUSE_MOVE_STRUCT = struct.Struct(">ff")
MOUSE_BUTTON_STRUCT = struct.Struct(">ffBB")
MOUSE_SCROLL_STRUCT = struct.Struct(">ffff")
KEY_EVENT_STRUCT = struct.Struct(">IBBH")
PING_PONG_STRUCT = struct.Struct(">Q")


class ProtocolError(Exception):
    """Raised when incoming binary data violates the IDEX v1 contract."""


class MsgType(IntEnum):
    HELLO = 0x01
    HELLO_ACK = 0x02
    VIDEO_FRAME = 0x10
    MOUSE_MOVE = 0x20
    MOUSE_BUTTON = 0x21
    MOUSE_SCROLL = 0x22
    KEY_EVENT = 0x23
    PING = 0x30
    PONG = 0x31


class Codec(IntEnum):
    JPEG = 0x01
    H264_ANNEXB = 0x02


class Flags(IntEnum):
    NONE = 0x0000
    KEYFRAME = 0x0001


class MouseButton(IntEnum):
    LEFT = 1
    RIGHT = 2
    MIDDLE = 3


@dataclass(frozen=True)
class HelloMessage:
    client_width: int
    client_height: int
    target_fps: int
    preferred_codec: Codec
    reserved: int = 0


@dataclass(frozen=True)
class HelloAckMessage:
    canvas_width: int
    canvas_height: int
    actual_fps: int
    active_codec: Codec
    status: int = 0


@dataclass(frozen=True)
class VideoFrameMessage:
    frame_seq: int
    timestamp_us: int
    codec: Codec
    width: int
    height: int
    is_keyframe: bool
    frame_data: bytes


@dataclass(frozen=True)
class MouseMoveMessage:
    norm_x: float
    norm_y: float


@dataclass(frozen=True)
class MouseButtonMessage:
    norm_x: float
    norm_y: float
    button: int
    action: int  # 0 = up, 1 = down


@dataclass(frozen=True)
class MouseScrollMessage:
    norm_x: float
    norm_y: float
    delta_x: float
    delta_y: float


@dataclass(frozen=True)
class KeyEventMessage:
    key_code: int
    action: int  # 0 = up, 1 = down
    modifiers: int
    unicode_char: int


def clamp_norm(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def pack_packet(msg_type: MsgType, payload: bytes, flags: int = Flags.NONE) -> bytes:
    if len(payload) > MAX_PAYLOAD_LENGTH:
        raise ProtocolError(f"Payload too large: {len(payload)}")
    header = HEADER_STRUCT.pack(MAGIC, VERSION, int(msg_type), flags, len(payload))
    return header + payload


def pack_hello(
    client_width: int = 1920,
    client_height: int = 1080,
    target_fps: int = 30,
    preferred_codec: Codec = Codec.JPEG,
    reserved: int = 0,
) -> bytes:
    payload = HELLO_STRUCT.pack(
        client_width,
        client_height,
        target_fps,
        int(preferred_codec),
        reserved,
    )
    return pack_packet(MsgType.HELLO, payload)


def unpack_hello(payload: bytes) -> HelloMessage:
    if len(payload) != HELLO_STRUCT.size:
        raise ProtocolError(f"Invalid HELLO payload size: {len(payload)}")
    w, h, fps, codec_raw, reserved = HELLO_STRUCT.unpack(payload)
    return HelloMessage(w, h, fps, Codec(codec_raw), reserved)


def pack_hello_ack(
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    actual_fps: int = 30,
    active_codec: Codec = Codec.JPEG,
    status: int = 0,
) -> bytes:
    payload = HELLO_ACK_STRUCT.pack(
        canvas_width,
        canvas_height,
        actual_fps,
        int(active_codec),
        status,
    )
    return pack_packet(MsgType.HELLO_ACK, payload)


def unpack_hello_ack(payload: bytes) -> HelloAckMessage:
    if len(payload) != HELLO_ACK_STRUCT.size:
        raise ProtocolError(f"Invalid HELLO_ACK payload size: {len(payload)}")
    w, h, fps, codec_raw, status = HELLO_ACK_STRUCT.unpack(payload)
    return HelloAckMessage(w, h, fps, Codec(codec_raw), status)


def pack_video_frame(
    frame_seq: int,
    timestamp_us: int,
    codec: Codec,
    width: int,
    height: int,
    frame_data: bytes,
    is_keyframe: bool = True,
) -> bytes:
    sub_header = VIDEO_FRAME_STRUCT.pack(
        frame_seq,
        timestamp_us,
        int(codec),
        0,
        width,
        height,
    )
    flags = Flags.KEYFRAME if is_keyframe else Flags.NONE
    return pack_packet(MsgType.VIDEO_FRAME, sub_header + frame_data, flags=flags)


def unpack_video_frame(payload: bytes, flags: int) -> VideoFrameMessage:
    if len(payload) < VIDEO_FRAME_STRUCT.size:
        raise ProtocolError(f"Invalid VIDEO_FRAME payload size: {len(payload)}")
    seq, ts_us, codec_raw, _reserved, w, h = VIDEO_FRAME_STRUCT.unpack_from(payload, 0)
    return VideoFrameMessage(
        frame_seq=seq,
        timestamp_us=ts_us,
        codec=Codec(codec_raw),
        width=w,
        height=h,
        is_keyframe=bool(flags & Flags.KEYFRAME),
        frame_data=payload[VIDEO_FRAME_STRUCT.size :],
    )


def pack_mouse_move(norm_x: float, norm_y: float) -> bytes:
    payload = MOUSE_MOVE_STRUCT.pack(clamp_norm(norm_x), clamp_norm(norm_y))
    return pack_packet(MsgType.MOUSE_MOVE, payload)


def unpack_mouse_move(payload: bytes) -> MouseMoveMessage:
    if len(payload) != MOUSE_MOVE_STRUCT.size:
        raise ProtocolError(f"Invalid MOUSE_MOVE payload size: {len(payload)}")
    x, y = MOUSE_MOVE_STRUCT.unpack(payload)
    return MouseMoveMessage(x, y)


def pack_mouse_button(norm_x: float, norm_y: float, button: int, action: int) -> bytes:
    payload = MOUSE_BUTTON_STRUCT.pack(clamp_norm(norm_x), clamp_norm(norm_y), button, action)
    return pack_packet(MsgType.MOUSE_BUTTON, payload)


def unpack_mouse_button(payload: bytes) -> MouseButtonMessage:
    if len(payload) != MOUSE_BUTTON_STRUCT.size:
        raise ProtocolError(f"Invalid MOUSE_BUTTON payload size: {len(payload)}")
    x, y, button, action = MOUSE_BUTTON_STRUCT.unpack(payload)
    return MouseButtonMessage(x, y, button, action)


def pack_mouse_scroll(norm_x: float, norm_y: float, delta_x: float, delta_y: float) -> bytes:
    payload = MOUSE_SCROLL_STRUCT.pack(
        clamp_norm(norm_x),
        clamp_norm(norm_y),
        float(delta_x),
        float(delta_y),
    )
    return pack_packet(MsgType.MOUSE_SCROLL, payload)


def unpack_mouse_scroll(payload: bytes) -> MouseScrollMessage:
    if len(payload) != MOUSE_SCROLL_STRUCT.size:
        raise ProtocolError(f"Invalid MOUSE_SCROLL payload size: {len(payload)}")
    x, y, dx, dy = MOUSE_SCROLL_STRUCT.unpack(payload)
    return MouseScrollMessage(x, y, dx, dy)


def pack_key_event(key_code: int, action: int, modifiers: int, unicode_char: int) -> bytes:
    payload = KEY_EVENT_STRUCT.pack(key_code, action, modifiers, unicode_char & 0xFFFF)
    return pack_packet(MsgType.KEY_EVENT, payload)


def unpack_key_event(payload: bytes) -> KeyEventMessage:
    if len(payload) != KEY_EVENT_STRUCT.size:
        raise ProtocolError(f"Invalid KEY_EVENT payload size: {len(payload)}")
    key_code, action, modifiers, unicode_char = KEY_EVENT_STRUCT.unpack(payload)
    return KeyEventMessage(key_code, action, modifiers, unicode_char)


def pack_ping(timestamp_us: int) -> bytes:
    return pack_packet(MsgType.PING, PING_PONG_STRUCT.pack(timestamp_us))


def pack_pong(timestamp_us: int) -> bytes:
    return pack_packet(MsgType.PONG, PING_PONG_STRUCT.pack(timestamp_us))


def unpack_ping_pong(payload: bytes) -> int:
    if len(payload) != PING_PONG_STRUCT.size:
        raise ProtocolError(f"Invalid PING/PONG payload size: {len(payload)}")
    return PING_PONG_STRUCT.unpack(payload)[0]


class PacketStreamReader:
    """Incremental TCP framing buffer for IDEX v1 packets."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> Iterator[tuple[MsgType, int, bytes]]:
        self._buf.extend(chunk)
        while len(self._buf) >= HEADER_SIZE:
            magic, version, msg_raw, flags, payload_len = HEADER_STRUCT.unpack_from(self._buf, 0)
            if magic != MAGIC:
                raise ProtocolError(f"Invalid magic header: {magic!r}")
            if version != VERSION:
                raise ProtocolError(f"Unsupported protocol version: {version}")
            if payload_len > MAX_PAYLOAD_LENGTH:
                raise ProtocolError(f"Payload too large: {payload_len}")
            try:
                msg_type = MsgType(msg_raw)
            except ValueError as exc:
                raise ProtocolError(f"Unknown message type: {msg_raw:#x}") from exc

            total_len = HEADER_SIZE + payload_len
            if len(self._buf) < total_len:
                break

            payload = bytes(self._buf[HEADER_SIZE:total_len])
            del self._buf[:total_len]
            yield msg_type, flags, payload
