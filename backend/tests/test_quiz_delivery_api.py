"""Public API/SSE acceptance tests for root-owned delivery integration."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main

SECRET='PRIVATE-SOLUTION-8aef'
def generated_item():return {'id':'model-id','question':'Which value is two?','options':['one','two'],'answer_index':1,'explanation':SECRET}
def fake_partial(capability,inputs,emit):
    emit('quiz.question.emitted',{'position':1,'item':generated_item(),'review':{'corrections':[SECRET]}})
    emit('tool.completed',{'output':SECRET})
    emit('quiz.question.failed',{'position':2,'corrections':[SECRET]})
    return {'kind':'quiz','items':[generated_item()],'text':SECRET,'quiz_status':{'status':'partial','requested':2,'successful':1,'failed':1,'outcomes':[{'corrections':[SECRET]}]}}

class QuizDeliveryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old_db=main.DB;main.DB=Path(self.tmp.name)/'runs.db'
        self.client=TestClient(main.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);main.DB=self.old_db;self.tmp.cleanup()
    def create(self,runner=fake_partial):
        with patch.object(main,'fake_run',side_effect=runner):
            response=self.client.post('/api/tasks',json={'capability':'quiz','provider':'fake','inputs':{}})
            self.assertEqual(response.status_code,202,response.text);task_id=response.json()['id']
            for _ in range(200):
                task=self.client.get('/api/tasks/'+task_id).json()
                if task['status'] in ('completed','failed'):return task_id,task
                time.sleep(.01)
            self.fail('task timed out')
    def test_issued_item_available_while_later_work_is_running(self):
        import threading
        issued=threading.Event();release=threading.Event()
        def runner(capability,inputs,emit):
            emit('quiz.question.emitted',{'position':1,'item':generated_item()})
            issued.set();release.wait(3)
            emit('quiz.question.failed',{'position':2,'corrections':[SECRET]})
            return {'kind':'quiz','items':[generated_item()],'quiz_status':{'status':'partial','requested':2,'successful':1,'failed':1}}
        with patch.object(main,'fake_run',side_effect=runner):
            task_id=self.client.post('/api/tasks',json={'capability':'quiz','provider':'fake','inputs':{}}).json()['id']
            try:
                self.assertTrue(issued.wait(2))
                task=self.client.get('/api/tasks/'+task_id).json()
                self.assertEqual(task['status'],'running')
                self.assertEqual(len(task['result']['items']),1)
                self.assertNotIn(SECRET,json.dumps(task))
            finally:
                release.set()
                for _ in range(200):
                    if self.client.get('/api/tasks/'+task_id).json()['status'] in ('completed','failed'):break
                    time.sleep(.01)

    def test_partial_result_and_sse_hide_keys_before_submit(self):
        task_id,task=self.create();self.assertEqual(len(task['result']['items']),1)
        self.assertNotIn(SECRET,json.dumps(task));self.assertNotIn('answer_index',json.dumps(task))
        events=self.client.get('/api/tasks/'+task_id+'/events').text
        self.assertIn('quiz.question.emitted',events);self.assertNotIn(SECRET,events);self.assertNotIn('answer_index',events)
    def test_score_feedback_after_submission(self):
        task_id,task=self.create();item_id=task['result']['items'][0]['id']
        response=self.client.post('/api/tasks/'+task_id+'/quiz/submit',json={'answers':{item_id:1}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['feedback'][0]['status'],'correct');self.assertIn(SECRET,response.text)
    def test_late_exception_preserves_item_and_sanitizes_error(self):
        def explode(capability,inputs,emit):
            fake_partial(capability,inputs,emit);raise RuntimeError(SECRET)
        task_id,task=self.create(explode)
        self.assertEqual(task['status'],'failed');self.assertIsNotNone(task['result'])
        self.assertEqual(len(task['result']['items']),1);self.assertNotIn(SECRET,json.dumps(task))
        self.assertNotIn(SECRET,self.client.get('/api/tasks/'+task_id+'/events').text)

if __name__=='__main__':unittest.main()
