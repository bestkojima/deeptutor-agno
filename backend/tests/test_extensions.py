import unittest
from unittest.mock import patch

from app.exam_blueprint import EXAMPLE_BLUEPRINT, deterministic_sample_exam, render_exam
from app.preview import confirmed_inputs, prepare_preview
from app.visualize import finalize_visual
from app.retrieval import local_retrieve, arxiv_retrieve, web_retrieve


class ExtensionTests(unittest.TestCase):
    def test_outline_is_bound_to_confirmation(self):
        preview = prepare_preview("research", {"prompt":"OCR"}, "fake", lambda *_:None)
        self.assertIn("OCR", preview["outline"][0])
        out = confirmed_inputs("research", preview, {"goal":"确认"})
        self.assertEqual(out["confirmed_outline"],preview["outline"])
        with self.assertRaises(ValueError):
            confirmed_inputs("research", preview, {"not_allowed":"确认"})

    def test_render_exam_separates_key(self):
        exam=deterministic_sample_exam(EXAMPLE_BLUEPRINT, 2)
        export=render_exam(exam)
        self.assertEqual(export["format"],"markdown")
        self.assertNotIn("参考答案",export["paper"])
        self.assertIn("参考答案",export["answer_key"])

    def test_visualize_chart_escape_and_unsupported(self):
        output=finalize_visual({"chart":{"labels":["<script>"],"values":[4]}})
        self.assertIn("&lt;script&gt;",output["svg"])
        self.assertNotIn("<script>",output["svg"])
        self.assertFalse(finalize_visual({"visualization":{"type":"manim","content":"class Example: pass"}})["rendered"])
        with self.assertRaises(ValueError): finalize_visual({"text":"prose only"})

    def test_retrieval_limits(self):
        self.assertEqual(local_retrieve("二次函数",[{"id":"1","text":"二次函数"},{"id":"2","text":"化学"}])[0]["id"],"1")
        with patch.dict("os.environ",{"TUTOR_ENABLE_ARXIV":"0","TUTOR_ENABLE_WEB":"0"}):
            for f in (arxiv_retrieve, web_retrieve):
                with self.assertRaises(RuntimeError): f("subject")
