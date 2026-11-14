import unittest
from app.solve_workflow import SolveState, make_solve_tools


def steps(*ids):
    return [{'id': sid, 'goal': 'Resolve ' + sid} for sid in ids]


class SolveStateTests(unittest.TestCase):
    def test_order_and_completion_gate(self):
        state = SolveState()
        with self.assertRaises(ValueError): state.require_complete()
        state.plan('analyze', steps('a', 'b'))
        with self.assertRaises(ValueError): state.finish_step('b', 'done')
        with self.assertRaises(ValueError): state.plan('reset', steps('x'))
        with self.assertRaises(ValueError): state.require_complete()
        checkpoint = state.finish_step('a', 'Checked the premise')
        self.assertEqual(checkpoint['_context_checkpoint']['state']['next_step_id'], 'b')
        with self.assertRaises(ValueError): state.finish_step('a', 'repeat')
        state.finish_step('b', 'Verified result')
        self.assertTrue(state.require_complete()['complete'])
        with self.assertRaises(ValueError): state.replan('more', steps('c'))

    def test_replan_preserves_prefix_and_budget(self):
        state = SolveState()
        state.plan('initial', steps('a', 'b'))
        state.finish_step('a', 'Evidence retained')
        state.replan('new approach', steps('c', 'd'))
        state.replan('refine', steps('e'))
        before = state.snapshot()
        with self.assertRaises(ValueError): state.replan('third', steps('f'))
        self.assertEqual(state.snapshot(), before)
        self.assertEqual(state.steps[0]['summary'], 'Evidence retained')
        state.finish_step('e', 'Checked')
        self.assertTrue(state.complete)

    def test_rejected_requests_atomic(self):
        state = SolveState(max_steps=2)
        state.plan('initial', steps('a', 'b'))
        state.finish_step('a', 'done')
        before = state.snapshot()
        for replacement in [steps('a'), steps('x', 'y'), steps('x', 'x'), [], [{'id': 'x', 'goal': ''}]]:
            with self.assertRaises(ValueError): state.replan('reason', replacement)
            self.assertEqual(state.snapshot(), before)
        with self.assertRaises(ValueError): state.finish_step('b', '')
        self.assertEqual(state.snapshot(), before)

    def test_isolation_and_snapshot_copy(self):
        a, b = SolveState(), SolveState()
        a.plan('a', steps('a'))
        a.replan('change', steps('b'))
        self.assertEqual(b.replans, 0)
        self.assertEqual(b.steps, [])
        snap = a.snapshot()
        snap['steps'][0]['done'] = True
        self.assertFalse(a.complete)

    def test_tools_events_and_error_feedback(self):
        state, events = SolveState(), []
        plan, finish, replan = make_solve_tools(state, lambda k, d: events.append((k, d)))
        plan('initial', steps('a'))
        with self.assertRaises(ValueError): finish('wrong', 'done')
        self.assertEqual(events[-1][0], 'tool.failed')
        finish('a', 'Verified')
        self.assertEqual(events[-1][0], 'tool.completed')
        self.assertTrue(state.require_complete()['complete'])

    def test_limits_and_empty_plan(self):
        for kwargs in [{'max_replans': -1}, {'max_steps': 0}, {'max_replans': True}]:
            with self.assertRaises(ValueError): SolveState(**kwargs)
        state = SolveState()
        for invalid in [[], steps(*map(str, range(13))), steps('a', 'a')]:
            with self.assertRaises(ValueError): state.plan('bad', invalid)
            self.assertEqual(state.steps, [])

if __name__ == '__main__':
    unittest.main()
