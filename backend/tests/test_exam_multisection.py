"""Offline API acceptance with a synthetic blueprint, not a real exam."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main
from app.exam_blueprint import EXAMPLE_BLUEPRINT


class MultiSectionExamTest(TestCase):
    def test_normal_exam_preserves_structure_without_memory(self):
        bp = deepcopy(EXAMPLE_BLUEPRINT)
        bp.update(title="Synthetic structural fixture", total_points=22)
        bp["sections"][0]["duration_minutes"] = 10
        bp["sections"].append({
            "id": "B", "title": "Written", "instructions": "Show your work.",
            "duration_minutes": 20, "style_descriptors": [],
            "slots": [
                {"number": "1", "type": "fill_blank", "points": 4, "choice_labels": [],
                 "style_descriptors": [], "source_stem": "Fill in the constant."},
                {"number": "2", "type": "short_answer", "points": 8, "choice_labels": [],
                 "style_descriptors": [], "source_stem": "Explain the calculation."},
            ],
        })
        with TemporaryDirectory() as tmp, patch.object(main, "DB", Path(tmp) / "runs.db"):
            with TestClient(main.app) as client:
                submit = client.post("/api/tasks", json={
                    "capability": "exam", "provider": "fake", "inputs": {"blueprint": bp, "seed": 42},
                })
                self.assertEqual(submit.status_code, 202, submit.text)
                url = "/api/tasks/" + submit.json()["id"]
                deadline = monotonic() + 2
                while monotonic() < deadline:
                    task = client.get(url).json()
                    if task["status"] in ("completed", "failed"):
                        break
                    sleep(.02)
                self.assertEqual(task["status"], "completed", task)
                exam = task["result"]
                events = client.get(url + "/events").text

        self.assertEqual(exam["total_points"], 22)
        self.assertEqual(exam["duration_minutes"], 30)
        self.assertEqual([
            (s["id"], i["number"], i["type"], i["points"])
            for s in exam["sections"] for i in s["items"]
        ], [("A", "1", "single_choice", 10), ("B", "1", "fill_blank", 4),
            ("B", "2", "short_answer", 8)])
        self.assertEqual([(a["section_id"], a["number"]) for a in exam["answer_key"]],
                         [("A", "1"), ("B", "1"), ("B", "2")])
        self.assertIn("event: run.completed", events)
