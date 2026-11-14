"""Native nested Team/Agent delegation over mock HTTP; no model API access."""
import copy
import json
import os
import unittest
from collections import Counter
from unittest.mock import patch
import httpx
from app.exam_blueprint import EXAMPLE_BLUEPRINT
from app.exam_teams import run_exam_teams
from app.exam_difficulty import difficulty_targets


def blueprint():
    b=copy.deepcopy(EXAMPLE_BLUEPRINT)
    b.update(total_points=20,duration_minutes=30)
    one=b['sections'][0]
    one.update(duration_minutes=None)
    two=copy.deepcopy(one); two.update(id='B',title='Fill blank')
    two['slots'][0].update(number='2',type='fill_blank',choice_labels=[],source_stem='Reference fill')
    b['sections'].append(two)
    return b

class NativeExamTeamsTests(unittest.TestCase):
    def execute(self, *, reject_once=False, no_delegation=False, foreign_slot=False, reject_always=False, leader_rewrite=False, bp=None, unauthorized=False, single_multi=False, split_short_answer=False):
        from agno.models.openai import OpenAIChat
        counts=Counter(); wire=[]; events=[]
        def response(request):
            body=json.loads(request.content);wire.append(body)
            system='\n'.join(m.get('content','') or '' for m in body['messages'] if m['role'] in ('system','developer'))
            tools=[t['function']['name'] for t in body.get('tools',[])]
            is_chief='Delegate once to all your direct question-type Teams' in system
            is_type='You are the leader of the ' in system
            is_solver='not shown the author answer' in system
            is_reviewer='Check the proposed problem' in system
            scope=None
            for pos in range(len(system)):
                if system[pos:].startswith('{"seed"'):
                    scope=json.JSONDecoder().raw_decode(system[pos:])[0]
            prior_tools=any(m['role']=='tool' for m in body['messages'])
            message={'role':'assistant','content':None}
            tool_count=sum(m['role']=='tool' for m in body['messages'])
            needs_geometry=split_short_answer and is_type and scope['slots'][0]['type']=='short_answer' and tool_count==1
            if (is_chief or is_type) and (not prior_tools or needs_geometry) and not no_delegation:
                self.assertEqual(body['reasoning_effort'],'none')
                if is_chief:
                    name='delegate_task_to_members'; args={'task':'Create only your assigned slots, use your system scope.'}
                else:
                    kind=scope['slots'][0]['type'];name='delegate_task_to_member'
                    role='geometry' if needs_geometry else 'algebra'
                    args={'member_id':'unauthorized-member' if unauthorized else 'exam-type-'+kind+'-'+role,'task':'Create the assigned slots from your system scope.'}
                    if needs_geometry:
                        tool_result=next(m['content'] for m in body['messages'] if m['role']=='tool')
                        returned=[i['number'] for i in json.JSONDecoder().raw_decode(tool_result[tool_result.index('{'):])[0]['items']]
                        self.assertEqual(returned,['17','18','19'])
                        args['task']='Only missing slots: solve:15, solve:16.'
                self.assertIn(name,tools)
                message['tool_calls']=[{'id':'call_'+str(len(wire)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]
            else:
                if is_solver:
                    content={'answer':'A','explanation':'Independent fixture solution'}
                    self.assertNotIn('author',body['messages'][-1]['content'])
                elif is_reviewer:
                    packet=json.loads(body['messages'][-1]['content']);key=packet['slot']['number'];counts['review-'+key]+=1
                    rejected=key=='2' and (reject_always or (reject_once and counts['review-'+key]==1))
                    content={'accepted':not rejected,'corrections':['Revise this slot'] if rejected else []}
                elif is_chief or is_type:
                    # Leaders relay member data. Native tool content is text plus JSON.
                    items=[]
                    for m in body['messages']:
                        if m['role']=='tool':
                            text=m.get('content',''); start=text.find('{')
                            if start>=0:
                                try:items+=json.JSONDecoder().raw_decode(text[start:])[0]['items']
                                except (ValueError,KeyError):pass
                    if leader_rewrite and is_type and items:
                        items[0]['answer']='FORGED'
                    content={'completed':True}
                else:
                    self.assertIsNotNone(scope,system)
                    items=[]
                    for slot in scope['slots']:
                        if split_short_answer and slot['type']=='short_answer':
                            geometry='Geometry, vectors and trigonometry question designer' in system
                            if (slot['number'] in ('15','16')) != geometry:
                                continue
                        counts[slot['number']]+=1
                        items.append({'section_id':slot['section_id'],'number':'99' if foreign_slot else slot['number'],
                            'stem':'Question '+slot['number']+' attempt '+str(counts[slot['number']]),
                            'choices':[{'label':x,'text':str(i)} for i,x in enumerate(slot['choice_labels'])],
                            'answer':((['A'] if single_multi else ['A','B']) if slot['type']=='multiple_choice' else ('A' if slot['choice_labels'] else '42')),'explanation':'Fixture derivation'})
                    content={'items':items}
                message['content']=json.dumps(content)
            return httpx.Response(200,json={'id':'chatcmpl-fixture','object':'chat.completion','created':0,'model':'gpt-6-luna',
                'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop'}],
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        # Each native async run may have a distinct event loop; MockTransport has no sockets.
        def factory(with_tools=False):
            return OpenAIChat(id='gpt-6-luna',api_key='offline-fixture',reasoning_effort='none' if with_tools else None,max_retries=0,
                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(response)))
        with patch('app.exam_teams._model',factory), patch('socket.socket.connect',side_effect=AssertionError('No network')):
            result=run_exam_teams({'blueprint':bp or blueprint(),'seed':8},lambda k,d:events.append((k,d)))
        return result,counts,events,wire

    def test_native_chief_type_leaders_and_designers(self):
        result,counts,events,wire=self.execute()
        self.assertEqual([len(s['items']) for s in result['sections']],[1,1])
        self.assertEqual(counts['1'],1);self.assertEqual(counts['2'],1)
        started=[d for k,d in events if k=='exam.delegation.started']
        self.assertEqual({d['team'] for d in started},{'chief','single_choice','fill_blank'})
        self.assertTrue(any(d.get('percent')==95 for k,d in events if k=='progress'))
        self.assertTrue(all('answer' not in d and 'stem' not in d for k,d in events))

    def test_only_failed_slot_is_regenerated(self):
        result,counts,events,_=self.execute(reject_once=True)
        self.assertEqual(counts['1'],1);self.assertEqual(counts['2'],2)
        self.assertEqual([d['number'] for k,d in events if k=='exam.slot.retrying'],['2'])
        self.assertIn('attempt 1',result['sections'][0]['items'][0]['stem'])
        self.assertIn('attempt 2',result['sections'][1]['items'][0]['stem'])

    def test_leader_prompt_survives_partial_result_and_native_followup(self):
        from pathlib import Path
        fixture=json.loads((Path(__file__).parents[2]/'examples/exam-artifacts/gaokao-i-2026-structure.json').read_text())
        b=fixture['inputs']['blueprint']
        result,counts,events,wire=self.execute(bp=b,split_short_answer=True)
        lead=['\n'.join(m.get('content') or '' for m in r['messages'] if m['role'] in ('developer','system'))
              for r in wire if any('leader of the short_answer question-type team' in (m.get('content') or '') for m in r['messages'] if m['role'] in ('developer','system'))]
        self.assertEqual(len(lead),3)
        for prompt in lead:
            self.assertIn('compare required vs received',prompt.lower())
            self.assertIn('ONLY the missing slots',prompt)
            self.assertIn('is RECEIVED even if you suspect its math',prompt)
            self.assertIn('If MISSING is empty, stop delegating immediately.',prompt)
            self.assertIn('Leave all correctness, option quality, difficulty and scoring decisions to the independent reviewer.',prompt)
            self.assertIn('"off-target" means it did not return the requested slot IDs',prompt)
            self.assertIn('exam-type-short_answer-geometry',prompt)
            self.assertIn('Required slot IDs for this run (section_id:number) = ["solve:15", "solve:16", "solve:17", "solve:18", "solve:19"]',prompt)
        self.assertEqual([d['member'] for k,d in events if k=='exam.delegation.started' and d['team']=='short_answer'],
                         ['exam-type-short_answer-algebra','exam-type-short_answer-geometry'])
        self.assertEqual([counts[str(i)] for i in range(15,20)],[1]*5)
        self.assertEqual(len(result['answer_key']),19)

    def test_claimed_delegation_without_member_calls_fails(self):
        with self.assertRaises(ValueError):
            self.execute(no_delegation=True)

    def test_foreign_slot_fails_closed(self):
        with self.assertRaises(ValueError):
            self.execute(foreign_slot=True)

    def test_leader_ack_is_not_used_as_question_content(self):
        result,_,_,_=self.execute(leader_rewrite=True)
        self.assertTrue(all(a['answer']!='FORGED' for a in result['answer_key']))

    def test_failed_repair_does_not_publish_partial_paper(self):
        with self.assertRaisesRegex(ValueError,'unresolved slots'):
            self.execute(reject_always=True)

    def test_real_nineteen_slot_shape(self):
        from pathlib import Path
        fixture=json.loads((Path(__file__).parents[2]/'examples/exam-artifacts/gaokao-i-2026-structure.json').read_text())
        b=fixture.get('blueprint',fixture.get('inputs',{}).get('blueprint',fixture))
        result,counts,events,wire=self.execute(bp=b)
        self.assertEqual([len(s['items']) for s in result['sections']],[8,3,3,5])
        self.assertEqual(result['total_points'],150)
        self.assertEqual(sum(1 for k,d in events if k=='exam.slot.accepted'),19)
        progress=[d['completed'] for k,d in events if k=='progress']
        self.assertEqual(progress,list(range(1,20)))
        # 2 chief + 4*(2 leader + 1 batched designer) + 19*(solver+review).
        self.assertEqual(len(wire),52)
        self.assertTrue(all('difficulty' not in item for sec in result['sections'] for item in sec['items']))

    def test_unauthorized_designer_fails_closed(self):
        with self.assertRaises(ValueError):
            self.execute(unauthorized=True)

    def test_default_adapter_routes_exam_to_teams(self):
        from app.agno_adapter import run_agno
        with patch.dict(os.environ,{'OPENAI_API_KEY':'offline-placeholder','AGNO_EXAM_MODE':'teams'}), patch('app.exam_teams.run_exam_teams',return_value={'sentinel':1}) as run:
            self.assertEqual(run_agno('exam',{'blueprint':blueprint()},lambda *_:None),{'sentinel':1})
            run.assert_called_once()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'offline-placeholder','AGNO_EXAM_MODE':'typo'}), self.assertRaises(ValueError):
            run_agno('exam',{'blueprint':blueprint()},lambda *_:None)

    def test_multi_choice_requires_two_declared_answers(self):
        b=blueprint();b['sections'][0]['slots'][0]['type']='multiple_choice'
        with self.assertRaisesRegex(ValueError,'unresolved slots'):
            self.execute(bp=b,single_multi=True)

    def test_default_gaokao_targets_and_blueprint_immutability(self):
        from pathlib import Path
        fixture=json.loads((Path(__file__).parents[2]/'examples/exam-artifacts/gaokao-i-2026-structure.json').read_text())
        b=fixture['inputs']['blueprint']; before=copy.deepcopy(b)
        targets=difficulty_targets(b)
        expected=['foundation']*4+['standard']*3+['advanced']+['standard','advanced','challenge']+['foundation','standard','advanced']+['standard','advanced','advanced','challenge','challenge']
        self.assertEqual([targets[(sec['id'],slot['number'])]['band'] for sec in b['sections'] for slot in sec['slots']],expected)
        self.assertEqual(b,before)
        self.assertEqual(difficulty_targets(b),targets)

    def test_author_reviewer_and_repair_keep_the_same_difficulty(self):
        _,counts,_,wire=self.execute(reject_once=True)
        authored=[]; reviewed=[]
        for body in wire:
            system='\n'.join(m.get('content','') or '' for m in body['messages'] if m['role'] in ('system','developer'))
            if 'Create only the assigned slots.' in system:
                pos=system.find('{"seed"')
                packet=json.JSONDecoder().raw_decode(system[pos:])[0]
                if packet['slots'][0]['number']=='2':
                    authored.append(packet)
                    self.assertIn('返工不能自行降档',system)
            elif 'Check the proposed problem' in system:
                packet=json.loads(body['messages'][-1]['content'])
                if packet['slot']['number']=='2':
                    reviewed.append(packet)
                    self.assertIn('按slot.difficulty',system)
        self.assertEqual(len(authored),2);self.assertEqual(len(reviewed),2)
        target=difficulty_targets(blueprint())[('B','2')]
        self.assertTrue(all(p['slots'][0]['difficulty']==target for p in authored))
        self.assertTrue(all(p['slot']['difficulty']==target for p in reviewed))
        self.assertEqual(authored[1]['feedback'],['Revise this slot'])
        self.assertEqual(authored[1]['previous_draft']['number'],'2')
        self.assertEqual([s['number'] for s in authored[1]['slots']],['2'])
        self.assertEqual(counts['1'],1)

    def test_other_shapes_use_proportional_policy_without_score_changes(self):
        b=blueprint(); sec=b['sections'][0]; sec['slots']*=2
        sec['slots'][1]=copy.deepcopy(sec['slots'][1]); sec['slots'][1]['number']='3'
        before=copy.deepcopy(b); targets=difficulty_targets(b)
        self.assertEqual(targets[('A','1')]['band'],'foundation')
        self.assertEqual(targets[('A','3')]['band'],'standard')
        self.assertEqual(b,before)

    def test_limit_before_any_model(self):
        b=blueprint();b['sections'][0]['slots']*=31
        with patch('app.exam_teams._model',side_effect=AssertionError('No model should be made')),self.assertRaises(ValueError):
            run_exam_teams({'blueprint':b},lambda *_:None)
