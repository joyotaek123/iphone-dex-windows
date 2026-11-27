"""Unit and integration tests for IDEX v1 protocol, decoder, transport, and Mock iOS Host."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SRC = REPO_ROOT / "windows-client" / "src"
MOCK_HOST_DIR = REPO_ROOT / "tools" / "mock-ios-host"

for p in (str(CLIENT_SRC), str(MOCK_HOST_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from decoder import FrameDecoder  # noqa: E402
from mock_ios_host import CANVAS_HEIGHT, CANVAS_WIDTH, MockIosHostServer  # noqa: E402
from protocol import (  # noqa: E402
    Codec,
    MouseButton,
    MsgType,
    PacketStreamReader,
    ProtocolError,
    pack_hello,
    pack_hello_ack,
    pack_key_event,
    pack_mouse_button,
    pack_mouse_move,
    pack_mouse_scroll,
    pack_ping,
    pack_pong,
    pack_video_frame,
    unpack_hello,
    unpack_hello_ack,
    unpack_key_event,
    unpack_mouse_button,
    unpack_mouse_move,
    unpack_mouse_scroll,
    unpack_ping_pong,
    unpack_video_frame,
)
from transport import DexTransport  # noqa: E402


class TestDexProtocol(unittest.TestCase):
    def test_all_packet_roundtrips_and_chunked_reassembly(self) -> None:
        stream_bytes = (
            pack_hello(1920, 1080, 60, Codec.H264_ANNEXB)
            + pack_hello_ack(1920, 1080, 30, Codec.JPEG, 0)
            + pack_video_frame(7, 123456789, Codec.JPEG, 1920, 1080, b"\xff\xd8\xff\xd9", is_keyframe=True)
            + pack_mouse_move(0.25, 0.75)
            + pack_mouse_button(0.5, 0.5, MouseButton.LEFT, 1)
            + pack_mouse_scroll(0.1, 0.2, -1.5, 2.5)
            + pack_key_event(65, 1, 1, ord("A"))
            + pack_ping(999999)
            + pack_pong(999999)
        )

        reader = PacketStreamReader()
        parsed = []
        # Feed 3 bytes at a time to verify partial TCP stream reassembly.
        for i in range(0, len(stream_bytes), 3):
            parsed.extend(reader.feed(stream_bytes[i : i + 3]))

        self.assertEqual(len(parsed), 9)

        self.assertEqual(parsed[0][0], MsgType.HELLO)
        hello = unpack_hello(parsed[0][2])
        self.assertEqual((hello.client_width, hello.client_height, hello.target_fps), (1920, 1080, 60))
        self.assertEqual(hello.preferred_codec, Codec.H264_ANNEXB)

        self.assertEqual(parsed[1][0], MsgType.HELLO_ACK)
        ack = unpack_hello_ack(parsed[1][2])
        self.assertEqual((ack.canvas_width, ack.canvas_height, ack.actual_fps, ack.status), (1920, 1080, 30, 0))
        self.assertEqual(ack.active_codec, Codec.JPEG)

        self.assertEqual(parsed[2][0], MsgType.VIDEO_FRAME)
        vf = unpack_video_frame(parsed[2][2], parsed[2][1])
        self.assertEqual((vf.frame_seq, vf.timestamp_us, vf.width, vf.height), (7, 123456789, 1920, 1080))
        self.assertTrue(vf.is_keyframe)
        self.assertEqual(vf.frame_data, b"\xff\xd8\xff\xd9")

        mv = unpack_mouse_move(parsed[3][2])
        self.assertAlmostEqual(mv.norm_x, 0.25, places=5)
        self.assertAlmostEqual(mv.norm_y, 0.75, places=5)

        mb = unpack_mouse_button(parsed[4][2])
        self.assertEqual((mb.button, mb.action), (MouseButton.LEFT, 1))
        self.assertAlmostEqual(mb.norm_x, 0.5, places=5)

        ms = unpack_mouse_scroll(parsed[5][2])
        self.assertAlmostEqual(ms.delta_x, -1.5, places=5)
        self.assertAlmostEqual(ms.delta_y, 2.5, places=5)

        ke = unpack_key_event(parsed[6][2])
        self.assertEqual((ke.key_code, ke.action, ke.modifiers, ke.unicode_char), (65, 1, 1, ord("A")))

        self.assertEqual(unpack_ping_pong(parsed[7][2]), 999999)
        self.assertEqual(unpack_ping_pong(parsed[8][2]), 999999)

    def test_invalid_magic_raises(self) -> None:
        reader = PacketStreamReader()
        with self.assertRaises(ProtocolError):
            list(reader.feed(b"BAD!\x01\x01\x00\x00\x00\x00\x00\x00"))


class TestMockHostRoundtrip(unittest.TestCase):
    def test_end_to_end_stream_and_mouse_click(self) -> None:
        server = MockIosHostServer(host="127.0.0.1", port=0, verbose=False)
        port = server.start()

        received_images = []
        frame_event = threading.Event()
        decoder = FrameDecoder()

        def on_frame(vf):
            img = decoder.decode(vf)
            if img is not None:
                received_images.append(img)
                if len(received_images) >= 2:
                    frame_event.set()

        transport = DexTransport(on_frame=on_frame)
        try:
            ack = transport.connect_tcp(host="127.0.0.1", port=port, preferred_codec=Codec.JPEG, target_fps=30)
            self.assertEqual((ack.canvas_width, ack.canvas_height, ack.status), (1920, 1080, 0))

            got_frames = frame_event.wait(timeout=5.0)
            self.assertTrue(got_frames, "Expected at least 2 JPEG frames from MockIosHostServer")
            self.assertEqual(received_images[0].size, (CANVAS_WIDTH, CANVAS_HEIGHT))

            # Click center of "+1 Counter" button on the floating window.
            x1, y1, x2, y2 = server.state.increment_btn_rect
            norm_x = ((x1 + x2) / 2.0) / CANVAS_WIDTH
            norm_y = ((y1 + y2) / 2.0) / CANVAS_HEIGHT
            transport.send_mouse_button(norm_x, norm_y, MouseButton.LEFT, True)
            transport.send_mouse_button(norm_x, norm_y, MouseButton.LEFT, False)
            transport.send_key_event(65, True, 0, ord("A"))
            transport.send_key_event(65, False, 0, ord("A"))

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if server.state.button_clicks == 1 and server.state.typed_text == "A":
                    break
                time.sleep(0.05)

            self.assertEqual(server.state.button_clicks, 1)
            self.assertEqual(server.state.typed_text, "A")
        finally:
            transport.close()
            decoder.close()
            server.stop()


if __name__ == "__main__":
    unittest.main()
