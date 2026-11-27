"""Video frame decoder supporting Phase 1 JPEG and VideoToolbox H.264 Annex-B streams."""

from __future__ import annotations

from io import BytesIO
import shutil
import subprocess
import threading
from typing import Callable, Optional

from PIL import Image

from protocol import Codec, VideoFrameMessage


class FrameDecoder:
    """Decodes incoming VideoFrameMessage packets into RGB PIL Images."""

    def __init__(self, on_image: Optional[Callable[[Image.Image, VideoFrameMessage], None]] = None) -> None:
        self._on_image = on_image
        self._ffmpeg_proc: Optional[subprocess.Popen[bytes]] = None
        self._ffmpeg_thread: Optional[threading.Thread] = None
        self._h264_dims: tuple[int, int] = (1920, 1080)
        self._last_frame_meta: Optional[VideoFrameMessage] = None
        self._lock = threading.Lock()
        self._closed = False

    def decode(self, frame: VideoFrameMessage) -> Optional[Image.Image]:
        if frame.codec == Codec.JPEG:
            img = Image.open(BytesIO(frame.frame_data)).convert("RGB")
            if self._on_image:
                self._on_image(img, frame)
            return img

        if frame.codec == Codec.H264_ANNEXB:
            self._feed_h264(frame)
            return None

        raise ValueError(f"Unsupported codec: {frame.codec}")

    def _feed_h264(self, frame: VideoFrameMessage) -> None:
        with self._lock:
            self._last_frame_meta = frame
            if self._ffmpeg_proc is None or self._h264_dims != (frame.width, frame.height):
                self._start_ffmpeg(frame.width, frame.height)

            proc = self._ffmpeg_proc
            if proc and proc.stdin:
                try:
                    proc.stdin.write(frame.frame_data)
                    proc.stdin.flush()
                except BrokenPipeError:
                    self._stop_ffmpeg_locked()

    def _start_ffmpeg(self, width: int, height: int) -> None:
        self._stop_ffmpeg_locked()
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            raise RuntimeError("FFmpeg executable not found on PATH for H.264 decoding.")

        self._h264_dims = (width, height)
        cmd = [
            ffmpeg_exe,
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        self._ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._ffmpeg_thread = threading.Thread(
            target=self._read_ffmpeg_stdout,
            args=(self._ffmpeg_proc, width, height),
            daemon=True,
        )
        self._ffmpeg_thread.start()

    def _read_ffmpeg_stdout(self, proc: subprocess.Popen[bytes], width: int, height: int) -> None:
        frame_bytes = width * height * 3
        stdout = proc.stdout
        if stdout is None:
            return
        while not self._closed and proc.poll() is None:
            raw = stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                break
            img = Image.frombytes("RGB", (width, height), raw)
            meta = self._last_frame_meta
            if self._on_image and meta is not None:
                self._on_image(img, meta)

    def _stop_ffmpeg_locked(self) -> None:
        if self._ffmpeg_proc is not None:
            try:
                if self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.close()
            except OSError:
                pass
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=1.0)
            except Exception:
                self._ffmpeg_proc.kill()
            self._ffmpeg_proc = None

    def close(self) -> None:
        self._closed = True
        with self._lock:
            self._stop_ffmpeg_locked()
