"""Video lesson artifact renderer; accepts data, never generated executable code."""
from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ARTIFACTS = Path(os.environ.get("TUTOR_MEDIA_DIR", Path(tempfile.gettempdir()) / "tutor-lesson-artifacts")).resolve()
FORMATS = {"lesson.mp4": "video/mp4", "captions.vtt": "text/vtt"}
DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
VOICES = {"zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "en-US-AriaNeural", "en-US-GuyNeural"}


def resolve_media(media_id: str, filename: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", media_id) or filename not in FORMATS:
        raise FileNotFoundError("Unknown media")
    path = (ARTIFACTS / media_id / filename).resolve()
    if not path.is_relative_to(ARTIFACTS) or not path.is_file():
        raise FileNotFoundError("Unknown media")
    return path


def _run(cmd: list[str], timeout: int = 90) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(f"Video renderer returned an error ({cmd[0]})")
    return proc.stdout.strip()


def _stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{sec:02}.{ms:03}"


def _wrap(draw, text, font, width):
    lines = []
    for para in text.splitlines():
        line = ""
        for char in para:
            if line and draw.textlength(line + char, font=font) > width:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    return lines


async def _voice(text: str, voice: str, dst: Path) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("Edge narration requires the optional edge-tts dependency") from exc
    await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(dst)), timeout=45)


def build_lesson(inputs: dict) -> dict:
    """Render structured scenes to H.264 video and UTF-8 WebVTT. Call off the event loop."""
    title = str(inputs.get("title") or "视频课程").strip()[:100]
    raw = inputs.get("scenes")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError("Video Lesson requires 1–12 structured scenes")
    scenes = []
    for scene in raw:
        if not isinstance(scene, dict) or not isinstance(scene.get("text"), str):
            raise ValueError("Every scene needs text")
        content = scene["text"].strip()
        seconds = float(scene.get("duration_seconds", 5))
        if not content or len(content) > 280 or not math.isfinite(seconds) or not 1 <= seconds <= 45:
            raise ValueError("Use 1–280 characters and 1–45 seconds per scene")
        scenes.append(dict(text=content, duration_seconds=seconds))
    tts = inputs.get("tts") or {}
    if isinstance(tts, str):
        tts = {"provider": tts}
    if not isinstance(tts, dict):
        raise ValueError("tts must be a provider name or configuration object")
    provider = tts.get("provider", "none")
    voice = tts.get("voice", "zh-CN-XiaoxiaoNeural")
    if provider not in {"none", "edge"} or not isinstance(voice, str):
        raise ValueError("Supported narration providers: none, edge")
    if provider == "edge" and (os.environ.get("TUTOR_ENABLE_EDGE_TTS") != "1" or voice not in VOICES):
        raise ValueError("Edge TTS sends lesson text to Microsoft; enable it server-side and select an allowed voice")
    if sum(s["duration_seconds"] for s in scenes) > 240:
        raise ValueError("Lesson total exceeds 240 seconds")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or (provider == "edge" and not ffprobe):
        raise RuntimeError("Video rendering requires FFmpeg (and ffprobe for narration)")
    from PIL import Image, ImageDraw, ImageFont
    font_path = os.environ.get("TUTOR_VIDEO_FONT", DEFAULT_FONT)
    if not Path(font_path).is_file():
        raise RuntimeError("Set TUTOR_VIDEO_FONT to an installed font supporting the lesson language")
    head, body, foot = [ImageFont.truetype(font_path, size) for size in (40, 32, 21)]
    ARTIFACTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    dest = ARTIFACTS / media_id
    with tempfile.TemporaryDirectory(prefix="lesson-", dir=ARTIFACTS) as staging:
        tmp = Path(staging)
        cues = ["WEBVTT", ""]
        elapsed = 0.0
        for i, scene in enumerate(scenes):
            content, seconds = scene["text"], scene["duration_seconds"]
            img = Image.new("RGB", (960, 540), "#10192a")
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((50, 40, 910, 500), radius=22, fill="#192840")
            draw.text((78, 60), f"LESSON   {i+1:02d} / {len(scenes):02d}", fill="#81d7ed", font=foot)
            title_lines = _wrap(draw, title, head, 800)
            draw.text((78, 112), title_lines[0][:100], fill="#ffffff", font=head)
            lines = _wrap(draw, content, body, 800)
            if len(lines) > 7:
                raise ValueError("Slide text will overflow; split the scene into two slides")
            for n, line in enumerate(lines):
                draw.text((78, 188 + n * 41), line, fill="#ecf4ff", font=body)
            slide, clip, audio = (tmp / f"{i}.{ext}" for ext in ("png", "mp4", "mp3"))
            img.save(slide)
            args = [ffmpeg, "-nostdin", "-v", "error", "-y", "-loop", "1", "-framerate", "15", "-i", str(slide)]
            if provider == "edge":
                asyncio.run(_voice(content, voice, audio))
                spoken = float(_run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)]))
                seconds = max(seconds, spoken + .2)
                args += ["-i", str(audio), "-af", "apad", "-c:a", "aac", "-ar", "48000"]
            scene["duration_seconds"] = seconds
            if elapsed + seconds > 240:
                raise ValueError("Rendered lesson total exceeds 240 seconds")
            args += ["-t", f"{seconds:.3f}", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(clip)]
            _run(args)
            caption = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "").replace("\n", " ")
            cues.extend([f"{_stamp(elapsed)} --> {_stamp(elapsed + seconds)}", caption, ""])
            elapsed += seconds
        listing = tmp / "clips.txt"
        listing.write_text("".join(f"file '{i}.mp4'\n" for i in range(len(scenes))), encoding="utf-8")
        _run([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(tmp / "lesson.mp4")])
        (tmp / "captions.vtt").write_text("\n".join(cues) + "\n", encoding="utf-8")
        dest.mkdir(mode=0o700)
        try:
            for name in FORMATS:
                (tmp / name).replace(dest / name)
        except OSError:
            shutil.rmtree(dest)
            raise
    return {
        "kind": "video_lesson", "title": title, "scenes": scenes, "media_id": media_id,
        "video_url": f"/api/media/{media_id}/lesson.mp4",
        "subtitles_url": f"/api/media/{media_id}/captions.vtt",
        "subtitles_vtt": "\n".join(cues) + "\n",
        "duration_seconds": elapsed, "narration": provider, "renderer": "ffmpeg-slides",
    }
