import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import media


class LessonMediaTests(unittest.TestCase):
    def test_reject_invalid_inputs_and_filenames(self):
        for invalid in ({}, {"scenes": [{"text": "a", "duration_seconds": float("nan")}]},
                        {"scenes": [{"text": "a", "duration_seconds": 46}]}):
            with self.assertRaises(ValueError):
                media.build_lesson(invalid)
        for media_id, name in (("../escape", "lesson.mp4"), ("a" * 32, "../x")):
            with self.assertRaises(FileNotFoundError):
                media.resolve_media(media_id, name)

    def test_edge_requires_operator_opt_in(self):
        with patch.dict("os.environ", {"TUTOR_ENABLE_EDGE_TTS": "0"}):
            with self.assertRaises(ValueError):
                media.build_lesson({"scenes": [{"text": "a"}], "tts": {"provider": "edge"}})

    @unittest.skipUnless(shutil.which("ffmpeg") and Path(media.DEFAULT_FONT).exists(), "FFmpeg/CJK font unavailable")
    def test_two_scene_video(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(media, "ARTIFACTS", Path(temp)):
            out = media.build_lesson({"title": "课程", "scenes": [
                {"text": "认识抛物线。", "duration_seconds": 1},
                {"text": "写出对称轴。", "duration_seconds": 1}]})
            self.assertEqual(out["duration_seconds"], 2)
            self.assertIn("00:00:01.000 --> 00:00:02.000", out["subtitles_vtt"])
            self.assertGreater(media.resolve_media(out["media_id"], "lesson.mp4").stat().st_size, 512)


if __name__ == "__main__":
    unittest.main()
