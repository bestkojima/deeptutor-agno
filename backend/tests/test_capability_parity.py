"""Offline semantic assertions for the real, pinned Agno workflow."""
import importlib.util
import json
import os
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

from app.agno_adapter import Review, Plan, TutorOutput, run_agno
from app.preview import Card, confirmed_inputs


class ClarificationTests(TestCase):
    def test_allowed_choice_and_original_question_are_preserved(self):
        card = Card(id="audience", question="What grade?", type="single_choice",
                    options=["Grade 7", "Grade 9"])
        questions = {"questions": [card.model_dump()]}
        for answer in ({}, {"audience": "Grade 6"}, {"x": "Grade 9"}):
            with self.assertRaises(ValueError):
                confirmed_inputs("ask_questions", questions, answer)
        self.assertEqual(confirmed_inputs("ask_questions", questions, {"audience": "Grade 9"})["clarification"],
                         [{"question": "What grade?", "answer": "Grade 9"}])


@skipUnless(all(importlib.util.find_spec(p) for p in ("agno", "openai")), "Agno required")
class WorkflowParityTests(TestCase):
    def run_offline(self, capability, inputs, handler):
        from agno.agent import Agent
        events = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-placeholder-not-a-secret"}), \
                patch.object(Agent, "run", new=lambda agent, payload: SimpleNamespace(
                    content=handler(agent, json.loads(payload)))), \
                patch("socket.socket.connect", side_effect=AssertionError("Network disabled")):
            result = run_agno(capability, inputs, lambda kind, data: events.append((kind, data)))
        return result, events

    def test_resumed_ask_answers_original_prompt(self):
        def handler(agent, packet):
            if agent.name == "review":
                return Review(accepted=True, checks=["fits grade"])
            self.assertIn("Do not generate another card", str(agent.instructions))
            self.assertEqual(packet["request"]["prompt"], "Explain quadratics")
            self.assertEqual(packet["request"]["clarification"][0]["answer"], "Grade 9")
            return TutorOutput(text="A quadratic can be written as ax²+bx+c.")
        result, _ = self.run_offline("ask_questions", {
            "prompt": "Explain quadratics", "clarification": [{"question": "What grade?", "answer": "Grade 9"}]
        }, handler)
        self.assertIn("ax²", result["text"])
        self.assertNotIn("questions", result)

    def test_resumed_ask_rejects_a_second_card(self):
        def handler(agent, packet):
            if agent.name == "review":
                return Review(accepted=True, checks=[])
            return TutorOutput(text="Another question", data={"questions": ["Do you agree?"]})
        with self.assertRaisesRegex(ValueError, "another clarification"):
            self.run_offline("ask_questions", {"clarification": [{"question": "What grade?", "answer": "9"}]}, handler)

    def test_read_actions_only_accept_attached_verbatim_sources(self):
        def handler(agent, packet):
            if agent.name == "review":
                return Review(accepted=True, checks=["exact quote"])
            tools = {f.__name__: f for f in agent.tools}
            self.assertIn("error", json.loads(tools["read_excerpt"]("other")))
            self.assertIn("error", json.loads(tools["locate_excerpt"]("e1", "invented")))
            self.assertEqual(json.loads(tools["locate_excerpt"]("e1", "Exact words"))["start_seconds"], 3.0)
            return TutorOutput(text="An explanation", citations=[{"source_id": "e1", "quote": "Exact words"}])
        result, events = self.run_offline("immersive_reading", {"sources": [{
            "id": "e1", "text": "Exact words.", "start_seconds": 3.0, "end_seconds": 5.0}]}, handler)
        self.assertEqual(result["citations"][0]["end_seconds"], 5.0)
        self.assertEqual(len([k for k, _ in events if k == "reader.located"]), 1)

    def test_solve_uses_ordered_tools_and_retries_review(self):
        drafts = []
        def handler(agent, packet):
            if agent.name == "review":
                return Review(accepted=len(drafts) == 2, checks=["fixture"],
                              corrections=[] if len(drafts) == 2 else ["verify the substitution"])
            drafts.append(packet)
            if len(drafts) == 1:
                funcs = {f.__name__: f for f in agent.tools}
                funcs["solve_plan"]("Use substitution", [{"id": "s1", "goal": "Substitute"}])
                funcs["solve_finish_step"]("s1", "2 + 3 = 5")
            else:
                self.assertEqual(packet["retry_feedback"]["corrections"], ["verify the substitution"])
            return TutorOutput(text="The checked value is 5.")
        result, events = self.run_offline("solve", {"prompt": "What is 2+3?"}, handler)
        self.assertEqual(len(drafts), 2)
        self.assertTrue(result["solve_status"]["steps"][0]["done"])
        self.assertEqual([v["accepted"] for k,v in events if k == "solve.review"], [False, True])

    def test_solve_require_complete_even_if_reviewer_accepts(self):
        def handler(agent, packet):
            if agent.name == "review":
                return Review(accepted=True, checks=[])
            return TutorOutput(text="No completed steps")
        with self.assertRaisesRegex(ValueError, "every planned step"):
            self.run_offline("solve", {"prompt": "Do some work"}, handler)

    def test_visualize_only_accepts_valid_tool_submission(self):
        def handler(agent, packet):
            if agent.name == "review":
                self.assertEqual(packet["accepted_visualization"]["type"], "function_graph")
                return Review(accepted=True, checks=["graph accepted"])
            tool = {f.__name__: f for f in agent.tools}["submit_visualization"]
            self.assertFalse(tool({"type": "html", "content": "<h1>untrusted</h1>"})["accepted"])
            self.assertTrue(tool({"type": "function_graph", "content": {"curves": [
                {"function": "quadratic", "parameters": {"a": 1, "b": -4, "c": 3}}]}})["accepted"])
            return TutorOutput(text="A parabola")
        result, events = self.run_offline("visualize", {"prompt": "Plot a quadratic"}, handler)
        self.assertEqual(result["visualization"]["type"], "function_graph")
        self.assertIn("tool.failed", [k for k,_ in events])

    def test_research_partial_reports_missing_branch(self):
        def handler(agent, packet):
            if agent.name == "plan":
                return Plan(tasks=["Valid, cited branch", "Failed branch"])
            if agent.name == "research_evidence_02":
                raise ValueError("omit details")
            if agent.name == "review":
                return Review(accepted=True, checks=[])
            if agent.name == "answer":
                self.assertTrue(packet["outputs"]["evidence"]["data"]["partial"])
            return TutorOutput(text="Verified excerpt", citations=[{"source_id": "e", "quote": "Exact."}])
        result, _ = self.run_offline("research", {"prompt": "Investigate", "sources": [
            {"id": "e", "text": "Exact."}]}, handler)
        self.assertTrue(result["research_status"]["partial"])
        self.assertEqual(result["research_status"]["failed_branches"], ["research_evidence_02"])

    def test_research_with_all_branches_failed_cannot_synthesize(self):
        def handler(agent, packet):
            if agent.name == "plan":
                return Plan(tasks=["A branch"])
            if agent.name == "research_evidence_01":
                raise ValueError("fixture failure")
            self.fail("Synthesis must not run")
        with self.assertRaisesRegex(ValueError, "report withheld"):
            self.run_offline("research", {"sources": [{"id":"e", "text":"x."}]}, handler)
