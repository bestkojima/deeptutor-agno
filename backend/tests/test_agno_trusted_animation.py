"""The renderer accepts animation configuration only from the task request."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.agno_adapter import run_agno, TutorOutput, Review

class TrustedAnimationTests(unittest.TestCase):
    def test_model_animation_is_removed_and_request_animation_wins(self):
        from agno.agent import Agent
        def respond(agent, *args, **kwargs):
            if agent.name == 'review':
                return SimpleNamespace(content=Review(accepted=True, checks=['fixture']))
            return SimpleNamespace(content=TutorOutput(text='lesson', data={'scenes': [{'text': 'hello', 'duration_seconds': 1}], 'animation': {'untrusted': True}}))
        for requested in (None, {'type': 'fixture'}):
            with self.subTest(requested=requested), patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(Agent, 'run', respond), patch('socket.socket.connect', side_effect=AssertionError('No network')), patch('app.media.build_lesson', return_value={'renderer': 'offline-fixture'}) as render:
                inputs = {'prompt': 'lesson'}
                if requested is not None: inputs['animation'] = requested
                run_agno('video_lesson', inputs, lambda *a: None)
                packet = render.call_args.args[0]
                if requested is None: self.assertNotIn('animation', packet)
                else: self.assertEqual(packet['animation'], requested)

if __name__ == '__main__': unittest.main()
