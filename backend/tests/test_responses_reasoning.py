"""Stateless Responses wire test for pinned Agno 3.2.0. No provider/network calls."""
import importlib.util
import json
from unittest import TestCase, skipUnless
from pydantic import BaseModel

@skipUnless(importlib.util.find_spec('agno') and importlib.util.find_spec('openai'), 'Agno required')
class ResponsesReasoningTests(TestCase):
    def test_real_agent_replays_reasoning_and_correlates_tool_output(self):
        import httpx
        from agno.agent import Agent
        from agno.models.openai import OpenAIResponses
        class Answer(BaseModel):
            answer: int
        packets=[]
        def calculator(expression: str) -> str:
            """Return the answer for the smoke fixture."""
            self.assertEqual(expression,'7*9+3')
            return '66'
        def respond(request):
            self.assertEqual(str(request.url),'https://api.openai.com/v1/responses')
            body=json.loads(request.content); packets.append(body)
            self.assertIs(body['store'],False)
            self.assertEqual(body['reasoning']['effort'],'high')
            self.assertNotIn('previous_response_id',body)
            self.assertEqual(body['tools'][0]['name'],'calculator')
            self.assertEqual(body['text']['format']['type'],'json_object')
            if len(packets)==1:
                output=[{'type':'reasoning','id':'rs_fixture','summary':[],'encrypted_content':'opaque-fixture-token'},
                        {'type':'function_call','id':'fc_fixture','call_id':'call_fixture','name':'calculator',
                         'arguments':'{"expression":"7*9+3"}','status':'completed'}]
            else:
                inputs=body['input']
                types=[i.get('type') for i in inputs]
                self.assertLess(types.index('reasoning'),types.index('function_call'))
                self.assertLess(types.index('function_call'),types.index('function_call_output'))
                reasoning=inputs[types.index('reasoning')]
                self.assertEqual(reasoning['encrypted_content'],'opaque-fixture-token')
                tool=inputs[types.index('function_call_output')]
                self.assertEqual(tool['call_id'],'call_fixture')
                self.assertEqual(tool['output'],'66')
                output=[{'type':'message','id':'msg_fixture','role':'assistant','status':'completed',
                         'content':[{'type':'output_text','text':'{"answer":66}','annotations':[]}]}]
            return httpx.Response(200,json={'object':'response','id':f'resp_fixture{len(packets)}',
                   'created_at':0,'model':'gpt-6-luna','status':'completed','output':output,
                   'parallel_tool_calls':False,'tool_choice':'auto','tools':[],
                   'error':None,'usage':None})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            model=OpenAIResponses(id='gpt-6-luna',api_key='offline-fixture',
                      base_url='https://api.openai.com/v1',store=False,reasoning_effort='high',http_client=client,max_retries=0)
            agent=Agent(model=model,tools=[calculator],tool_call_limit=4,output_schema=Answer,
                        use_json_mode=True,instructions='Return a JSON answer object.',telemetry=False)
            self.assertEqual(agent.run('Calculate 7*9+3').content,Answer(answer=66))
        self.assertEqual(len(packets),2)

    def test_opt_in_is_limited_to_research_evidence_not_regular_chat(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat, OpenAIResponses
        from app.agno_adapter import Plan, Review, TutorOutput, run_agno

        models={}
        def fixture(agent, prompt):
            models[agent.name]=agent.model
            if agent.name=='plan':
                return SimpleNamespace(content=Plan(tasks=['Find the supplied fact']))
            if agent.name=='review':
                return SimpleNamespace(content=Review(accepted=True,checks=[]))
            return SimpleNamespace(content=TutorOutput(text='Found fact',citations=[
                {'source_id':'s1','quote':'The supplied fact.'}]))
        env={'AGNO_DEEP_RESPONSES':'1','AGNO_MODEL':'gpt-6-luna','OPENAI_API_KEY':'offline-fixture'}
        request={'prompt':'Find fact','sources':[{'id':'s1','text':'The supplied fact.'}]}
        with patch.dict(os.environ,env), patch.object(Agent,'run',fixture):
            result=run_agno('research',request,lambda *_:None)
            self.assertFalse(result['research_status']['partial'])
            self.assertIsInstance(models['research_evidence_01'],OpenAIResponses)
            self.assertFalse(models['research_evidence_01'].store)
            self.assertEqual(models['research_evidence_01'].reasoning_effort,'high')
            for stage in ('plan','answer','review'):
                self.assertIsInstance(models[stage],OpenAIChat)
            run_agno('chat',request,lambda *_:None)
            self.assertIsInstance(models['answer'],OpenAIChat)
            self.assertEqual(models['answer'].reasoning_effort,'none')
