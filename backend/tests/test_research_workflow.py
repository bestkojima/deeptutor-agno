"""Offline real-Agno fan-out tests; provider callback is a local fixture."""
import importlib.util
import threading
import unittest
from unittest.mock import patch
from app.research_workflow import research_evidence_stage, split_research_plan


class PlanTests(unittest.TestCase):
    def test_bounds_and_stable_deduplication(self):
        self.assertEqual(split_research_plan({'tasks': [' A ', 'B', 'A']}),
                         [{'name': 'research_evidence_01', 'task': 'A'}, {'name': 'research_evidence_02', 'task': 'B'}])
        for tasks in ([], ['a'] * 7, [''], ['x' * 4001], [1], 'abc'):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                split_research_plan({'tasks': tasks})

    def test_context_and_outline(self):
        self.assertEqual(split_research_plan({'outputs': {'plan': {'tasks': ['A']}}})[0]['task'], 'A')
        self.assertEqual(len(split_research_plan({'request': {'confirmed_outline': 'A\nB'}})), 2)


@unittest.skipUnless(importlib.util.find_spec('agno'), 'Agno not installed')
class ParallelTests(unittest.TestCase):
    def test_real_parallel_stable_aggregation_and_gaps(self):
        barrier = threading.Barrier(3)
        events = []
        def run(name, task):
            barrier.wait(timeout=5)  # Would fail if execution were sequential.
            if task == 'B':
                raise RuntimeError('secret should not reach output')
            return {'text': task, 'citations': [{'source_id': 's', 'quote': 'evidence'}],
                    'limitations': ['Needs more evidence'] if task == 'C' else []}
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            result = research_evidence_stage({'tasks': ['A', 'B', 'C']}, run, lambda k,d: events.append((k,d)))
        self.assertEqual([b['task'] for b in result['data']['branches']], ['A', 'B', 'C'])
        self.assertEqual([b['status'] for b in result['data']['branches']], ['completed', 'failed', 'partial'])
        self.assertEqual(len(result['citations']), 1)
        self.assertTrue(result['data']['partial'])
        self.assertFalse(result['data']['all_failed'])
        self.assertNotIn('secret should', str(result) + str(events))
        self.assertEqual(sum(k == 'step.started' for k,d in events), 3)

    def test_no_citations_and_malformed_output(self):
        result = research_evidence_stage({'tasks': ['A']}, lambda *args: {'text': 'uncited'}, lambda *args: None)
        self.assertTrue(result['data']['partial'])
        self.assertFalse(result['data']['all_failed'])
        result = research_evidence_stage({'tasks': ['A']}, lambda *args: None, lambda *args: None)
        self.assertTrue(result['data']['all_failed'])
        self.assertEqual(result['citations'], [])


    def test_resume_retries_partial_and_retains_verified_evidence_on_failure(self):
        plan={'tasks':['A']}
        initial=research_evidence_stage(plan, lambda *_: {
            'text':'Partial evidence', 'citations':[{'source_id':'s','quote':'known'}],
            'limitations':['Need more evidence'],
        }, lambda *_: None)
        cached=initial['data']['branches'][0]
        calls=[]
        def retry(name,task):
            calls.append(task)
            raise RuntimeError('fixture failure')
        resumed=research_evidence_stage(plan,retry,lambda *_: None,completed_branches={cached['name']:cached})
        self.assertEqual(calls,['A'])
        self.assertEqual(resumed['citations'],initial['citations'])
        self.assertTrue(resumed['data']['partial'])


if __name__ == '__main__':
    unittest.main()
