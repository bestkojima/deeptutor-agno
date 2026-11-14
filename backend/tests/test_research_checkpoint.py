import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.research_checkpoint import ResearchCheckpointStore
from app.agno_adapter import run_agno, Plan, TutorOutput, Review

class ResearchCheckpointTests(unittest.TestCase):
    def test_resume_reuses_verified_branch_and_plan(self):
        from agno.agent import Agent
        inputs = {'prompt': 'research', 'confirmed_outline': ['A', 'B'], 'sources': [{'id': 's', 'text': 'evidence'}]}
        calls = []
        attempt = [0]
        def model(agent, payload, *args, **kwargs):
            calls.append(agent.name)
            if agent.name == 'plan': return SimpleNamespace(content=Plan(tasks=['A', 'B']))
            if agent.name == 'research_evidence_02' and attempt[0] == 0: raise RuntimeError('synthetic failure')
            if agent.name == 'review':
                return SimpleNamespace(content=Review(accepted=attempt[0] > 0, checks=['fixture'], corrections=['retry review']))
            return SimpleNamespace(content=TutorOutput(text='evidence', citations=[{'source_id': 's', 'quote': 'evidence'}]))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(Agent, 'run', model), patch('socket.socket.connect', side_effect=AssertionError('No network')):
            path = Path(tmp)/'tasks.db'
            store = ResearchCheckpointStore(path, 'same-task', inputs)
            with self.assertRaises(ValueError): run_agno('research', inputs, lambda *a: None, research_checkpoint=store)
            state = ResearchCheckpointStore(path, 'same-task', inputs).load()
            self.assertEqual(state['branches']['research_evidence_01']['status'], 'completed')
            self.assertEqual(state['branches']['research_evidence_02']['status'], 'failed')
            calls.clear(); attempt[0] = 1
            result = run_agno('research', inputs, lambda *a: None, research_checkpoint=ResearchCheckpointStore(path, 'same-task', inputs))
            self.assertEqual(calls, ['research_evidence_02', 'answer', 'review'])
            self.assertFalse(result['research_status']['partial'])
            self.assertNotIn('offline-placeholder', path.read_bytes().decode(errors='ignore'))

    def test_interrupted_pending_branch_restores_retrieved_sources(self):
        from agno.agent import Agent
        inputs = {'prompt': 'research', 'confirmed_outline': ['A', 'B'], 'use_web': True}
        retrieved = {'id': 'web-s', 'text': 'retrieved evidence', 'url': 'https://example.org/paper'}
        calls = []
        def model(agent, payload, *args, **kwargs):
            calls.append(agent.name)
            packet = json.loads(payload)
            self.assertIn(retrieved, packet['request']['sources'])
            if agent.name == 'review':
                return SimpleNamespace(content=Review(accepted=True, checks=['fixture']))
            return SimpleNamespace(content=TutorOutput(text='evidence', citations=[{'source_id': 'web-s', 'quote': 'retrieved evidence'}]))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(Agent, 'run', model), patch('socket.socket.connect', side_effect=AssertionError('No network')):
            path = Path(tmp)/'tasks.db'
            store = ResearchCheckpointStore(path, 'same-task', inputs)
            store.save_plan({'tasks': ['A', 'B']})
            store.save_branch({'name': 'research_evidence_01', 'task': 'A', 'status': 'completed', 'gaps': [], 'evidence': {'text': 'evidence', 'citations': [{'source_id': 'web-s', 'quote': 'retrieved evidence'}]}}, [retrieved])
            # Process disappeared before B: absence of a branch record means pending.
            result = run_agno('research', inputs, lambda *a: None, research_checkpoint=ResearchCheckpointStore(path, 'same-task', inputs))
            self.assertEqual(calls, ['research_evidence_02', 'answer', 'review'])
            self.assertEqual(result['retrieved_sources'], [retrieved])

    def test_all_failed_checkpoint_does_not_generate_report(self):
        from agno.agent import Agent
        inputs = {'confirmed_outline': ['A'], 'sources': [{'id': 's', 'text': 'evidence'}]}
        calls = []
        def model(agent, *args, **kwargs):
            calls.append(agent.name)
            if agent.name == 'plan': return SimpleNamespace(content=Plan(tasks=['A']))
            raise RuntimeError('synthetic failure')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(Agent, 'run', model), patch('socket.socket.connect', side_effect=AssertionError('No network')):
            path = Path(tmp)/'tasks.db'
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'report withheld'):
                    run_agno('research', inputs, lambda *a: None, research_checkpoint=ResearchCheckpointStore(path, 'task', inputs))
            self.assertEqual(calls, ['plan', 'research_evidence_01', 'research_evidence_01'])

    def test_eligibility_binding_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'tasks.db'
            with self.assertRaises(ValueError): ResearchCheckpointStore(path, 'task', {'prompt': 'x'})
            inputs = {'confirmed_outline': ['A']}
            store = ResearchCheckpointStore(path, 'task', inputs)
            store.save_plan({'tasks': ['A']})
            with self.assertRaises(ValueError): ResearchCheckpointStore(path, 'task', {'confirmed_outline': ['B']})
            record = {'name': 'research_evidence_01', 'task': 'A', 'status': 'completed', 'gaps': [], 'evidence': {'text': 'invented', 'citations': [{'source_id': 's', 'quote': 'invented'}]}}
            with self.assertRaises(ValueError): store.save_branch(record, [{'id': 's', 'text': 'actual'}])
            self.assertEqual(store.load()['branches'], {})

if __name__ == '__main__': unittest.main()
