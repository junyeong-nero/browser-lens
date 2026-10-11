"""Internal recording helpers for PlaywrightBrowser artifacts and clips."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .artifact_logger import ArtifactLogger
from .gif import build_high_quality_gif_filter

ACTION_CLIP_START_HOLD_SECONDS = 0.35
ACTION_CLIP_END_HOLD_SECONDS = 0.85
ACTION_CLIP_MIN_OUTPUT_FPS = 15.0
ACTION_VIDEO_MIN_FRAME_COUNT = 15
ACTION_TRANSITION_SECONDS = 1.0
ACTION_TRANSITION_FADE_SECONDS = 0.35


class BrowserRecordingHelper:
    """Owns frame streaming and per-action recording state.

    The public browser facade keeps compatibility wrappers for tests and callers;
    this helper centralizes the stateful recording implementation.
    """

    def __init__(self, *, artifact_logger: ArtifactLogger, subprocess_module: Any, shutil_module: Any):
        self.artifact_logger = artifact_logger
        self._subprocess = subprocess_module
        self._shutil = shutil_module
        self.frame_buffer: bytes | None = None
        self.frame_lock = threading.Lock()
        self._frame_thread: Optional[threading.Thread] = None
        self._frame_stop = threading.Event()
        self._ffmpeg_proc: Any | None = None
        self._action_cdp_session: Any | None = None
        self._action_capture_frames: list[tuple[float, bytes]] | None = None
        self._action_capture_lock = threading.Lock()
        self._action_capture_started_at: float | None = None

    def set_artifact_logger(self, artifact_logger: ArtifactLogger) -> None:
        self.artifact_logger = artifact_logger

    def history_dir(self) -> Optional[Path]:
        return self.artifact_logger.history_dir()

    def video_dir(self) -> Optional[Path]:
        return self.artifact_logger.video_dir()

    def latest_artifact_metadata(self) -> Optional[dict]:
        return self.artifact_logger.latest_artifact_metadata()

    def prepare_log_dirs(self) -> None:
        self.artifact_logger.prepare_log_dirs()

    def prepare_video_dir(self) -> None:
        self.artifact_logger.prepare_video_dir()

    def update_frame_buffer(self, frame: bytes) -> None:
        with self.frame_lock:
            self.frame_buffer = frame

    def _latest_frame_buffer(self) -> bytes | None:
        with self.frame_lock:
            return self.frame_buffer

    def start_frame_stream(self, *, fps: int) -> None:
        video_dir = self.video_dir()
        if not video_dir:
            return
        ffmpeg_cmd = os.getenv("COMPUTER_USE_FFMPEG_COMMAND") or self._shutil.which("ffmpeg")
        if not ffmpeg_cmd:
            return
        self.prepare_video_dir()
        output_path = video_dir / "session_60fps.mp4"
        cmd = [
            ffmpeg_cmd, "-y",
            "-f", "image2pipe",
            "-framerate", str(fps),
            "-vcodec", "png",
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
        self._ffmpeg_proc = self._subprocess.Popen(
            cmd,
            stdin=self._subprocess.PIPE,
            stdout=self._subprocess.DEVNULL,
            stderr=self._subprocess.DEVNULL,
        )
        self._frame_stop.clear()
        self._frame_thread = threading.Thread(
            target=self._frame_pipe_loop,
            args=(fps,),
            daemon=True,
            name="frame-pipe",
        )
        self._frame_thread.start()

    def stop_frame_stream(self) -> None:
        self._frame_stop.set()
        if self._frame_thread:
            self._frame_thread.join(timeout=5)
            self._frame_thread = None
        if self._ffmpeg_proc:
            try:
                if self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.close()
                self._ffmpeg_proc.wait(timeout=30)
            except Exception:
                self._ffmpeg_proc.kill()
                try:
                    self._ffmpeg_proc.wait(timeout=5)
                except Exception:
                    pass
            self._ffmpeg_proc = None

    @staticmethod
    def _cleanup_process(
        proc: Any,
        *,
        wait_timeout: float,
        kill_timeout: float,
        force_kill: bool = False,
    ) -> bool:
        stdin = getattr(proc, "stdin", None)
        close_failed = False
        if stdin is not None:
            try:
                stdin.close()
            except Exception:
                close_failed = True

        if not force_kill and not close_failed:
            try:
                proc.wait(timeout=wait_timeout)
                return True
            except Exception:
                pass

        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=kill_timeout)
        except Exception:
            pass
        return False

    def _frame_pipe_loop(self, fps: int) -> None:
        interval = 1.0 / fps
        while not self._frame_stop.wait(interval):
            with self.frame_lock:
                frame = self.frame_buffer
            if frame is None or self._ffmpeg_proc is None:
                continue
            stdin = self._ffmpeg_proc.stdin
            if stdin is None:
                break
            try:
                stdin.write(frame)
            except (BrokenPipeError, OSError):
                break

    def begin_action_capture(self, *, page: Any, context: Any) -> None:
        if not self.history_dir():
            return
        ffmpeg_cmd = os.getenv("COMPUTER_USE_FFMPEG_COMMAND") or self._shutil.which("ffmpeg")
        if not ffmpeg_cmd or page is None or context is None:
            return
        started_at = time.time()
        stable_before_frame = self._latest_frame_buffer()
        with self._action_capture_lock:
            self._action_capture_frames = (
                [(started_at, stable_before_frame)] if stable_before_frame is not None else []
            )
            self._action_capture_started_at = started_at
        try:
            cdp_session = context.new_cdp_session(page)

            def on_frame(params: dict[str, Any]) -> None:
                data = params.get("data")
                session_id = params.get("sessionId")
                if session_id is not None:
                    try:
                        cdp_session.send("Page.screencastFrameAck", {"sessionId": session_id})
                    except Exception:
                        pass
                if not isinstance(data, str):
                    return
                try:
                    frame = base64.b64decode(data)
                except Exception:
                    return
                frame_ts = time.time()
                metadata = params.get("metadata")
                if isinstance(metadata, dict) and isinstance(metadata.get("timestamp"), (int, float)):
                    frame_ts = time.time()
                with self._action_capture_lock:
                    frames = self._action_capture_frames
                    if frames is not None and len(frames) < 600:
                        frames.append((frame_ts, frame))

            cdp_session.on("Page.screencastFrame", on_frame)
            cdp_session.send("Page.startScreencast", {"format": "png", "quality": 80, "everyNthFrame": 1})
            self._action_cdp_session = cdp_session
        except Exception:
            with self._action_capture_lock:
                self._action_capture_frames = None
                self._action_capture_started_at = None
            self._action_cdp_session = None

    def end_action_capture(self, *, persist: bool = True) -> dict[str, Any] | None:
        cdp_session = self._action_cdp_session
        if cdp_session is not None:
            try:
                cdp_session.send("Page.stopScreencast")
            except Exception:
                pass
            try:
                detach = getattr(cdp_session, "detach", None)
                if callable(detach):
                    detach()
            except Exception:
                pass
            finally:
                self._action_cdp_session = None

        with self._action_capture_lock:
            captured_frames = list(self._action_capture_frames or [])
            started_at = self._action_capture_started_at
            self._action_capture_frames = None
            self._action_capture_started_at = None

        if not persist:
            return None

        final_frame = self._latest_frame_buffer()
        if final_frame is not None and (
            not captured_frames or captured_frames[-1][1] != final_frame
        ):
            final_ts = time.time()
            if captured_frames:
                final_ts = max(final_ts, captured_frames[-1][0] + 0.001)
            captured_frames.append((final_ts, final_frame))

        metadata = self.latest_artifact_metadata()
        history_dir = self.history_dir()
        if not metadata or not history_dir:
            return None

        ended_at = time.time()
        metadata_updates: dict[str, Any] = {
            "action_started_at": started_at,
            "action_ended_at": ended_at,
            "action_duration_ms": int((ended_at - started_at) * 1000) if started_at else None,
            "action_capture_frame_count": len(captured_frames),
        }
        sampled_frames = self.sample_action_frames(captured_frames, max_frames=60)
        distinct_frame_count = self.action_gif_distinct_frame_count(sampled_frames)
        if sampled_frames:
            metadata_updates["action_gif_frame_count"] = len(sampled_frames)
            metadata_updates["action_gif_distinct_frame_count"] = distinct_frame_count
        video_name = None
        if len(sampled_frames) >= 2 and distinct_frame_count >= 2:
            action_output_fps = self.action_gif_output_fps(sampled_frames)
            metadata_updates["action_gif_output_fps"] = round(
                action_output_fps,
                3,
            )
            video_name = self.write_action_clip_video(sampled_frames, metadata)
            if video_name:
                metadata_updates["action_video_path"] = video_name
                metadata_updates["action_video_source"] = "action_capture_frames"
                metadata_updates["action_video_output_fps"] = round(action_output_fps, 3)
        clip_name = (
            self.write_action_clip_gif(sampled_frames, metadata)
            if distinct_frame_count >= 2
            else None
        )
        if clip_name:
            metadata_updates["action_clip_gif_path"] = clip_name
        if not video_name:
            transition_name = self.write_action_transition_video(metadata)
            if transition_name:
                metadata_updates["action_video_path"] = transition_name
                metadata_updates["action_video_source"] = "before_after_transition"
                metadata_updates["action_video_output_fps"] = ACTION_CLIP_MIN_OUTPUT_FPS
                metadata_updates["action_video_min_frame_count"] = ACTION_VIDEO_MIN_FRAME_COUNT
        self.merge_latest_metadata(metadata_updates)
        return metadata_updates

    @staticmethod
    def sample_action_frames(
        frames: list[tuple[float, bytes]],
        *,
        max_frames: int,
    ) -> list[tuple[float, bytes]]:
        if len(frames) <= max_frames:
            return frames
        if max_frames <= 1:
            return frames[:1]
        last_index = len(frames) - 1
        selected: list[tuple[float, bytes]] = []
        seen_indices: set[int] = set()
        for out_index in range(max_frames):
            source_index = round(out_index * last_index / (max_frames - 1))
            if source_index in seen_indices:
                continue
            seen_indices.add(source_index)
            selected.append(frames[source_index])
        return selected

    @staticmethod
    def action_gif_input_fps(frames: list[tuple[float, bytes]]) -> float:
        if len(frames) < 2:
            return 20.0
        duration = max(frames[-1][0] - frames[0][0], 0.001)
        return max(0.5, min(60.0, (len(frames) - 1) / duration))

    @staticmethod
    def action_gif_output_fps(frames: list[tuple[float, bytes]]) -> float:
        return max(
            ACTION_CLIP_MIN_OUTPUT_FPS,
            BrowserRecordingHelper.action_gif_input_fps(frames),
        )

    @staticmethod
    def action_gif_distinct_frame_count(frames: list[tuple[float, bytes]]) -> int:
        return len({frame for _timestamp, frame in frames})

    @staticmethod
    def action_clip_video_filter(output_fps: float) -> str:
        return (
            f"tpad=start_mode=clone:start_duration={ACTION_CLIP_START_HOLD_SECONDS}"
            f":stop_mode=clone:stop_duration={ACTION_CLIP_END_HOLD_SECONDS}"
            f",fps={output_fps:.3f}"
            ",scale=w='min(iw\\,1920)':h='min(ih\\,1080)'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2"
            ",format=yuv420p"
        )

    @staticmethod
    def action_transition_video_filter() -> str:
        return (
            "[0:v]scale=w='min(iw\\,1920)':h='min(ih\\,1080)'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[v0];"
            "[1:v]scale=w='min(iw\\,1920)':h='min(ih\\,1080)'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[v1];"
            f"[v0][v1]xfade=transition=fade:duration={ACTION_TRANSITION_FADE_SECONDS}"
            f":offset={max(0.0, ACTION_TRANSITION_SECONDS - ACTION_TRANSITION_FADE_SECONDS):.3f}"
            f",fps={int(ACTION_CLIP_MIN_OUTPUT_FPS)},format=yuv420p[v]"
        )

    def write_action_clip_video(self, frames: list[tuple[float, bytes]], metadata: dict[str, Any]) -> str | None:
        if len(frames) < 2:
            return None
        history_dir = self.history_dir()
        if not history_dir:
            return None
        ffmpeg_cmd = os.getenv("COMPUTER_USE_FFMPEG_COMMAND") or self._shutil.which("ffmpeg")
        if not ffmpeg_cmd:
            return None
        step = metadata.get("step")
        if not isinstance(step, int):
            return None
        output_path = history_dir / f"step-{step:04d}-action.mp4"
        self._unlink_path(output_path)
        input_fps = self.action_gif_input_fps(frames)
        output_fps = self.action_gif_output_fps(frames)
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "image2pipe",
            "-framerate",
            f"{input_fps:.3f}",
            "-vcodec",
            "png",
            "-i",
            "pipe:0",
            "-vf",
            self.action_clip_video_filter(output_fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        if not self._write_piped_frames(cmd, [frame for _timestamp, frame in frames]):
            self._unlink_path(output_path)
            return None
        if not output_path.is_file():
            return None
        if not self._validate_action_video(output_path, ffmpeg_cmd=ffmpeg_cmd):
            self._unlink_path(output_path)
            return None
        return output_path.name

    def write_action_transition_video(self, metadata: dict[str, Any]) -> str | None:
        history_dir = self.history_dir()
        if not history_dir:
            return None
        ffmpeg_cmd = os.getenv("COMPUTER_USE_FFMPEG_COMMAND") or self._shutil.which("ffmpeg")
        if not ffmpeg_cmd:
            return None
        step = metadata.get("step")
        if not isinstance(step, int):
            return None
        before_path = self._history_artifact_path(
            metadata.get("before_screenshot_path"),
            history_dir=history_dir,
        )
        after_path = self._history_artifact_path(
            metadata.get("after_screenshot_path") or metadata.get("screenshot_path"),
            history_dir=history_dir,
        )
        if not before_path or not after_path or not before_path.is_file() or not after_path.is_file():
            return None
        output_path = history_dir / f"step-{step:04d}-action.mp4"
        self._unlink_path(output_path)
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{ACTION_TRANSITION_SECONDS:.3f}",
            "-i",
            str(before_path),
            "-loop",
            "1",
            "-t",
            f"{ACTION_TRANSITION_SECONDS:.3f}",
            "-i",
            str(after_path),
            "-filter_complex",
            self.action_transition_video_filter(),
            "-map",
            "[v]",
            "-frames:v",
            str(ACTION_VIDEO_MIN_FRAME_COUNT),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        if not self._write_piped_frames(cmd, []):
            self._unlink_path(output_path)
            return None
        if not output_path.is_file():
            return None
        if not self._validate_action_video(output_path, ffmpeg_cmd=ffmpeg_cmd):
            self._unlink_path(output_path)
            return None
        return output_path.name

    def _write_piped_frames(self, cmd: list[str], frames: list[bytes]) -> bool:
        proc = None
        try:
            proc = self._subprocess.Popen(
                cmd,
                stdin=self._subprocess.PIPE,
                stdout=self._subprocess.DEVNULL,
                stderr=self._subprocess.DEVNULL,
            )
            assert proc.stdin is not None
            for frame in frames:
                proc.stdin.write(frame)
        except Exception:
            if proc is not None:
                self._cleanup_process(proc, wait_timeout=20, kill_timeout=5, force_kill=True)
            return False
        return self._cleanup_process(proc, wait_timeout=20, kill_timeout=5)

    def write_action_clip_gif(self, frames: list[tuple[float, bytes]], metadata: dict[str, Any]) -> str | None:
        if len(frames) < 2:
            return None
        history_dir = self.history_dir()
        if not history_dir:
            return None
        ffmpeg_cmd = os.getenv("COMPUTER_USE_FFMPEG_COMMAND") or self._shutil.which("ffmpeg")
        if not ffmpeg_cmd:
            return None
        step = metadata.get("step")
        if not isinstance(step, int):
            return None
        output_path = history_dir / f"step-{step:04d}-action.gif"
        input_fps = self.action_gif_input_fps(frames)
        output_fps = self.action_gif_output_fps(frames)
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "image2pipe",
            "-framerate",
            f"{input_fps:.3f}",
            "-vcodec",
            "png",
            "-i",
            "pipe:0",
            "-filter_complex",
            build_high_quality_gif_filter(
                "[0:v]"
                f"tpad=start_mode=clone:start_duration={ACTION_CLIP_START_HOLD_SECONDS}"
                f":stop_mode=clone:stop_duration={ACTION_CLIP_END_HOLD_SECONDS}"
                f",fps={output_fps:.3f}"
            ),
            str(output_path),
        ]
        if not self._write_piped_frames(cmd, [frame for _timestamp, frame in frames]):
            return None
        if not output_path.is_file():
            return None
        encoded_distinct_frame_count = self.encoded_gif_distinct_frame_count(
            output_path,
            ffmpeg_cmd=ffmpeg_cmd,
        )
        if encoded_distinct_frame_count is not None and encoded_distinct_frame_count < 2:
            try:
                output_path.unlink()
            except OSError:
                pass
            return None
        return output_path.name

    def _validate_action_video(self, video_path: Path, *, ffmpeg_cmd: str) -> bool:
        stats = self.encoded_media_frame_stats(video_path, ffmpeg_cmd=ffmpeg_cmd)
        if stats is None:
            return True
        frame_count, distinct_frame_count = stats
        return frame_count >= ACTION_VIDEO_MIN_FRAME_COUNT and distinct_frame_count >= 2

    def encoded_gif_distinct_frame_count(
        self,
        gif_path: Path,
        *,
        ffmpeg_cmd: str,
    ) -> int | None:
        stats = self.encoded_media_frame_stats(gif_path, ffmpeg_cmd=ffmpeg_cmd)
        if stats is None:
            return None
        return stats[1]

    def encoded_media_frame_stats(
        self,
        media_path: Path,
        *,
        ffmpeg_cmd: str,
    ) -> tuple[int, int] | None:
        cmd = [
            ffmpeg_cmd,
            "-v",
            "error",
            "-i",
            str(media_path),
            "-f",
            "framemd5",
            "-",
        ]
        try:
            completed = self._subprocess.run(
                cmd,
                stdout=self._subprocess.PIPE,
                stderr=self._subprocess.DEVNULL,
                check=True,
                timeout=15,
                text=True,
            )
        except Exception:
            return None
        stdout = getattr(completed, "stdout", "")
        if not isinstance(stdout, str):
            return None
        hashes = set()
        frame_count = 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 6:
                continue
            frame_count += 1
            hashes.add(parts[-1])
        if frame_count == 0:
            return None
        return frame_count, len(hashes)

    @staticmethod
    def _history_artifact_path(value: Any, *, history_dir: Path) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        name = Path(value).name
        if not name:
            return None
        return history_dir / name

    @staticmethod
    def _unlink_path(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def merge_latest_metadata(self, updates: dict[str, Any]) -> None:
        metadata = self.latest_artifact_metadata()
        history_dir = self.history_dir()
        if not metadata or not history_dir:
            return
        metadata_path_value = metadata.get("metadata_path")
        if not isinstance(metadata_path_value, str):
            return
        metadata_path = history_dir / metadata_path_value
        if not metadata_path.is_file():
            return
        try:
            current = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(current, dict):
            return
        current.update(updates)
        metadata_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        latest = getattr(self.artifact_logger, "_latest_artifact_metadata", None)
        if isinstance(latest, dict):
            latest.update(updates)
