import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import media
from app.math_lesson_media import validate_animation, sample_quadratic, probe_video


class MathLessonTests(unittest.TestCase):
    def test_exact_quadratic_and_derivative(self):
        rows = sample_quadratic({'template':'quadratic_trace','a':2,'b':-3,'c':1,'domain':[-1,1]}, 3)
        self.assertEqual(rows, [(-1,6,-7),(0,1,-3),(1,0,1)])

    def test_bounds(self):
        base={'template':'quadratic_trace'}
        for change in ({'template':'exec'}, {'code':'print(1)'}, {'a':True}, {'a':0},
                       {'a':float('nan')}, {'a':10**500}, {'domain':[1,1]},
                       {'domain':[-11,1]}, {'duration_seconds':1}, {'duration_seconds':2.5}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_animation({**base, **change})
        with self.assertRaises(ValueError):
            media.build_lesson({'animation':base,'tts':'edge'})

    def test_probe_rejects_incorrect_media(self):
        with self.assertRaises(RuntimeError):
            probe_video(Path('unused'),duration=2,ffprobe='unused',runner=lambda _: '{"streams":[]}')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and Path(media.DEFAULT_FONT).exists(), 'Existing media tools unavailable')
    def test_actual_animation_captions_and_failed_revision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(media, 'ARTIFACTS', Path(tmp)):
            request={'animation':{'template':'quadratic_trace','duration_seconds':2}}
            result=media.build_lesson(request)
            self.assertEqual(result['verification']['frames'],24)
            self.assertEqual(result['verification']['codec'],'h264')
            self.assertIn('00:00:01.000 --> 00:00:02.000',result['subtitles_vtt'])
            path=media.resolve_media(result['media_id'],'lesson.mp4')
            hashes=media._run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(path), '-f', 'framemd5', '-'])
            hashes=[line.rsplit(',',1)[-1].strip() for line in hashes.splitlines() if not line.startswith('#') and line.strip()]
            self.assertEqual(len(hashes),24)
            self.assertGreater(len(set(hashes)),1, 'Animation frames must change, not a static slide')
            old=path.read_bytes()
            # Rendering a revision fails: old immutable media remains, no fake fallback returned.
            with patch.object(media, '_run', side_effect=RuntimeError('simulated failure')):
                with self.assertRaises(RuntimeError): media.build_lesson(request)
            self.assertEqual(path.read_bytes(),old)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [result['media_id']])


if __name__ == '__main__': unittest.main()
