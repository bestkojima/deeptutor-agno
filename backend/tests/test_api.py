import os,tempfile,time,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import main
class ApiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); main.DB=Path(self.tmp.name)/'test.db'
  self.client=TestClient(main.app); self.client.__enter__()
 def tearDown(self):
  self.client.__exit__(None,None,None); self.tmp.cleanup()
 def wait(self,id,states=('completed','failed','paused')):
  for _ in range(100):
   task=self.client.get('/api/tasks/'+id).json()
   if task['status'] in states:return task
   time.sleep(.02)
  self.fail('timeout')
 def test_solve_and_sse_replay(self):
  id=self.client.post('/api/tasks',json={'capability':'solve','inputs':{'prompt':'2+3'}}).json()['id']
  self.assertEqual(self.wait(id)['result']['text'],'5')
  content=self.client.get('/api/tasks/'+id+'/events').text
  self.assertIn('event: tool.completed',content);self.assertIn('event: run.completed',content)
 def test_pause_resume_and_conflict(self):
  id=self.client.post('/api/tasks',json={'capability':'ask_questions','inputs':{'prompt':'fractions'}}).json()['id']
  self.assertEqual(self.wait(id)['status'],'paused')
  self.assertEqual(self.client.post('/api/tasks/'+id+'/resume',json={'answers':{'goal':'practice'}}).status_code,202)
  self.assertEqual(self.wait(id,('completed','failed'))['status'],'completed')
  self.assertEqual(self.client.post('/api/tasks/'+id+'/resume',json={'answers':{'goal':'again'}}).status_code,409)
 def test_bad_tool(self):
  self.assertEqual(self.client.post('/api/tasks',json={'capability':'chat','inputs':{'tools':['shell']}}).status_code,422)
 def test_exam(self):
  from app.exam_blueprint import EXAMPLE_BLUEPRINT
  id=self.client.post('/api/tasks',json={'capability':'exam','inputs':{'blueprint':EXAMPLE_BLUEPRINT,'seed':3}}).json()['id']
  self.assertEqual(self.wait(id)['status'],'completed')
 def test_caption_ingestion_api(self):
  response=self.client.post('/api/sources/captions?filename=demo.vtt',
      content=b'WEBVTT\n\n00:00:03.000 --> 00:00:05.000\nExact words.\n')
  self.assertEqual(response.status_code,200,response.text)
  self.assertIs(response.json()['transcribed'],False)
  self.assertEqual(response.json()['sources'][0]['start_seconds'],3)
  self.assertEqual(self.client.post('/api/sources/captions?filename=demo.mp4',content=b'unsupported').status_code,422)
 def test_graph_recompute_api(self):
  spec={'domain':[0,4],'samples':5,
        'curves':[{'function':'quadratic','parameters':{'a':1,'b':-4,'c':3}}]}
  response=self.client.post('/api/visualize/plot',json=spec)
  self.assertEqual(response.status_code,200,response.text)
  self.assertIn('<svg',response.json()['svg'])
  self.assertEqual(self.client.post('/api/visualize/plot',json={'curves':[{'function':'eval'}]}).status_code,422)
 def test_failed_solve(self):
  id=self.client.post('/api/tasks',json={'capability':'solve','inputs':{'prompt':'__import__("os")'}}).json()['id']
  self.assertEqual(self.wait(id)['status'],'failed')
if __name__=='__main__':unittest.main()
