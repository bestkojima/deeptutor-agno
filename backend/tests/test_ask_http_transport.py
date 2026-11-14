"""API + SSE verification at the OpenAI HTTP seam; never opens a network socket."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic,sleep
from unittest import TestCase, skipUnless
from unittest.mock import patch
from importlib.util import find_spec
import json, os
import httpx
from fastapi.testclient import TestClient
from app import main


fixture_calls=[]
def result(payload, message, finish='stop'):
    return httpx.Response(200, json={'id':'chatcmpl-offline','object':'chat.completion','model':payload['model'],
        'created':1,'choices':[{'index':0,'finish_reason':finish,'message':{'role':'assistant',**message}}],
        'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}})
def response(request):
    assert request.url == httpx.URL('https://api.openai.com/v1/chat/completions')
    payload=json.loads(request.content)
    assert payload['model']=='gpt-6-luna'
    if payload.get('tools'):
        assert payload.get('reasoning_effort')=='none'
    messages=payload['messages']
    fixture_calls.append(messages)
    alltext=json.dumps(messages,ensure_ascii=False)
    if 'Ask only targeted clarification' in alltext:
        return result(payload,{'content':json.dumps({'questions':[{'id':'goal','question':'Which grade?', 'required':True, 'type':'single_choice','options':['Grade 9','Grade 10']}]})})
    if 'Independently review' in alltext:
        return result(payload,{'content':json.dumps({'accepted':True,'checks':['supports the request'],'corrections':[]})})
    tools=[m for m in messages if m.get('role')=='tool']
    if not tools:
        assert any(x['function']['name']=='calculator' for x in payload['tools'])
        return result(payload,{'content':None,'tool_calls':[{'id':'c1','type':'function','function':{
            'name':'calculator','arguments':json.dumps({'expression':'2**3' if 'try unsupported' in alltext else '7*9+3'})}}]},'tool_calls')
    if 'try unsupported' in alltext:
        assert any('Unsupported' in m.get('content','') for m in tools)
        content={'text':'The calculator could not run that expression.','data':{},'citations':[],'limitations':[]}
    else:
        assert any('66' in m.get('content','') for m in tools)
        if 'original word problem' in alltext: assert 'Grade 9' in alltext
        content={'text':'The requested result is 66.','data':{},'citations':[],'limitations':[]}
    return result(payload,{'content':json.dumps(content)})
def wait(client,url,terminal):
    deadline=monotonic()+12
    while monotonic()<deadline:
        task=client.get(url).json()
        if task['status'] in terminal: return task
        sleep(.03)
    raise RuntimeError('timeout')
def verify(client):
    for mode,prompt in [('ask_questions','original word problem, ask grade first and then calculate 7*9+3'),('chat','try unsupported arithmetic 2**3 using the tool')]:
        r=client.post('/api/tasks',json={'capability':mode,'provider':'agno','inputs':{'tools':['calculator'],'prompt':prompt}})
        assert r.status_code==202,r.text
        url='/api/tasks/'+r.json()['id']
        if mode=='ask_questions':
            assert wait(client,url,{'paused','failed'})['status']=='paused'
            r=client.post(url+'/resume',json={'answers':{'goal':'Grade 9'}})
            assert r.status_code==202,r.text
            assert client.post(url+'/resume',json={'answers':{'goal':'Grade 9'}}).status_code==409
        state=wait(client,url,{'completed','failed'})
        assert state['status']=='completed',state
        assert ('66' if mode=='ask_questions' else 'could not') in state['result']['text']
        events=client.get(url+'/events').text
        assert 'event: tool.started' in events
        assert ('event: tool.completed' if mode=='ask_questions' else 'event: tool.failed') in events
        assert events.count('event: question\n')==int(mode=='ask_questions')

@skipUnless(find_spec('agno') and find_spec('openai'), 'Agno transport dependencies required')
class AskTransportTests(TestCase):
    def test_ask_resume_and_tool_failure_on_real_agno_intercepted_http(self):
        from agno.models.openai import OpenAIChat
        from openai import OpenAI
        fixture_calls.clear()
        with TemporaryDirectory() as tmp, httpx.Client(transport=httpx.MockTransport(response)) as model_http, \
            patch.object(main,'DB',Path(tmp)/'runs.sqlite3'),patch.object(OpenAIChat,'get_client',lambda _:OpenAI(api_key='offline-http-fixture',base_url='https://api.openai.com/v1',http_client=model_http,max_retries=0)), \
            patch.dict(os.environ,{'AGNO_MODEL':'gpt-6-luna','OPENAI_API_KEY':'offline-http-fixture',
                                   'OPENAI_BASE_URL':'https://api.openai.com/v1'}):
            with TestClient(main.app) as client:
                verify(client)
        self.assertEqual(len(fixture_calls), 7)
