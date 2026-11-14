"""Task API acceptance for research recovery and last-good video media."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest import TestCase
from unittest.mock import patch
import os
import shutil

from fastapi.testclient import TestClient
from app import main, media


class ContinuationAPITests(TestCase):
    def setUp(self):
        temporary=self.enterContext(TemporaryDirectory())
        root=Path(temporary)
        self.enterContext(patch.object(main,'DB',root/'app.sqlite3'))
        self.enterContext(patch.object(media,'ARTIFACTS',root/'media'))
        self.client=self.enterContext(TestClient(main.app))

    def wait(self,url,states):
        deadline=monotonic()+20
        while monotonic()<deadline:
            task=self.client.get(url).json()
            if task['status'] in states:return task
            sleep(.03)
        self.fail('Timed out')

    def test_confirmed_research_resumes_original_task_after_restart(self):
        preview={'questions':[{'id':'goal','question':'Confirm outline','required':True,'type':'text'}],
                 'outline':['Check excerpt'],'context':'Research'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'offline-only'}), patch.object(
            main.importlib.util,'find_spec',return_value=object()), patch.object(main,'prepare_preview',return_value=preview):
            response=self.client.post('/api/tasks',json={'capability':'research','provider':'agno',
                'inputs':{'prompt':'Research','sources':[{'id':'1','text':'A source.'}]}})
            self.assertEqual(response.status_code,202,response.text)
            url='/api/tasks/'+response.json()['id']
            self.assertEqual(self.wait(url,{'paused'})['status'],'paused')
            with patch.object(main,'launch'):
                self.assertEqual(self.client.post(url+'/resume',json={'answers':{'goal':'confirm'}}).status_code,202)
            main.init_db()  # Simulate a restart before the scheduled worker starts.
            meta=self.client.get(url).json()
            self.assertEqual(meta['status'],'interrupted')
            self.assertTrue(meta['can_resume_research'])
            self.assertIn('event: research.interrupted',self.client.get(url+'/events').text)
            with patch.object(main,'launch') as launch:
                resp=self.client.post(url+'/resume',json={'answers':{}})
                self.assertEqual(resp.status_code,202)
                self.assertEqual(resp.json()['id'],response.json()['id'])
                self.assertEqual(self.client.post(url+'/resume',json={'answers':{}}).status_code,409)
                launch.assert_called_once_with(response.json()['id'])

    def test_first_animation_failure_does_not_return_a_fake_result(self):
        with patch.object(media,'build_lesson',side_effect=RuntimeError('fixture encoder failure')):
            response=self.client.post('/api/tasks',json={'capability':'video_lesson','inputs':{
                'animation':{'template':'quadratic_trace','duration_seconds':2}}})
            task=self.wait('/api/tasks/'+response.json()['id'],{'completed','failed'})
            self.assertEqual(task['status'],'failed')
            self.assertIsNone(task['result'])

    def test_video_revision_failure_keeps_previous_playable_media(self):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('FFmpeg+ffprobe required')
        animation={'template':'quadratic_trace','a':1,'duration_seconds':2}
        result=self.client.post('/api/tasks',json={'capability':'video_lesson','inputs':{'animation':animation}})
        url='/api/tasks/'+result.json()['id']
        task=self.wait(url,{'completed','failed'})
        self.assertEqual(task['status'],'completed',task)
        before=task['result']
        data=self.client.get(before['video_url']).content
        self.assertIn(b'ftyp',data[:20])
        self.assertIn('00:00:02.000',self.client.get(before['subtitles_url']).text)
        with patch.object(media,'build_lesson',side_effect=RuntimeError('fixture encoder failure')):
            revised=self.client.post(url+'/video/revise',json={'animation':{**animation,'a':2}})
            self.assertEqual(revised.status_code,202,revised.text)
            after=self.wait(url,{'completed','failed'})
        self.assertEqual(after['result']['video_url'],before['video_url'])
        self.assertEqual(after['result']['revision_status'],'failed')
        self.assertIs(after['result']['fallback_used'],True)
        self.assertEqual(self.client.get(before['video_url']).content,data)


    def test_event_replay_crosses_page_and_returns_single_terminal_frame(self):
        def emit_many(capability, inputs, emit):
            for i in range(280): emit('step.completed',{'index':i})
            return {'text':'done'}
        with patch.object(main,'fake_run',side_effect=emit_many):
            response=self.client.post('/api/tasks',json={'capability':'chat'})
            url='/api/tasks/'+response.json()['id']
            self.assertEqual(self.wait(url,{'completed','failed'})['status'],'completed')
            events=self.client.get(url+'/events').text
        self.assertEqual(events.count('event: step.completed'),280)
        self.assertEqual(events.count('event: run.completed'),1)
        self.assertIn('event: result',events)
        ids=[int(line[4:]) for line in events.splitlines() if line.startswith('id: ')]
        self.assertEqual(ids,sorted(set(ids)))
        tail=self.client.get(url+'/events',headers={'Last-Event-ID':str(ids[-2])}).text
        self.assertEqual(tail.count('event: run.completed'),1)
        self.assertNotIn('event: result',tail)
