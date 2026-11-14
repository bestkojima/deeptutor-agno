"""Actual Agno orchestration, with Agent.run mocked: no provider/network calls."""
import importlib.util
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.agno_adapter import calculate, run_agno, TutorOutput, Plan, Review
from app.exam_blueprint import EXAMPLE_BLUEPRINT, deterministic_sample_exam, validate_generated_exam

AGNO_AVAILABLE = all(importlib.util.find_spec(p) is not None for p in ('agno', 'openai'))

class ArithmeticTests(unittest.TestCase):
    def test_safe_and_unsafe_arithmetic(self):
        self.assertEqual(calculate('(2+3)*4'), 20)
        for value in ['__import__("os")', '2**99999', '[1][0]', 'True+1', '1e200*1e200']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate(value)

@unittest.skipUnless(AGNO_AVAILABLE, 'Install agno==2.3.21 and openai to run actual orchestration smoke tests')
class AgnoWorkflowTests(unittest.TestCase):
    def run_fixture(self, capability, inputs=None, rejected=False):
        from agno.agent import Agent
        events, names = [], []
        def respond(agent, payload, *args, **kwargs):
            names.append(agent.name)
            context = json.loads(payload)
            request = context['request']
            if agent.name in ('plan','quiz_plan'):
                content = Plan(tasks=['Check the supplied evidence'])
            elif agent.name in ('review','quiz_review'):
                content = Review(accepted=not rejected, checks=['fixture check'], corrections=['fixture rejection'] if rejected else [])
            else:
                citations = [{'source_id': s['id'], 'quote': s['text']} for s in request.get('sources', [])]
                data = {}
                if capability == 'quiz':
                    data = {'item': {'id': '1', 'question': '2+3?', 'options': ['4', '5'], 'answer_index': 1, 'explanation': '2+3=5'}}
                if capability == 'exam':
                    data = {'exam': deterministic_sample_exam(request['blueprint'], request['exam_contract']['seed'])}
                content = TutorOutput(text='offline fixture', citations=citations, data=data)
            return SimpleNamespace(content=content)
        # Fail loudly if a regression bypasses the mocked Agent boundary.
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder-not-a-secret'}), \
             patch.object(Agent, 'run', respond), \
             patch('socket.socket.connect', side_effect=AssertionError('Network forbidden in offline smoke test')):
            result = run_agno(capability, inputs or {'prompt': 'test'}, lambda kind, data: events.append((kind, data)))
        return result, names, events

    def test_chat_real_workflow(self):
        result, names, events = self.run_fixture('chat')
        self.assertEqual(names, ['answer', 'review'])
        self.assertEqual(result['kind'], 'chat')
        self.assertEqual([d['name'] for k, d in events if k == 'step.started'], names)

    def test_research_citations_and_stages(self):
        result, names, _ = self.run_fixture('research', {'prompt': 'evidence', 'sources': [{'id': 's1', 'text': 'Known evidence.', 'page': 4}]})
        self.assertEqual(names, ['plan', 'research_evidence_01', 'answer', 'review'])
        self.assertEqual(result['citations'][0]['page'], 4)
        self.assertEqual(result['citations'][0]['quote'], 'Known evidence.')

    def test_quiz_contract(self):
        result, _, _ = self.run_fixture('quiz', {'prompt': 'practice', 'quiz_count': 1})
        self.assertEqual(result['items'][0]['answer_index'], 1)

    def test_exam_canonical_contract(self):
        result, _, _ = self.run_fixture('exam', {'prompt': 'fresh exam', 'blueprint': EXAMPLE_BLUEPRINT, 'seed': 13})
        self.assertEqual(result['seed'], 13)
        self.assertEqual(validate_generated_exam(EXAMPLE_BLUEPRINT, result), result)
        self.assertNotIn('kind', result)

    def test_rejected_review_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'reviewer rejected'):
            self.run_fixture('chat', rejected=True)

if __name__ == '__main__':
    unittest.main()
